
# "rrid": re-randomized IDs, using ElGamal-encrypted tokens. These encrypted
# tokens can be given to someone else, then re-encrypted (multiple times)
# without letting them know the actual token value. The holder of the private
# key can decrypt these to recover the original token.

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

import os

def split(s):
    assert len(s)==3*32
    return s[:32], s[32:64], s[64:]

def create_token():
    # actual crypto is stubbed out for now
    privkey = "\x00"*32
    pubkey = "\x11"*32
    token = os.urandom(32)
    # the encrypted token we return can be rerandomized all by itself
    encrypted_token = pubkey+os.urandom(32)+token
    return token, privkey, encrypted_token

def rerandomize_token(encrypted_token):
    pubkey, one, two = split(encrypted_token)
    return pubkey+os.urandom(32)+two

def decrypt(privkey, encrypted_token):
    pubkey, one, two = split(encrypted_token)
    return two
