
import re, os, json, hmac
from hashlib import sha256
from twisted.application import service
from . import rrid
from .hkdf import HKDF
from .errors import CommandError
from nacl.signing import SigningKey, VerifyKey, BadSignatureError
from nacl.public import PrivateKey, PublicKey, Box
from nacl.encoding import HexEncoder as Hex

assert Box.NONCE_SIZE == 24

# sk = SigningKey.generate() or SigningKey(seed)
# vk = sk.verify_key.encode() or .encode(Hex) or VerifyKey(bytes)
# sigmsg = sk.sign(msg)
# msg = vk.verify(sm) or nacl.signing.BadSignatureError

# privkey = PrivateKey.generate() or PrivateKey(bytes)
# pubkey = privkey.public_key or PublicKey(bytes)
# pubkey.encode()
# nonce+ct = Box(privkey, pubkey).encrypt(body, nonce)
#  or body=box.decrypt(ct, nonce)
#  or body=box.decrypt(ct+nonce)

# all messages are r0:hex(sigmsg(by-code, msg))
# A->B: i0:m1:tmpA
# B->A: i0:m1:tmpB
# B->A: i0:m2:enc(to=tmpA,from=tmpB, i0:m2a:verfB+sig(tmpA+tmpB+tportB))
# A->B: i0:m2:enc(to=tmpB,from=tmpA, i0:m2a:verfA+sig(tmpB+tmpA+tportA))
# A->B: i0:m3:ACK-nonce
# B->A: i0:m3:ACK-nonce
# B->A: i0:destroy:nonce  # (1-of-2)
# A->B: i0:destroy:nonce  # (2-of-2)

class CorruptChannelError(Exception):
    pass

VALID_INVITEID = re.compile(r'^[0-9a-f]+$')
VALID_MESSAGE = re.compile(r'^r0:[0-9a-f]+$')

def stretch(code):
    # TODO: spend some quality time with scrypt
    return HKDF("stretched-" + code, 32)

def HMAC(key, msg):
    return hmac.new(key, msg, sha256).digest()

def splitMessages(s):
    if not s:
        return set()
    return set(str(s).split(","))

class InvitationManager(service.MultiService):
    """I manage all invitations, as well as connections to the rendezvous
    servers
    """
    def __init__(self, db, client):
        service.MultiService.__init__(self)
        self.db = db
        self.client = client
        # all my service children are Rendezvous services

    def startService(self):
        service.MultiService.startService(self)
        self.readyPendingInvitations()

    def addRendezvousService(self, rs):
        rs.setServiceParent(self)

    def subscribe(self, inviteID):
        for rs in list(self):
            rs.subscribe(inviteID)

    def unsubscribe(self, inviteID):
        for rs in list(self):
            rs.unsubscribe(inviteID)

    def messagesReceived(self, inviteID, messages):
        i = Invitation(inviteID, self.db, self) # might raise KeyError
        i.processMessages(messages)

    def sendToAll(self, inviteID, msg):
        #print "sendToAll", msg
        for rs in list(self):
            rs.send(inviteID, msg)

    def readyPendingInvitations(self):
        c = self.db.cursor()
        c.execute("SELECT inviteID FROM invitations")
        for (inviteID,) in c.fetchall():
            # this will fetch a batch of messages (possibly empty, if we
            # crashed before delivering our first one), which will trigger
            # resends or reactions to inbound messages
            self.subscribe(str(inviteID))

    def startInvitation(self, petname, code, mailbox):
        #print "invite", petname, code.encode("hex")
        stretched = stretch(code)
        inviteKey = SigningKey(stretched)
        inviteID = inviteKey.verify_key.encode(Hex)
        mySigningKey = SigningKey.generate()
        myTempPrivkey = PrivateKey.generate()
        # create my transport record
        channel_key = PrivateKey.generate()
        private_CID, sender_CID = rrid.create()
        pub_tport = { "channel_pubkey": channel_key.public_key.encode(Hex),
                      "CID": sender_CID.encode("hex"),
                      "STID": rrid.randomize(mailbox["TID"]).encode("hex"),
                      "mailbox_descriptor": mailbox["descriptor"],
                      }
        priv_tport = { "my_signkey": mySigningKey.encode(Hex),
                       "my_private_CID": private_CID.encode("hex"),
                       "my_old_channel_privkey": channel_key.encode(Hex),
                       "my_new_channel_privkey": channel_key.encode(Hex),
                       }

        c = self.db.cursor()
        c.execute("SELECT inviteID FROM invitations")
        if inviteID in [str(row[0]) for row in c.fetchall()]:
            raise CommandError("invitation code already in use")
        c.execute("INSERT INTO `invitations`"
                  " (code_hex, petname, inviteKey,"
                  "  inviteID,"
                  "  myTempPrivkey, mySigningKey,"
                  "  myTransportRecord, myPrivateTransportRecord,"
                  "  myMessages, theirMessages, nextExpectedMessage)"
                  " VALUES (?,?,?, ?, ?,?, ?,?, ?,?,?)",
                  (code.encode("hex"), petname, stretched.encode("hex"),
                   inviteID,
                   myTempPrivkey.encode(Hex), mySigningKey.encode(Hex),
                   json.dumps(pub_tport), json.dumps(priv_tport),
                   "", "", 1))
        self.subscribe(inviteID)
        i = Invitation(inviteID, self.db, self)
        i.sendFirstMessage()
        self.db.commit()

