import os
from twisted.trial import unittest
from .common import BasedirMixin, NodeRunnerMixin
from ..errors import CommandError

class Invite(BasedirMixin, NodeRunnerMixin, unittest.TestCase):

    def test_unknown_retrieval_type(self):
        basedir1 = os.path.join(self.make_basedir(), "node1")
        self.createNode(basedir1)
        n1 = self.startNode(basedir1)
        mbrec_bogus = {"retrieval": {"type": "bogus"}}
        self.failUnlessRaises(CommandError,
                              n1.agent.command_add_mailbox, mbrec_bogus)
