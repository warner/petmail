
import json
from hashlib import sha256
import hmac
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
    return "stretched-" + code

def HMAC(key, msg):
    return hmac.new(key, msg, sha256).digest()

def invite(db, petname, code):
    print "invite", petname, code
    stretched = stretch(code)
    myTempPrivkey = PrivateKey.generate()
    pub_hex = myTempPrivkey.public_key.encode(Hex)
    c = db.cursor()
    c.execute("INSERT INTO `invitations` (code, stretchedKey, myTempPrivkey)"
              " VALUES (?,?,?)", (code, stretched, myTempPrivkey.encode(Hex)))
    db.commit()
    
    msg1 = "invite-v1:%s:%s" % (pub_hex, HMAC(stretched, pub_hex).encode("hex"))
    print "msg1", msg1

