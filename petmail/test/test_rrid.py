from twisted.trial import unittest
from .. import rrid
from .common import flip_bit

class RRID(unittest.TestCase):
    def test_create(self):
        binary = type(b"")
        privkey, pubkey = rrid.create_keypair()
        tokenid, token0 = rrid.create_token(pubkey)
        self.failUnlessEqual((type(privkey), type(pubkey)), (binary, binary))
        self.failUnlessEqual((type(tokenid), type(token0)), (binary, binary))
        self.failUnlessEqual(len(privkey), 32)
        self.failUnlessEqual(len(pubkey), 32)
        self.failUnlessEqual(len(tokenid), 32)
        self.failUnlessEqual(len(token0), 3*32)

    def failUnlessDistinct(self, *things):
        self.failUnlessEqual(len(set(things)), len(things))

    def test_crypt(self):
        privkey, pubkey = rrid.create_keypair()
        tokenid, token0 = rrid.create_token(pubkey)
        token1 = rrid.randomize(token0)
        token2 = rrid.randomize(token1)
        self.failUnlessDistinct(token0, token1, token2)

        self.failUnlessEqual(rrid.decrypt(privkey, token0), tokenid)
        self.failUnlessEqual(rrid.decrypt(privkey, token1), tokenid)
        self.failUnlessEqual(rrid.decrypt(privkey, token2), tokenid)

        # tokens are malleable, we must tolerate that
        corrupt_token = flip_bit(token1)
        self.failIfEqual(rrid.decrypt(privkey, corrupt_token), tokenid)

        other_privkey, other_pubkey = rrid.create_keypair()
        other_tokenid, other_token0 = rrid.create_token(other_pubkey)
        other_token1 = rrid.randomize(other_token0)
        # disabled until rrid.py has real crypto
        #self.failIfEqual(rrid.decrypt(other_privkey, token1), tokenid)
        self.failIfEqual(rrid.decrypt(other_privkey, token1), other_tokenid)
        self.failIfEqual(rrid.decrypt(privkey, other_token1), tokenid)
        #self.failIfEqual(rrid.decrypt(privkey, other_token1), other_tokenid)
