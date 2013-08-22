
# "rrid": re-randomized IDs, using ElGamal-encrypted tokens. These encrypted
# tokens can be given to someone else, then re-encrypted (multiple times)
# without letting them know the actual token value. The holder of the private
# key can decrypt these to recover the original token. We only use this to
# compare the decrypted token against the original.

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

# the final recipient remembers privkey+token
# some senders are given pubkey+token (when each sender gets a unique token)
# other senders get pubkey+enctoken (to prevent senders from comparing tokens)

import os

def split(s):
    return [s[i:i+32] for i in range(0, len(s), 32)]

def create():
    # actual crypto is stubbed out for now
    IDENTITY = "\x00"*32
    # encrypting with r=0 gives (IDENTITY,m), which is suitable for the first
    # token (which is not encrypted), and can also be fed into rerandomize().
    privkey = "\x11"*32
    pubkey = "\x22"*32
    token_id = os.urandom(32)
    private_token = privkey + token_id
    nullencrypted_token = pubkey + IDENTITY + token_id
    return private_token, nullencrypted_token

def randomize(token):
    pubkey, C1, C2 = split(token)
    return pubkey+os.urandom(32)+C2

def compare(private_token, token):
    privkey, token_id = split(private_token)
    pubkey, C1, C2 = split(token)
    if token_id == C2:
        return True
    return False
