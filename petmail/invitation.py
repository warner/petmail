
import json
from nacl.signing import SigningKey

# sk = SigningKey(seed)
# vk = sk.verify_key.encode()
# sigmsg = sk.sign(msg)
# msg = vk.verify(sm) or nacl.signing.BadSignatureError

def invite(db, petname, code):
    print "invite", petname, code

