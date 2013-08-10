
import json, os, hmac
from hashlib import sha256
from twisted.application import service
from .hkdf import HKDF
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
# Box(privkey, pubkey).encrypt(body, nonce) or .decrypt(ct, nonce)

# all messages are r0:hex(sigmsg(by-code, msg))
# A->B: i0:m1:tmpA
# B->A: i0:m1:tmpB
# B->A: i0:m2:enc(to=tmpA,from=tmpB, i0:m2a:verfB+sig(tmpA+tmpB+tportB))
# A->B: i0:m2:enc(to=tmpB,from=tmpA, i0:m2a:verfA+sig(tmpB+tmpA+tportA))
# A->B: i0:m3:ACK-nonce
# B->A: i0:m3:ACK-nonce
# B->A: i0:destroy:nonce  # (1-of-2)
# A->B: i0:destroy:nonce  # (2-of-2)

def stretch(code):
    # TODO: spend some quality time with scrypt
    return HKDF("stretched-" + code, 32)

def HMAC(key, msg):
    return hmac.new(key, msg, sha256).digest()

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

    def subscribe(self, channelID):
        for rs in list(self):
            rs.subscribe(channelID)

    def unsubscribe(self, channelID):
        for rs in list(self):
            rs.unsubscribe(channelID)

    def messagesReceived(self, channelID, messages):
        i = Invitation(channelID, self.db, self) # might raise KeyError
        i.processMessages(messages)

    def send(self, channelID, msg):
        for rs in list(self):
            rs.send(channelID, msg)

    def readyPendingInvitations(self):
        c = self.db.cursor()
        c.execute("SELECT channelID FROM invitations")
        for (channelID,) in c.fetchall():
            # this will fetch a batch of messages (possibly empty, if we
            # crashed before delivering our first one), which will trigger
            # resends or reactions to inbound messages
            self.subscribe(str(channelID))

    def startInvitation(self, petname, code, transportRecord,
                        privateTransportRecord):
        assert isinstance(transportRecord, dict)
        print "invite", petname, code.encode("hex")
        stretched = stretch(code)
        channelKey = SigningKey(stretched)
        channelID = channelKey.verify_key.encode(Hex)
        mySigningKey = SigningKey.generate()
        myTempPrivkey = PrivateKey.generate()
        c = self.db.cursor()
        c.execute("INSERT INTO `invitations`"
                  " (code, petname, stretchedKey,"
                  "  channelID,"
                  "  myTempPrivkey, mySigningKey,"
                  "  myTransportRecord, myPrivateTransportRecord,"
                  "  nextExpectedMessage) VALUES (?,?,?, ?, ?,?, ?,?, ?)",
                  (code.encode("hex"), petname, stretched.encode("hex"),
                   channelID,
                   myTempPrivkey.encode(Hex), mySigningKey.encode(Hex),
                   json.dumps(transportRecord),
                   json.dumps(privateTransportRecord),
                   1))
        self.db.commit()

        i = Invitation(channelID, self.db, self)
        i.sendFirstMessage()
        self.subscribe(channelID)

