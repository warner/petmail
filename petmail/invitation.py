import re, os, json, hmac
from hashlib import sha256
from twisted.python import log
from twisted.application import service
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
    def __init__(self, db, agent):
        service.MultiService.__init__(self)
        self.db = db
        self.agent = agent
        self._debug_invitations_completed = 0
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
        rows = self.db.execute("SELECT id FROM invitations"
                               " WHERE inviteID=? LIMIT 1",
                               (inviteID,)).fetchall()
        if not rows:
            raise KeyError(inviteID)
        iid = rows[0][0]
        i = Invitation(iid, self.db, self, self.agent)
        i.processMessages(messages)

    def sendToAll(self, inviteID, msg):
        #print "sendToAll", msg
        for rs in list(self):
            rs.send(inviteID, msg)

    def readyPendingInvitations(self):
        c = self.db.execute("SELECT inviteID FROM invitations")
        for (inviteID,) in c.fetchall():
            # this will fetch a batch of messages (possibly empty, if we
            # crashed before delivering our first one), which will trigger
            # resends or reactions to inbound messages
            self.subscribe(str(inviteID))

    def startInvitation(self, petname, code, my_signkey, payload, private):
        # "payload" goes to them, "private" stays with us
        #print "invite", petname, code.encode("hex")
        stretched = stretch(code)
        inviteKey = SigningKey(stretched)
        inviteID = inviteKey.verify_key.encode(Hex)
        myTempPrivkey = PrivateKey.generate()

        db = self.db
        c = db.execute("SELECT inviteID FROM invitations")
        if inviteID in [str(row[0]) for row in c.fetchall()]:
            raise CommandError("invitation code already in use")
        iid = db.insert("INSERT INTO `invitations`"
                        " (code, petname, inviteKey,"
                        "  inviteID,"
                        "  myTempPrivkey, mySigningKey,"
                        "  payload_for_them_json, my_private_invitation_data,"
                        "  myMessages, theirMessages, nextExpectedMessage)"
                        " VALUES (?,?,?, ?, ?,?, ?,?, ?,?,?)",
                        (code.encode("hex"), petname, stretched.encode("hex"),
                         inviteID,
                         myTempPrivkey.encode(Hex), my_signkey.encode(Hex),
                         json.dumps(payload), json.dumps(private),
                         "", "", 1),
                        "invitations")
        self.subscribe(inviteID)
        i = Invitation(iid, self.db, self, self.agent)
        i.sendFirstMessage()
        self.db.commit()

