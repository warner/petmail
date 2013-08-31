import unittest

from ..netstring import netstring, split_netstrings

class Netstring(unittest.TestCase):
    def test_create(self):
        self.failUnlessEqual(netstring("abc"), "3:abc,")
    def test_split(self):
        a1 = netstring("abc")
        a2 = netstring("def")
        a3 = netstring("")
        a4 = netstring(":,")
        a5 = netstring("ghi")
        self.failUnlessEqual(split_netstrings(a1+a2+a3+a4+a5),
                             ["abc", "def", "", ":,", "ghi"])
    def test_leftover(self):
        a1 = netstring("abc")
        a2 = netstring("def")
        self.failUnlessEqual(split_netstrings(a1+a2+"stuff", True),
                             ["abc", "def", "stuff"])
    def test_no_leftover(self):
        self.failUnlessRaises(ValueError,
                              split_netstrings, "3:abc,extra")