class Invitation:
    # This has a brief lifetime.
    def __init__(self, channelID, db, manager):
        self.channelID = channelID
        self.db = db
        self.manager = manager
        c = db.cursor()
        c.execute("SELECT petname, stretchedKey, myTempPrivkey, mySigningKey,"
                  " theirTempPubkey,"
                  " myTransportRecord, myPrivateTransportRecord,"
                  " nextExpectedMessage,"
                  " myM1, myM2, myM3"
                  " FROM invitations WHERE channelID = ?", (channelID,))
        res = c.fetchone()
        if not res:
            raise KeyError("no pending Invitation for '%s'" % channelID)
        self.petname = res[0]
        self.channelKey = SigningKey(res[1].decode("hex"))
        self.myTempPrivkey = PrivateKey(res[2].decode("hex"))
        self.mySigningKey = SigningKey(res[3].decode("hex"))
        self.theirTempPubkey = None
        if res[4]:
            self.theirTempPubkey = PublicKey(res[4].decode("hex"))
        self.myTransportRecord = res[5]
        self.myPrivateTransportRecord = res[6]
        self.nextExpectedMessage = int(res[7])
        self.myMessages = set([str(m) for m in res[8:11] if m])

    def sendFirstMessage(self):
        pub = self.myTempPrivkey.public_key.encode()
        self.send(1, "i0:m1:"+pub)

    def processMessages(self, messages):
        print "processMessages", messages
        assert isinstance(messages, set)
        # Send anything that didn't make it to the server. This covers the
        # case where we commit our outbound message in send() but crash
        # before finishing delivery.
        for m in self.myMessages - messages:
            self.manager.send(self.channelID, m)

        theirMessages = messages - self.myMessages

        # check signatures, extract bodies, ignore invalid messages
        bodies = set()
        for m in theirMessages:
            if not m.startswith("r0:"):
                print "unrecognized rendezvous message prefix"
                continue
            m = m[len("r0:"):].decode("hex")
            try:
                bodies.add(self.channelKey.verify_key.verify(m))
            except BadSignatureError:
                print "invalid message (bad sig) on", self.channelID
                pass

        if self.nextExpectedMessage == 1:
            self.findPrefixAndCall("i0:m1:", bodies, self.processM1)
            # that may change self.nextExpectedMessage, so no elif here
        if self.nextExpectedMessage == 2:
            self.findPrefixAndCall("i0:m2:", bodies, self.processM2)
        if self.nextExpectedMessage == 3:
            self.findPrefixAndCall("i0:m3:", bodies, self.processM3)

    def findPrefixAndCall(self, prefix, bodies, handler):
        for msg in bodies:
            if msg.startswith(prefix):
                return handler(msg[len(prefix):])
        return None

    def send(self, which, msg):
        print "send", which, repr(msg[:10]), "..."
        signed = "r0:%s" % self.channelKey.sign(msg).encode("hex")
        if which < 4: # m4-destroy is not persistent
            colname = {1: "myM1", 2: "myM2", 3: "myM3"}[which]
            c = self.db.cursor()
            # committing this to the DB means we'll send it eventually
            c.execute("UPDATE invitations SET %s=? WHERE channelID=?" % colname,
                      (self.channelID, signed))
            self.db.commit()
        self.manager.send(self.channelID, signed)

    def processM1(self, msg):
        print "processM1"
        c = self.db.cursor()
        self.theirTempPubkey = PublicKey(msg)
        c.execute("UPDATE invitations SET theirTempPubkey=? WHERE channelID=?",
                  (self.channelID, self.theirTempPubkey.encode(Hex),))

        b = Box(self.myTempPrivkey, self.theirTempPubkey)
        hex_tport = self.myTransportRecord.encode("utf-8").encode("hex")
        signedBody = b"".join([self.theirTempPubkey.encode(),
                               self.myTempPrivkey.public_key.encode(),
                               hex_tport])
        body = b"".join([b"i0:m2a:",
                         self.mySigningKey.verify_key.encode(),
                         self.mySigningKey.sign(signedBody)
                         ])
        nonce = os.urandom(Box.NONCE_SIZE)
        ciphertext = b.encrypt(body, nonce)
        msg2 = "i0:m2:"+nonce+ciphertext
        self.send(2, msg2) # this also commits theirTempPubkey

    def processM2(self, msg):
        print "processM2"
        b = Box(self.myTempPrivkey, self.theirTempPubkey)
        nonce = msg[:Box.NONCE_SIZE]
        ciphertext = msg[Box.NONCE_SIZE:]
        body = b.decrypt(ciphertext, nonce)
        if not body.startswith("i0:m2a:"):
            raise ValueError("expected i0:m2a:, got '%r'" % body[:20])
        verfkey_and_signedBody = body[len("i0:m2a:"):]
        theirVerfKey = VerifyKey(verfkey_and_signedBody[:32])
        signedBody = verfkey_and_signedBody[32:]
        body = theirVerfKey.verify(signedBody)
        check_myTempPubkey = body[:32]
        check_theirTempPubkey = body[32:64]
        theirTransportRecord_json = body[64:].decode("utf-8")
        if check_myTempPubkey != self.myTempPrivkey.public_key.encode():
            raise ValueError("binding failure myTempPubkey")
        if check_theirTempPubkey != self.theirTempPubkey:
            raise ValueError("binding failure theirTempPubkey")

        c = self.db.cursor()
        c.execute("INSERT INTO addressbook"
                  " (their_verfkey, their_transport_record_json,"
                  "  petname, my_signkey,"
                  "  my_private_transport_record_json, acked)"
                  " VALUES (?,?, ?,?, ?,?)",
                  (theirVerfKey.encode(Hex), theirTransportRecord_json,
                   self.petname, self.mySigningKey.encode("hex"),
                   self.myPrivateTransportRecord, 0))
        # myPrivateTransportRecord will include our inbound privkeys for
        # everything we told them in the transport record (long-term privkey,
        # old+new rotating keys).

        msg3 = "i0:m3:ACK-"+os.urandom(16)
        self.send(3, msg3)

    def processM3(self, msg):
        print "processM3"
        if not msg.startswith("i0:m3:ACK"):
            raise ValueError("bad ACK")
        c = self.db.cursor()
        c.execute("UPDATE addressbook SET acked=1 WHERE their_verfkey=?",
                  (self.theirVerfKey.encode(Hex),))
        c.execute("DELETE FROM invitations WHERE channelID=?",
                  (self.channelID,))
        self.db.commit()

        # we no longer care about the channel
        msg4 = "i0:destroy:"+os.urandom(16)
        self.send(4, msg4)
        self.manager.unsubscribe(self.channelID)
