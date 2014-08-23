import os
from twisted.trial import unittest
from .common import BasedirMixin, NodeRunnerMixin, CLIinThreadMixin
from .pollmixin import PollMixin

class System(CLIinThreadMixin, BasedirMixin, NodeRunnerMixin, PollMixin,
             unittest.TestCase):

    def cli_1(self, command, *args):
        return self.cliMustSucceed("-d", self.basedir1, command, *args)
    def cli_2(self, command, *args):
        return self.cliMustSucceed("-d", self.basedir2, command, *args)

    def test_message(self):
        # two nodes, using a localdir relay, and --local-mailbox
        self.basedir1 = os.path.join(self.make_basedir(), "node1")
        self.createNode(self.basedir1)
        n1 = self.startNode(self.basedir1)
        self.basedir2 = os.path.join(self.make_basedir(), "node2")
        self.createNode(self.basedir2)
        n2 = self.startNode(self.basedir2)

        d = self.cli_1("invite", "-n", "bob", "code")
        d.addCallback(lambda _: self.cli_2("invite", "-n", "alice", "code"))

        def until_invited():
            a1 = n1.agent.command_list_addressbook()
            if not a1 or not a1[0]["acked"]:
                return False
            self.cid_bob = a1[0]["cid"]
            a2 = n2.agent.command_list_addressbook()
            if not a2 or not a2[0]["acked"]:
                return False
            return True
        d.addCallback(lambda _: self.poll(until_invited))

        d.addCallback(lambda _: self.cli_1("send-basic", str(self.cid_bob),
                                           "hello bob"))

        def until_received():
            m2 = n2.agent.command_fetch_all_messages()
            if not m2:
                return False
            self.bob_messages = m2
            return True
        d.addCallback(lambda _: self.poll(until_received))

        def _check_message(_):
            m = self.bob_messages[0]
            self.failUnlessEqual(m["petname"], u"alice")
            self.failUnlessEqual(m["seqnum"], 1)
            self.failUnlessEqual(m["payload"], {"basic": "hello bob"})
        d.addCallback(_check_message)

        return d
