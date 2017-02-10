import json
from twisted.trial import unittest
from hashlib import sha256
from nacl.public import PrivateKey, PublicKey, Box
from .common import TwoNodeMixin
from ..mailbox import channel
from ..mailbox.server import parseMsgA, parseMsgB

class msgC(TwoNodeMixin, unittest.TestCase):
    def test_create_and_parse(self):
        nA, nB, entA, entB = self.make_connected_nodes()

        cidAB = entA["id"]
        c = channel.OutboundChannel(nA.db, cidAB)
        payload = {"hi": "there"}
        msgC = c.createMsgC(payload)
        self.failUnless(msgC.startswith("c0:"))

        CIDToken, CIDBox, msgD = channel.parse_msgC(msgC)

        CIDKey = entB["my_CID_key"].decode("hex")
        seqnum, HmsgD, channel_pubkey = channel.decrypt_CIDBox(CIDKey, CIDBox)
        self.failUnlessEqual(HmsgD, sha256(msgD).digest())

        Bkey = PrivateKey(entB["my_new_channel_privkey"].decode("hex"))
        keylist = [(Bkey, "keyid")]
        keyid, pubkey2_s, msgE = channel.decrypt_msgD(msgD, keylist)

        their_verfkey = entB["their_verfkey"].decode("hex")
        seqnum, payload2_s = channel.check_msgE(msgE, pubkey2_s,
                                                their_verfkey,
                                                entB["highest_inbound_seqnum"])
        self.failUnlessEqual(payload, json.loads(payload2_s))

    def get_inbound_seqnum(self, db, cid):
        c = db.execute("SELECT highest_inbound_seqnum FROM addressbook"
                       " WHERE id=?", (cid,))
        return c.fetchone()[0]

    def get_outbound_seqnum(self, db, cid):
        c = db.execute("SELECT next_outbound_seqnum FROM addressbook"
                       " WHERE id=?", (cid,))
        return c.fetchone()[0]

    def test_channel_dispatch(self):
        nA, nB, entA, entB = self.make_connected_nodes()
        entA2, entB2 = self.add_new_channel(nA, nB)
        entA3, entB3 = self.add_new_channel(nA, nB)
        self.failUnlessEqual(self.get_outbound_seqnum(nA.db, entA2["id"]), 1)
        self.failUnlessEqual(self.get_inbound_seqnum(nB.db, entB2["id"]), 0)

        chan = channel.OutboundChannel(nA.db, entA2["id"])
        payload = {"hi": "there"}
        msgC = chan.createMsgC(payload)
        self.failUnless(msgC.startswith("c0:"))

        self.failUnlessEqual(self.get_outbound_seqnum(nA.db, entA2["id"]), 2)
        self.failUnlessEqual(self.get_inbound_seqnum(nB.db, entB2["id"]), 0)

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

        self.failUnlessEqual(self.get_outbound_seqnum(nA.db, entA2["id"]), 2)
        self.failUnlessEqual(self.get_inbound_seqnum(nB.db, entB2["id"]), 0)

        # but other agents should not recognize this CIDBox
        cid,which_key = channel.find_channel_from_CIDBox(nA.db, CIDBox)
        self.failUnlessEqual(cid, None)
        self.failUnlessEqual(which_key, None)

        self.failUnlessEqual(self.get_outbound_seqnum(nA.db, entA2["id"]), 2)
        self.failUnlessEqual(self.get_inbound_seqnum(nB.db, entB2["id"]), 0)

        # this exercises the full processing path, which will increment both
        # outbound and inbound seqnums
        cid2, seqnum, payload2_s = channel.process_msgC(nB.db, msgC)

        self.failUnlessEqual(cid2, entB2["id"])
        self.failUnlessEqual(seqnum, 1)
        self.failUnlessEqual(json.loads(payload2_s), payload)

        self.failUnlessEqual(self.get_outbound_seqnum(nA.db, entA2["id"]), 2)
        self.failUnlessEqual(self.get_inbound_seqnum(nB.db, entB2["id"]), 1)

class Send(TwoNodeMixin, unittest.TestCase):
    def test_send(self):
        nA, nB, entA, entB = self.make_connected_nodes()
        d = nA.agent.send_message(entA["id"], {"hi": "world"})
        def _sent(res):
            msgA = res[0][1]
            self.failUnless(msgA.startswith("a0:"))
            pubkey1_s, boxed = parseMsgA(msgA)
            tpriv_hex = self.tports2["local"]["retrieval"]["privkey"]
            tpriv = PrivateKey(tpriv_hex.decode("hex"))
            b = Box(tpriv, PublicKey(pubkey1_s))
            msgB = b.decrypt(boxed)
            MSTT, msgC = parseMsgB(msgB)

        d.addCallback(_sent)
        return d
