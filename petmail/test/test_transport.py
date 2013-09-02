import json
from twisted.trial import unittest
from nacl.public import PublicKey, Box
from .common import TwoNodeMixin
from ..mailbox import channel
from ..mailbox.delivery import createMsgA, ReturnTransport
from ..mailbox.server import parseMsgA, parseMsgB

class Transports(TwoNodeMixin, unittest.TestCase):
    def test_create_from_channel(self):
        nA, nB, entA, entB = self.make_nodes()
        c = channel.OutboundChannel(nA.db, entA["id"])
        transports = c.createTransports()
        self.failUnlessEqual(len(transports), 1)
        self.failUnless(isinstance(transports[0], ReturnTransport))

    def test_msgA(self):
        nA, nB, entA, entB = self.make_nodes()
        msgC = "msgC"

        trec = json.loads(entA["their_channel_record_json"])["transports"][0]
        msgA = createMsgA(trec, msgC)

        pubkey1_s, boxed = parseMsgA(msgA)
        tpriv = self.tport2[0]["privkey"]
        b = Box(tpriv, PublicKey(pubkey1_s))
        msgB = b.decrypt(boxed)

        MSTID, msgC2 = parseMsgB(msgB)
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

    def test_send(self):
        nA, nB, entA, entB = self.make_nodes(transport="local")
        #chanAB = json.loads(entA["their_channel_record_json"])
        messages = []
        def message_received(tid, msgC):
            messages.append((tid,msgC))
        nB.client.msgC_received = message_received
        d = nA.client.send_message(entA["id"], {"hi": "world"})
        def _sent(res):
            self.failUnlessEqual(len(messages), 1)
            self.failUnlessEqual(messages[0][0], entB["id"])
        d.addCallback(_sent)
        return d

    def test_send_payload(self):
        nA, nB, entA, entB = self.make_nodes(transport="local")
        payloads = []
        def payload_received(tid, msgC):
            payloads.append((tid,msgC))
        nB.client.payload_received = payload_received
        d = nA.client.send_message(entA["id"], {"hi": "world"})
        def _sent(res):
            self.failUnlessEqual(len(payloads), 1)
            self.failUnlessEqual(payloads[0][0], entB["id"])
            self.failUnlessEqual(payloads[0][1], {"hi": "world"})
        d.addCallback(_sent)
        return d
