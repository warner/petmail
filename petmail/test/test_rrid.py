from twisted.trial import unittest
from .. import rrid

def flip_bit(s):
    return s[:-1] + chr(ord(s[-1]) ^ 0x01)

class RRID(unittest.TestCase):
    def test_create(self):
        token, privkey, enctoken = rrid.create_token()
        self.failUnlessEqual(len(token), 32)
        self.failUnlessEqual(len(privkey), 32)
        self.failUnlessEqual(len(enctoken), 3*32)
    def test_crypt(self):
        token, privkey, enctoken1 = rrid.create_token()
        enctoken2 = rrid.rerandomize_token(enctoken1)
        enctoken3 = rrid.rerandomize_token(enctoken2)
        self.failIfEqual(enctoken1, enctoken2)
        self.failIfEqual(enctoken2, enctoken3)
        self.failUnlessEqual(rrid.decrypt(privkey, enctoken1), token)
        self.failUnlessEqual(rrid.decrypt(privkey, enctoken2), token)
        self.failUnlessEqual(rrid.decrypt(privkey, enctoken3), token)
        # note: this is malleable
        corrupt_token = flip_bit(enctoken1)
        self.failIfEqual(rrid.decrypt(privkey, corrupt_token), token)
