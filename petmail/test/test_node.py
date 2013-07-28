from twisted.trial import unittest

class Basic(unittest.TestCase):
    def test_one(self):
        self.assert_(True, "yay!")