class Invitation:
    # This has a brief lifetime: one is created in response to the rendezvous
    # client discovering new messages for us, used for one reactor tick, then
    # dereferenced. It holds onto a few values during that tick (which may
    # process multiple messages for a single invitation, e.g. A's second poll
    # will receive both B-m1 and B-m2 together). But all persistent state
    # beyond that one tick is stored in the database.
    def __init__(self, iid, db, manager, agent):
        self.iid = iid
        self.db = db
        self.manager = manager
        self.agent = agent
        c = self.db.execute("SELECT petname, inviteID, inviteKey," # 0,1,2
                            " theirTempPubkey," # 3
                            " nextExpectedMessage," # 4
                            " myMessages," # 5
                            " theirMessages" # 6
                            " FROM invitations WHERE id = ?", (iid,))
        res = c.fetchone()
        if not res:
            raise KeyError("no pending Invitation for '%d'" % iid)
        self.petname = res[0]
        self.inviteID = str(res[1])
        self.inviteKey = SigningKey(res[2].decode("hex"))
        self.theirTempPubkey = None
        if res[3]:
            self.theirTempPubkey = PublicKey(res[3].decode("hex"))
        self.nextExpectedMessage = int(res[4])
        self.myMessages = splitMessages(res[5])
        self.theirMessages = splitMessages(res[6])

    def getAddressbookID(self):
        c = self.db.execute("SELECT addressbook_id FROM invitations"
                            " WHERE id = ?", (self.iid,))
        return c.fetchone()[0]

    def getMyTempPrivkey(self):
        c = self.db.execute("SELECT myTempPrivkey FROM invitations"
                            " WHERE id = ?", (self.iid,))
        return PrivateKey(c.fetchone()[0].decode("hex"))

    def getMySigningKey(self):
        c = self.db.execute("SELECT mySigningKey FROM invitations"
                            " WHERE id = ?", (self.iid,))
        return SigningKey(c.fetchone()[0].decode("hex"))

    def getPayloadForThem(self):
        c = self.db.execute("SELECT payload_for_them_json FROM invitations"
                            " WHERE id = ?", (self.iid,))
        return c.fetchone()[0]

    def getMyPrivateData(self):
        c = self.db.execute("SELECT my_private_invitation_data FROM invitations"
                            " WHERE id = ?", (self.iid,))
        return json.loads(c.fetchone()[0])


    def sendFirstMessage(self):
        pub = self.getMyTempPrivkey().public_key.encode()
        self.send("i0:m1:"+pub)
        self.db.update("UPDATE invitations SET myMessages=? WHERE id=?",
                       (",".join(self.myMessages), self.iid),
                       "invitations", self.iid)
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
        #for m in self.myMessages - messages:
        #    #print "resending", m
        #    self.manager.sendToAll(self.inviteID, m)

        newMessages = messages - self.myMessages - self.theirMessages
        #print " %d new messages" % len(newMessages)
        if not newMessages:
            #print " huh, no new messages, stupid rendezvous client"
            pass

        # check signatures, extract bodies. invalid messages kill the channel
        # and the invitation. MAYBE TODO: lose the one channel, keep using
        # the others.
        messages_to_ignore = set()
        valid_bodies = {}
        for m in newMessages:
            try:
                if not m.startswith("r0:"):
                    print "unrecognized rendezvous message prefix"
                    messages_to_ignore.add(m) # ignore it next time
                    continue
                if not VALID_MESSAGE.search(m):
                    raise CorruptChannelError()
                decoded = m[len("r0:"):].decode("hex")
                body = self.inviteKey.verify_key.verify(decoded)
                valid_bodies[body] = m
            except (BadSignatureError, CorruptChannelError) as e:
                print "channel %s is corrupt" % self.inviteID
                if isinstance(e, BadSignatureError):
                    print " (bad sig)"
                self.unsubscribe(self.inviteID)
                # TODO: mark invitation as failed, destroy it
                return

        # these handlers will update self.myMessages with sent messages, and
        # will increment self.nextExpectedMessage. We can handle multiple
        # (sequential) messages in a single pass.
        def call_if_prefixed(prefix, handler):
            for b in valid_bodies:
                if b.startswith(prefix):
                    messages_to_ignore.add(valid_bodies[b])
                    handler(b[len(prefix):])
                    return

        if self.nextExpectedMessage == 1:
            call_if_prefixed("i0:m1:", self.processM1)
        # no elif here: self.nextExpectedMessage may have incremented
        if self.nextExpectedMessage == 2:
            call_if_prefixed("i0:m2:", self.processM2)
        if self.nextExpectedMessage == 3:
            call_if_prefixed("i0:m3:", self.processM3)

        self.db.update("UPDATE invitations SET"
                       "  myMessages=?,"
                       "  theirMessages=?,"
                       "  nextExpectedMessage=?"
                       " WHERE id=?",
                       (",".join(self.myMessages),
                        ",".join(self.theirMessages | messages_to_ignore),
                        self.nextExpectedMessage,
                        self.iid),
                       "invitations", self.iid)
        #print " db.commit"
        self.db.commit()

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
        self.theirTempPubkey = PublicKey(msg)
        self.db.update("UPDATE invitations SET theirTempPubkey=?"
                       " WHERE id=?",
                       (self.theirTempPubkey.encode(Hex), self.iid),
                       "invitations", self.iid)
        # theirTempPubkey will committed by our caller, in the same txn as
        # the message send

        my_privkey = self.getMyTempPrivkey()
        payload_for_them = self.getPayloadForThem()
        b = Box(my_privkey, self.theirTempPubkey)
        signedBody = b"".join([self.theirTempPubkey.encode(),
                               my_privkey.public_key.encode(),
                               payload_for_them.encode("utf-8")])
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
        my_privkey = self.getMyTempPrivkey()
        b = Box(my_privkey, self.theirTempPubkey)
        #nonce = msg[:Box.NONCE_SIZE]
        #ciphertext = msg[Box.NONCE_SIZE:]
        #print "DECRYPTING n+ct", len(msg), msg.encode("hex")
        body = b.decrypt(nonce_and_ciphertext)
        if not body.startswith("i0:m2a:"):
            raise ValueError("expected i0:m2a:, got '%r'" % body[:20])
        verfkey_and_signedBody = body[len("i0:m2a:"):]
        theirVerfkey = VerifyKey(verfkey_and_signedBody[:32])
        signedBody = verfkey_and_signedBody[32:]
        body = theirVerfkey.verify(signedBody)
        check_myTempPubkey = body[:32]
        check_theirTempPubkey = body[32:64]
        payload_for_us_json = body[64:].decode("utf-8")
        #print " binding checks:"
        #print " check_myTempPubkey", check_myTempPubkey.encode("hex")
        #print " my real tempPubkey", my_privkey.public_key.encode(Hex)
        #print " check_theirTempPubkey", check_theirTempPubkey.encode("hex")
        #print " first theirTempPubkey", self.theirTempPubkey.encode(Hex)
        if check_myTempPubkey != my_privkey.public_key.encode():
            raise ValueError("binding failure myTempPubkey")
        if check_theirTempPubkey != self.theirTempPubkey.encode():
            raise ValueError("binding failure theirTempPubkey")

        them = json.loads(payload_for_us_json)
        me = self.getMyPrivateData()
        cid = self.agent.invitation_done(self.petname, me, them, theirVerfkey)
        self.db.update("UPDATE invitations SET addressbook_id=?"
                       " WHERE id=?", (cid, self.iid),
                       "invitations", self.iid)

        msg3 = "i0:m3:ACK-"+os.urandom(16)
        self.send(msg3)
        self.nextExpectedMessage = 3

    def processM3(self, msg):
        #print "processM3", repr(msg[:10]), "..."
        if not msg.startswith("ACK-"):
            raise ValueError("bad ACK")
        self.agent.invitation_acked(self.getAddressbookID())
        self.db.delete("DELETE FROM invitations WHERE id=?", (self.iid,),
                       "invitations", self.iid)
        # we no longer care about the channel
        msg4 = "i0:destroy:"+os.urandom(16)
        self.send(msg4, persist=False)
        self.manager.unsubscribe(self.inviteID)
        self.manager._debug_invitations_completed += 1
        log.msg("addressbook entry added for petname=%r" % self.petname)
