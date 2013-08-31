import json
from twisted.trial import unittest
from nacl.public import PrivateKey, PublicKey, Box
from .common import TwoNodeMixin
from ..mailbox import channel, transport
from ..mailbox.delivery.http import OutboundHTTPTransport

class Transports(TwoNodeMixin, unittest.TestCase):
    def test_create_from_channel(self):
        nA, nB, entA, entB = self.make_nodes()
        c = channel.OutboundChannel(nA.db, entA["id"])
        transports = c.createTransports()
        self.failUnlessEqual(len(transports), 1)
        self.failUnless(isinstance(transports[0], OutboundHTTPTransport))

        #ic = channel.InboundChannel(nB.db, entB["id"], None)

    def test_msgA(self):
        nA, nB, entA, entB = self.make_nodes()
        msgC = "msgC"

        trec = json.loads(entA["their_channel_record_json"])["transports"][0]
        msgA = transport.createMsgA(trec, msgC)

        pubkey1_s, boxed = transport.parseMsgA(msgA)
        # the corresponding pubkey is currently hardcoded into
        # Client.build_transports
        tpriv="fbf86cb264701a5a6ffa3a031475a1d20a80415202ce8e385cef1776c602a242"
        b = Box(PrivateKey(tpriv.decode("hex")), PublicKey(pubkey1_s))
        msgB = b.decrypt(boxed)

        MSTID, msgC2 = transport.parseMsgB(msgB)
        self.failUnlessEqual(msgC, msgC2)

        # TODO: use a stable fake TID private key instead of randomly
        # generating one (and throwing it away) in Client.build_transports(),
        # so we can decrypt it here and make sure it matches

