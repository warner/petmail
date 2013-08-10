
import json, os, hmac
from hashlib import sha256
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

def startInvitation(db, rendezvouser, petname, code, transportRecord):
    assert isinstance(transportRecord, dict)
    print "invite", petname, code.encode("hex")
    stretched = stretch(code)
    mySigningKey = SigningKey.generate()
    myTempPrivkey = PrivateKey.generate()
    c = db.cursor()
    c.execute("INSERT INTO `invitations`"
              " (code, petname, stretchedKey,"
              "  myTempPrivkey, mySigningKey,"
              "  myTransportRecord,"
              "  nextExpectedMessage) VALUES (?,?,?,?,?,?)",
              (code.encode("hex"), petname, stretched.encode("hex"),
               myTempPrivkey.encode(Hex), mySigningKey.encode(Hex),
               json.dumps(transportRecord).encode("utf-8").encode("hex"),
               1))
    db.commit()

    channelKey = SigningKey(stretched)
    channelID = channelKey.verify_key.encode(Hex)
    i = Invitation(channelID, db, rendezvouser)
    i.sendFirstMessage()
    rendezvouser.subscribe(channelID)

def readyPendingInvitations(db, rendezvouser):
    c = db.cursor()
    c.execute("SELECT channelID FROM invitations")
    for (channelID,) in c.fetchall():
        i = Invitation(channelID, db, rendezvouser)
        # this is kept alive by the rendezvouser's subscription table
        del i

class Invitation:
    # This has a brief lifetime.
    def __init__(self, channelID, db, rendezvouser):
        self.channelID = channelID
        self.db = db
        self.rendezvouser = rendezvouser
        c = db.cursor()
        c.execute("SELECT petname, stretchedKey, myTempPrivkey, mySigningKey,"
                  " theirTempPubkey, myTransportRecord, nextExpectedMessage,"
                  " myM1_hex, myM2_hex, myM3_hex"
                  " FROM invitations WHERE channelID = ?", (channelID,))
        res = c.fetchone()
        self.petname = res[0]
        self.channelKey = SigningKey(res[1].decode("hex"))
        self.myTempPrivkey = PrivateKey(res[2].decode("hex"))
        self.mySigningKey = SigningKey(res[3].decode("hex"))
        self.theirTempPubkey = None
        if res[4]:
            self.theirTempPubkey = PublicKey(res[4].decode("hex"))
        self.myTransportRecord = res[5].decode("hex")
        self.nextExpectedMessage = int(res[6])
        self.myMessages = set([m.decode("hex") for m in res[7:10] if m])

    def sendFirstMessage(self):
        pub = self.myTempPrivkey.public_key.encode()
        self.send(1, "i0:m1:"+pub)

    def processMessages(self, messages):
        assert isinstance(messages, set)
        # Send anything that didn't make it to the server. This covers the
        # case where we commit our outbound message in send() but crash
        # before finishing delivery.
        for m in self.myMessages - messages:
            self.rendezvouser.send(self.channelID, m)

        theirMessages = messages - self.myMessages

        # check signatures, extract bodies, ignore invalid messages
        bodies = set()
        for m in theirMessages:
            try:
                bodies.add(self.channelKey.verify_key.verify(m))
            except BadSignatureError:
                print "invalid message on", self.channelID
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
        signed = "r0:%s" % self.channelKey.sign(msg).encode("hex")
        if which < 4: # m4-destroy is not persistent
            colname = {1: "myM1_hex", 2: "myM2_hex", 3: "myM3_hex"}[which]
            c = self.db.cursor()
            # committing this to the DB means we'll send it eventually
            c.execute("UPDATE invitations WHERE channelID=? SET %s=?" % colname,
                      (self.channelID, msg.encode("hex"),))
            self.db.commit()
        self.rendezvouser.send(self.channelID, signed)

    def processM1(self, msg):
        c = self.db.cursor()
        self.theirTempPubkey = PublicKey(msg)
        c.execute("UPDATE invitations WHERE channelID=? SET theirTempPubkey=?",
                  (self.channelID, self.theirTempPubkey.encode(Hex),))

        b = Box(self.myTempPrivkey, self.theirTempPubkey)
        signedBody = b"".join([self.theirTempPubkey.encode(),
                               self.myTempPrivkey.public_key.encode(),
                               self.myTransportRecord])
        body = b"".join([b"i0:m2a:",
                         self.mySigningKey.verify_key.encode(),
                         self.mySigningKey.sign(signedBody)
                         ])
        nonce = os.urandom(Box.NONCE_SIZE)
        ciphertext = b.encrypt(body, nonce)
        msg2 = "i0:m2:"+nonce+ciphertext
        self.send(2, msg2) # this also commits theirTempPubkey

    def processM2(self, msg):
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
                  " (their_verfkey, transport_record_json, petname,"
                  "  my_signkey, acked)"
                  " VALUES (?,?,?,?,?)",
                  (theirVerfKey.encode(Hex),
                   theirTransportRecord_json,
                   self.petname,
                   self.mySigningKey.encode("hex"), 0))
        # We also need to store inbound privkeys for everything we told them
        # in the transport record (long-term privkey, old+new rotating keys).
        # Figure that out later.

        msg3 = "i0:m3:ACK-"+os.urandom(16)
        self.send(3, msg3)

    def processM3(self, msg):
        if not msg.startswith("i0:m3:ACK"):
            raise ValueError("bad ACK")
        c = self.db.cursor()
        c.execute("UPDATE addressbook WHERE their_verfkey=? SET acked=1",
                  (self.theirVerfKey.encode(Hex),))
        c.execute("DELETE FROM invitations WHERE channelID=?",
                  (self.channelID,))
        self.db.commit()

        # we no longer care about the channel
        msg4 = "i0:destroy:"+os.urandom(16)
        self.send(4, msg4)
        self.rendezvouser.unsubscribe(self.channelID)


def rendezvousMessagesReceived(db, rendezvouser, channelID, messages):
    pass
