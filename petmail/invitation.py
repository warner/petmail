
import json
from hashlib import sha256
import hmac
from .hkdf import HKDF
from nacl.signing import SigningKey
from nacl.public import PrivateKey
from nacl.secret import SecretBox
from nacl.encoding import HexEncoder as Hex

# sk = SigningKey(seed)
# vk = sk.verify_key.encode()
# sigmsg = sk.sign(msg)
# msg = vk.verify(sm) or nacl.signing.BadSignatureError

# A->B: MAC(by=code, tmpA)
# B->A: MAC(by=code, tmpB), enc(to=tmpA,from=tmpB, verfB+sig(tmpA+tmpB))
# A->B: enc(to=B,from=A, verfA+sig(tmpA+tmpB))
# B: destroy channel

def stretch(code):
    # TODO: spend some quality time with scrypt
    return HKDF("stretched-" + code, 32)

def HMAC(key, msg):
    return hmac.new(key, msg, sha256).digest()

def invite(db, rendezvouser, petname, code):
    print "invite", petname, code.encode("hex")
    stretched = stretch(code)
    channelKey = SigningKey(stretched)
    channelID = channelKey.verify_key.encode(Hex)

    myTempPrivkey = PrivateKey.generate()
    pub = myTempPrivkey.public_key.encode()
    c = db.cursor()
    c.execute("INSERT INTO `invitations` (code, stretchedKey, myTempPrivkey)"
              " VALUES (?,?,?)", (code.encode("hex"),
                                  stretched.encode("hex"),
                                  myTempPrivkey.encode(Hex)))
    db.commit()

    rendezvouser.subscribe(channelID)

    msg1 = "invite-v1:%s" % channelKey.sign("m1:"+pub).encode("hex")
    print "msg1", msg1
    rendezvouser.send(channelID, msg1)

def rendezvousMessagesReceived(db, rendezvouser, channelID, messages):
    pass
