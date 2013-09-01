from twisted.trial import unittest
from hashlib import sha256
from nacl.public import PrivateKey
from .common import TwoNodeMixin
from ..mailbox import channel

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
        keyid, pubkey2_s, msgE = channel.decrypt_msgD(msgD, keys)

        their_verfkey = entB["their_verfkey"].decode("hex")
        seqnum, payload2 = channel.check_msgE(msgE, pubkey2_s,
                                              their_verfkey,
                                              entB["highest_inbound_seqnum"])
        self.failUnlessEqual(payload, payload2)

    def test_channel_dispatch(self):
        nA, nB, entA, entB = self.make_nodes()
        entA2, entB2 = self.add_new_channel(nA, nB)
        entA3, entB3 = self.add_new_channel(nA, nB)

        c = channel.OutboundChannel(nA.db, entA2["id"])
        payload = {"hi": "there"}
        msgC = c.createMsgC(payload)
        self.failUnless(msgC.startswith("c0:"))

        CIDToken, CIDBox, msgD = channel.parse_msgC(msgC)

        # TODO: test CIDToken

        # test CIDBox
        cid,which_key = channel.find_channel_from_CIDBox(nB.db, CIDBox)
        self.failUnlessEqual(cid, entB2["id"])
        # the CIDBox claims to tell us which key to use. We won't actually
        # use it unless it matches the cid that was able to open the CIDBox
        privkey_s = entB2["my_new_channel_privkey"].decode("hex")
        pubkey = PrivateKey(privkey_s).public_key.encode()
        self.failUnlessEqual(which_key, pubkey)

        # but other clients should not recognize this CIDBox
        cid,which_key = channel.find_channel_from_CIDBox(nA.db, CIDBox)
        self.failUnlessEqual(cid, None)
        self.failUnlessEqual(which_key, None)

        # TODO: test trial-descryption of msgC