class Invitation:
    # This has a brief lifetime: one is created in response to the rendezvous
    # client discovering new messages for us, used for one reactor tick, then
    # dereferenced. It holds onto a few values during that tick (which may
    # process multiple messages for a single invitation, e.g. A's second poll
    # will receive both B-m1 and B-m2 together). But all persistent state
    # beyond that one tick is stored in the database.
    def __init__(self, inviteID, db, manager):
        self.inviteID = inviteID
        self.db = db
        self.manager = manager
        c = db.cursor()
        c.execute("SELECT petname, inviteKey," # 0,1
                  " theirTempPubkey," # 2
                  " theirVerfkey," # 3
                  " nextExpectedMessage," # 4
                  " myMessages," # 5
                  " theirMessages" # 6
                  " FROM invitations WHERE inviteID = ?", (inviteID,))
        res = c.fetchone()
        if not res:
            raise KeyError("no pending Invitation for '%s'" % inviteID)
        self.petname = res[0]
        self.inviteKey = SigningKey(res[1].decode("hex"))
        self.theirTempPubkey = None
        if res[2]:
            self.theirTempPubkey = PublicKey(res[2].decode("hex"))
        # we stash theirVerfkey in the invitation just to correlate it with
        # the addressbook entry when the ACK arrives. We could easily stash
        # an addressbook-entry-id instead.
        self.theirVerfkey = None
        if res[3]:
            self.theirVerfkey = VerifyKey(res[3].decode("hex"))
        self.nextExpectedMessage = int(res[4])
        self.myMessages = splitMessages(res[5])
        self.theirMessages = splitMessages(res[6])

    def getMyTempPrivkey(self):
        c = self.db.cursor()
        c.execute("SELECT myTempPrivkey FROM invitations WHERE inviteID = ?",
                  (self.inviteID,))
        return PrivateKey(c.fetchone()[0].decode("hex"))

    def getMySigningKey(self):
        c = self.db.cursor()
        c.execute("SELECT mySigningKey FROM invitations WHERE inviteID = ?",
                  (self.inviteID,))
        return SigningKey(c.fetchone()[0].decode("hex"))

    def getMyTransportRecord(self):
        c = self.db.cursor()
        c.execute("SELECT myTransportRecord FROM invitations WHERE inviteID = ?",
                  (self.inviteID,))
        return c.fetchone()[0]

    def getMyPrivateTransportRecord(self):
        c = self.db.cursor()
        c.execute("SELECT myPrivateTransportRecord FROM invitations WHERE inviteID = ?",
                  (self.inviteID,))
        return json.loads(c.fetchone()[0])


    def sendFirstMessage(self):
        pub = self.getMyTempPrivkey().public_key.encode()
        self.send("i0:m1:"+pub)
        c = self.db.cursor()
        c.execute("UPDATE invitations SET  myMessages=? WHERE inviteID=?",
                  (",".join(self.myMessages), self.inviteID))
        # that will be commited by our caller

    def processMessages(self, messages):
        # These messages are neither version-checked nor signature-checked.
        # Also, we may have already processed some of them.
        #print "processMessages", messages
        #print " my", self.myMessages
        #print " theirs", self.theirMessages
        assert isinstance(messages, set), type(messages)
        assert None not in messages, messages
        assert None not in self.myMessages, self.myMessages
        assert None not in self.theirMessages, self.theirMessages
        # Send anything that didn't make it to the server. This covers the
        # case where we commit our outbound message in send() but crash
        # before finishing delivery.
        for m in self.myMessages - messages:
            #print "resending", m
            self.manager.sendToAll(self.inviteID, m)

        newMessages = messages - self.myMessages - self.theirMessages
        #print " %d new messages" % len(newMessages)
        if not newMessages:
            print " huh, no new messages, stupid rendezvous client"

        # check signatures, extract bodies. invalid messages kill the channel
        # and the invitation. MAYBE TODO: lose the one channel, keep using
        # the others.
        bodies = set()
        for m in newMessages:
            #print " new inbound message", m
            try:
                if not m.startswith("r0:"):
                    print "unrecognized rendezvous message prefix"
                if not VALID_MESSAGE.search(m):
                    raise CorruptChannelError()
                m = m[len("r0:"):].decode("hex")
                bodies.add(self.inviteKey.verify_key.verify(m))
            except (BadSignatureError, CorruptChannelError) as e:
                print "channel %s is corrupt" % self.inviteID
                if isinstance(e, BadSignatureError):
                    print " (bad sig)"
                self.unsubscribe(self.inviteID)
                # TODO: mark invitation as failed, destroy it
                return

        #print " new inbound bodies:", ", ".join([repr(b[:10])+" ..." for b in bodies])

        # these handlers will update self.myMessages with sent messages, and
        # will increment self.nextExpectedMessage. We can handle multiple
        # (sequential) messages in a single pass.
        if self.nextExpectedMessage == 1:
            self.findPrefixAndCall("i0:m1:", bodies, self.processM1)
            # no elif here: self.nextExpectedMessage may have incremented
        if self.nextExpectedMessage == 2:
            self.findPrefixAndCall("i0:m2:", bodies, self.processM2)
        if self.nextExpectedMessage == 3:
            self.findPrefixAndCall("i0:m3:", bodies, self.processM3)

        c = self.db.cursor()
        c.execute("UPDATE invitations SET"
                  "  myMessages=?, theirMessages=?, nextExpectedMessage=?"
                  " WHERE inviteID=?",
                  (",".join(self.myMessages),
                   ",".join(self.theirMessages | newMessages),
                   self.nextExpectedMessage,
                   self.inviteID))
        #print " db.commit"
        self.db.commit()

    def findPrefixAndCall(self, prefix, bodies, handler):
        for msg in bodies:
            if msg.startswith(prefix):
                return handler(msg[len(prefix):])
        return None

    def send(self, msg, persist=True):
        #print "send", repr(msg[:10]), "..."
        signed = "r0:%s" % self.inviteKey.sign(msg).encode("hex")
        if persist: # m4-destroy is not persistent
            self.myMessages.add(signed) # will be persisted by caller
            # This will be added to the DB, and committed, by our caller, to
            # get it into the same transaction as the update to which inbound
            # messages we've processed.
        assert VALID_MESSAGE.search(signed), signed
        self.manager.sendToAll(self.inviteID, signed)

    def processM1(self, msg):
        #print "processM1", self.petname
        c = self.db.cursor()
        self.theirTempPubkey = PublicKey(msg)
        c.execute("UPDATE invitations SET theirTempPubkey=? WHERE inviteID=?",
                  (self.theirTempPubkey.encode(Hex), self.inviteID))
        # theirTempPubkey will committed by our caller, in the same txn as
        # the message send

        my_priv = self.getMyTempPrivkey()
        my_tport = self.getMyTransportRecord()
        b = Box(my_priv, self.theirTempPubkey)
        signedBody = b"".join([self.theirTempPubkey.encode(),
                               my_priv.public_key.encode(),
                               my_tport.encode("utf-8")])
        my_sign = self.getMySigningKey()
        body = b"".join([b"i0:m2a:",
                         my_sign.verify_key.encode(),
                         my_sign.sign(signedBody)
                         ])
        nonce = os.urandom(Box.NONCE_SIZE)
        nonce_and_ciphertext = b.encrypt(body, nonce)
        #print "ENCRYPTED n+c", len(nonce_and_ciphertext), nonce_and_ciphertext.encode("hex")
        #print " nonce", nonce.encode("hex")
        msg2 = "i0:m2:"+nonce_and_ciphertext
        self.send(msg2)
        self.nextExpectedMessage = 2

    def processM2(self, msg):
        #print "processM2", repr(msg[:10]), "...", self.petname
        assert self.theirTempPubkey
        nonce_and_ciphertext = msg
        my_priv = self.getMyTempPrivkey()
        b = Box(my_priv, self.theirTempPubkey)
        #nonce = msg[:Box.NONCE_SIZE]
        #ciphertext = msg[Box.NONCE_SIZE:]
        #print "DECRYPTING n+ct", len(msg), msg.encode("hex")
        body = b.decrypt(nonce_and_ciphertext)
        if not body.startswith("i0:m2a:"):
            raise ValueError("expected i0:m2a:, got '%r'" % body[:20])
        verfkey_and_signedBody = body[len("i0:m2a:"):]
        self.theirVerfkey = VerifyKey(verfkey_and_signedBody[:32])
        signedBody = verfkey_and_signedBody[32:]
        body = self.theirVerfkey.verify(signedBody)
        check_myTempPubkey = body[:32]
        check_theirTempPubkey = body[32:64]
        theirTransportRecord_json = body[64:].decode("utf-8")
        #print " binding checks:"
        #print " check_myTempPubkey", check_myTempPubkey.encode("hex")
        #print " my real tempPubkey", my_priv.public_key.encode(Hex)
        #print " check_theirTempPubkey", check_theirTempPubkey.encode("hex")
        #print " first theirTempPubkey", self.theirTempPubkey.encode(Hex)
        if check_myTempPubkey != my_priv.public_key.encode():
            raise ValueError("binding failure myTempPubkey")
        if check_theirTempPubkey != self.theirTempPubkey.encode():
            raise ValueError("binding failure theirTempPubkey")

        them = json.loads(theirTransportRecord_json)
        me = self.getMyPrivateTransportRecord()
        c = self.db.cursor()
        c.execute("UPDATE invitations SET theirVerfkey=? WHERE inviteID=?",
                  (self.theirVerfkey.encode(Hex), self.inviteID))
        c.execute("INSERT INTO addressbook"
                  " (petname, acked,"
                  "  my_signkey, their_channel_pubkey,"
                  "  their_CID, their_STID, their_mailbox_descriptor,"
                  "  my_private_CID,"
                  "  my_old_channel_privkey, my_new_channel_privkey,"
                  "  they_used_new_channel_key, their_verfkey)"
                  " VALUES (?,?, "
                  "         ?,?,"
                  "         ?,?,?,"
                  "         ?,"
                  "         ?,?,"
                  "         ?,?)",
                  (self.petname, 0,
                   me["my_signkey"],
                   them["channel_pubkey"], them["CID"], them["STID"],
                   them["mailbox_descriptor"],
                   me["my_private_CID"],
                   me["my_old_channel_privkey"], me["my_new_channel_privkey"],
                   0, self.theirVerfkey.encode(Hex) ) )

        msg3 = "i0:m3:ACK-"+os.urandom(16)
        self.send(msg3)
        self.nextExpectedMessage = 3

    def processM3(self, msg):
        #print "processM3", repr(msg[:10]), "..."
        if not msg.startswith("ACK-"):
            raise ValueError("bad ACK")
        c = self.db.cursor()
        c.execute("UPDATE addressbook SET acked=1 WHERE their_verfkey=?",
                  (self.theirVerfkey.encode(Hex),))
        c.execute("DELETE FROM invitations WHERE inviteID=?",
                  (self.inviteID,))

        # we no longer care about the channel
        msg4 = "i0:destroy:"+os.urandom(16)
        self.send(msg4, persist=False)
        self.manager.unsubscribe(self.inviteID)
