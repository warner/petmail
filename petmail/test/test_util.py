from twisted.trial import unittest

from .. import util

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
