import json
from twisted.trial import unittest
from nacl.public import PublicKey, Box
from .common import TwoNodeMixin
from ..mailbox import channel, transport
from ..mailbox.delivery import createMsgA, ReturnTransport

class Transports(TwoNodeMixin, unittest.TestCase):
    def test_create_from_channel(self):
        nA, nB, entA, entB = self.make_nodes()
        c = channel.OutboundChannel(nA.db, entA["id"])
        transports = c.createTransports()
        self.failUnlessEqual(len(transports), 1)
        self.failUnless(isinstance(transports[0], ReturnTransport))

        #ic = channel.InboundChannel(nB.db, entB["id"], None)

    def test_msgA(self):
        nA, nB, entA, entB = self.make_nodes()
        msgC = "msgC"

        trec = json.loads(entA["their_channel_record_json"])["transports"][0]
        msgA = createMsgA(trec, msgC)

        pubkey1_s, boxed = transport.parseMsgA(msgA)
        tpriv = self.tport2[0]["privkey"]
        b = Box(tpriv, PublicKey(pubkey1_s))
        msgB = b.decrypt(boxed)

        MSTID, msgC2 = transport.parseMsgB(msgB)
        self.failUnlessEqual(msgC, msgC2)

        # TODO: use a stable fake TID private key instead of randomly
        # generating one (and throwing it away) in Client.build_transports(),
        # so we can decrypt it here and make sure it matches

    def test_local(self):
        nA, nB, entA, entB = self.make_nodes(transport="local")
        chanAB = json.loads(entA["their_channel_record_json"])
        transportsAB = chanAB["transports"]
        self.failUnlessEqual(len(transportsAB), 1)
        self.failUnlessEqual(transportsAB[0]["type"], "http")
