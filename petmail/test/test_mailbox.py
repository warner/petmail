import os
from twisted.trial import unittest
from .common import BasedirMixin, NodeRunnerMixin
from ..errors import CommandError

class Invite(BasedirMixin, NodeRunnerMixin, unittest.TestCase):

    def test_unknown_retrieval_type(self):
        basedir1 = os.path.join(self.make_basedir(), "node1")
        self.createNode(basedir1)
        n1 = self.startNode(basedir1)
        pub_bogus = priv_bogus = {"type": "bogus"}
        self.failUnlessRaises(CommandError,
                              n1.client.command_add_mailbox,
                              pub_bogus, priv_bogus)
