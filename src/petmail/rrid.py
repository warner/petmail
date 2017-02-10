
# "rrid": re-randomized IDs, using ElGamal-encrypted tokens. These encrypted
# tokens can be given to someone else, then re-encrypted (multiple times)
# without letting them know the actual token value. The holder of the private
# key can decrypt these to recover the original token. We only use this to
# compare the decrypted token against the original, so we define "tokenid" to
# be the hash of the encrypted random message, and return tokenid from both
# creation and decryption functions.

# in multiplicative notation:
#  privkey "SK" = x
#  pubkey  "PK" = g^x
#  encrypt(m) = (c1,c2); pick r; c1 = g^r; c2 = (g^x)^r * m
#  rerand(c1,c2)= (newc1,newc2); pick s; newc1 = g^s *c1; newc2 = (g^x)^s *c2
#  decrypt(c1,c2)= c2 / (c2^x) = m

# in additive notation: (base point "B", msg is point M)
#  privkey "SK" = x
#  pubkey  "PK" = Bx
#  encrypt(m) = (C1,C2); pick r; C1 = Br; C2 = Bxr+M
#  rerand(C1,C2)= (newC1,newC2); pick s; newC1 = Bs+C1; newC2 = Bxs+C2
#  decrypt(C1,C2)= C2-xC1 = M

# M = random
# tokenid = hash(M)
# the final recipient remembers privkey and tokenid
# token0: pubkey+M (rerandomizable, safe when each sender gets a unique token)
# token[N]: pubkey+enc(M) (to prevent senders from comparing tokens)

# privkey,pubkey = rrid.create_keypair()
# tokenid,token1 = rrid.create_token(pubkey)
# token2 = rrid.randomize(token1)
# tokenid = rrid.decrypt(privkey, token)

import os
from hashlib import sha256
from .util import split_into

TOKEN_LENGTH = 32+32+32

# actual crypto is stubbed out for now

def create_keypair():
    privkey = "\x11"*32
    pubkey = "\x22"*32
    return privkey, pubkey

def create_token(pubkey):
    message = os.urandom(32)
    tokenid = sha256(message).digest()
    IDENTITY_ELEMENT = "\x00"*32
    # encrypting with r=0 gives (IDENTITY_ELEMENT,m), which is suitable for
    # the first token (which is not encrypted), and can also be fed into
    # rerandomize().
    nullencrypted_token = pubkey + IDENTITY_ELEMENT + message
    return tokenid, nullencrypted_token

def decrypt(privkey, token):
    assert len(privkey) == 32
    assert privkey == "\x11"*32
    pubkey, C1, C2 = split_into(token, [32,32,32])
    message = C2
    tokenid = sha256(message).digest()
    return tokenid

def randomize(token):
    pubkey, C1, C2 = split_into(token, [32,32,32])
    return pubkey+os.urandom(32)+C2
