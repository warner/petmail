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

    def test_ascii(self):
        b2a = util.to_ascii
        a2b = util.from_ascii
        for prefix in ("", "prefix-"):
            for length in range(0, 100):
                b1 = "a"*length
                for base in ("base64", "base32", "base16", "hex"):
                    a = b2a(b1, prefix, base)
                    b2 = a2b(a, prefix, base)
                    self.failUnlessEqual(b1, b2)
        self.failUnlessRaises(NotImplementedError, b2a, "a", encoding="none")
        self.failUnlessRaises(NotImplementedError, a2b, "a", encoding="none")

    def test_nonce(self):
        n1 = util.make_nonce()
        self.failUnlessEqual(len(n1), 52)
        n2 = util.make_nonce()
        self.failIfEqual(n1, n2) # not exhaustive

    def test_equal(self):
        self.failUnless(util.equal("a", "a"))
        self.failIf(util.equal("a", "b"))

    def test_x_or_none(self):
        self.failUnlessEqual(util.hex_or_none(None), None)
        self.failUnlessEqual(util.hex_or_none("A"), "41")
        self.failUnlessEqual(util.unhex_or_none(None), None)
        self.failUnlessEqual(util.unhex_or_none("42"), "B")

    def test_remove_prefix(self):
        self.failUnlessEqual(util.remove_prefix("v1:stuff", "v1:"), "stuff")
        x = self.failUnlessRaises(util.BadPrefixError,
                                  util.remove_prefix, "v2:stuff", "v1:")
        self.failUnlessEqual(str(x), "did not see expected 'v1:' prefix")
        x = self.failUnlessRaises(ValueError,
                                  util.remove_prefix, "v2:stuff", "v1:",
                                  ValueError)
        self.failUnlessEqual(str(x), "did not see expected 'v1:' prefix")


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
