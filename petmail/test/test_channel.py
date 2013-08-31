from twisted.trial import unittest
from hashlib import sha256
from .common import TwoNodeMixin
from ..mailbox import channel
from ..mailbox.delivery.http import OutboundHTTPTransport

class msgC(TwoNodeMixin, unittest.TestCase):
    def test_create_and_parse(self):
        nA, nB, entA, entB = self.make_nodes()

        cidAB = entA["id"]
        c = channel.OutboundChannel(nA.db, cidAB)
        payload = {"hi": "there"}
        msgC = c.createMsgC(payload)
        self.failUnless(msgC.startswith("c0:"))

        CIDToken, CIDBox, msgD = channel.parse_msgC(msgC)

        CIDKey = entB["my_CID_key"].decode("hex")
        seqnum, HmsgD, channel_pubkey = channel.decrypt_CIDBox(CIDKey, CIDBox)
        self.failUnlessEqual(HmsgD, sha256(msgD).digest())

        keys = [(entB["my_new_channel_privkey"], "keyid")]
        msgE, keyid, pubkey2_s = channel.decrypt_msgD(msgD, keys)

        their_verfkey = entB["their_verfkey"].decode("hex")
        seqnum, payload2 = channel.check_msgE(msgE, pubkey2_s,
                                              their_verfkey,
                                              entB["highest_inbound_seqnum"])
        self.failUnlessEqual(payload, payload2)

class Transports(TwoNodeMixin, unittest.TestCase):
    def test_create(self):
        nA, nB, entA, entB = self.make_nodes()
        c = channel.OutboundChannel(nA.db, entA["id"])
        transports = c.createTransports()
        self.failUnlessEqual(len(transports), 1)
        self.failUnless(isinstance(transports[0], OutboundHTTPTransport))

        #ic = channel.InboundChannel(nB.db, entB["id"], None)

