from twisted.trial import unittest
from .common import TwoNodeMixin
from ..mailbox import channel
from ..mailbox.delivery.http import OutboundHTTPTransport

class Outbound(TwoNodeMixin, unittest.TestCase):
    def test_create_msgC(self):
        nA, nB, cidAB, cidBA = self.make_nodes()

        c = channel.OutboundChannel(nA.db, cidAB)
        payload = {"hi": "there"}
        msgC = c.createMsgC(payload)
        self.failUnless(msgC.startswith("c0:"))

        transports = c.createTransports()
        self.failUnlessEqual(len(transports), 1)
        self.failUnless(isinstance(transports[0], OutboundHTTPTransport))
