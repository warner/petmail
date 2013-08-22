from twisted.trial import unittest
from .. import rrid

def flip_bit(s):
    return s[:-1] + chr(ord(s[-1]) ^ 0x01)

class RRID(unittest.TestCase):
    def test_create(self):
        private_token, nullencrypted_token = rrid.create()
        self.failUnlessEqual(type(private_token), type(b""))
        self.failUnlessEqual(len(private_token), 2*32)
        self.failUnlessEqual(type(nullencrypted_token), type(b""))
        self.failUnlessEqual(len(nullencrypted_token), 3*32)

    def test_crypt(self):
        private_token, token0 = rrid.create()
        token1 = rrid.randomize(token0)
        token2 = rrid.randomize(token1)
        self.failUnlessEqual(len(set([private_token, token1, token2])), 3)
        self.failUnless(rrid.compare(private_token, token0))
        self.failUnless(rrid.compare(private_token, token1))
        self.failUnless(rrid.compare(private_token, token2))
        # note: this is malleable
        corrupt_token = flip_bit(token1)
        self.failIf(rrid.compare(private_token, corrupt_token))
        other_private_token, other_token0 = rrid.create()
        self.failIf(rrid.compare(other_private_token, token1))
