from twisted.trial import unittest
from twisted.internet import tcp, protocol
from nacl.signing import SigningKey
from nacl.exceptions import CryptoError

from .. import util, errors

class Utils(unittest.TestCase):
    def test_split_into(self):
        self.failUnlessEqual(util.split_into("ABBCCC", [1,2,3]),
                             ["A","BB","CCC"])
        self.failUnlessEqual(util.split_into("ABBCCC", [2,1], True),
                             ["AB","B","CCC"])
        self.failUnlessRaises(ValueError,
                              util.split_into, "ABBCCC", [2,1], False)
        self.failUnlessRaises(ValueError,
                              util.split_into, "ABBCCC", [2,1]
                              )

class Signatures(unittest.TestCase):
    def test_verify_with_prefix(self):
        sk = SigningKey.generate()
        vk = sk.verify_key
        m = "body"
        prefix = "prefix:"
        sk2 = SigningKey.generate()

        sm1 = sk.sign(prefix+m)
        sm2 = sk.sign("not the prefix"+m)
        sm3 = sk2.sign(prefix+m)

        self.failUnlessEqual(util.verify_with_prefix(vk, sm1, prefix), m)
        self.failUnlessRaises(errors.BadSignatureError,
                              util.verify_with_prefix, vk, sm2, prefix)
        self.failUnlessRaises(CryptoError,
                              util.verify_with_prefix, vk, sm3, prefix)

class AllocatePort(unittest.TestCase):
    def test_allocate(self):
        port = util.allocate_port()
        # and it should be possible to claim this port right away
        p2 = tcp.Port(port, protocol.Factory())
        p2.startListening()
        port2 = p2.getHost().port
        d = p2.stopListening()
        def _stopped(res):
            self.failUnlessEqual(port, port2)
            return res
        d.addBoth(_stopped)
        return d
