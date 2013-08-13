import os, collections
from twisted.trial import unittest
from .common import BasedirMixin, NodeRunnerMixin
from ..errors import CommandError

MROW = collections.namedtuple("Row", ["my", "theirs", "next"])
AddressbookRow = collections.namedtuple("AddressbookEntry",
                                        ["petname", "their_verfkey",
                                         "their_tport", "acked"])

class Invite(BasedirMixin, NodeRunnerMixin, unittest.TestCase):

    def test_unknown_retrieval_type(self):
        basedir1 = os.path.join(self.make_basedir(), "node1")
        self.createNode(basedir1)
        n1 = self.startNode(basedir1)
        self.failUnlessRaises(CommandError,
                              n1.client.command_add_mailbox, "bogus:stuff")
