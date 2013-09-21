import json, copy
from twisted.trial import unittest
from .common import TwoNodeMixin
from .. import rrid
from ..eventual import flushEventualQueue
from ..mailbox.delivery import createMsgA

class Transports(TwoNodeMixin, unittest.TestCase):
    def test_unknown_TID(self):
        nA, nB, entA, entB = self.make_connected_nodes(transport="local")
        msgC = "msgC"
        trec = json.loads(entA["their_channel_record_json"])["transports"][0]
        bad_trec = copy.deepcopy(trec)
        TID_privkey, TID_pubkey = rrid.create_keypair()
        TID_tokenid, TID_token0 = rrid.create_token(TID_pubkey)
        bad_STID = rrid.randomize(TID_token0)
        bad_trec["STID"] = bad_STID.encode("hex")
        msgA = createMsgA(bad_trec, msgC)

        unknowns = []
        server = nB.client.mailbox_server
        server.signal_unrecognized_TID = unknowns.append
        server.handle_msgA(msgA)
        d = flushEventualQueue()
        def _then(res):
            self.failUnlessEqual(len(unknowns), 1)
            c = nB.db.execute("SELECT * FROM mailbox_server_messages")
            messages = c.fetchall()
            self.failUnlessEqual(len(messages), 0)
        d.addCallback(_then)
        return d

    def test_local_TID(self):
        nA, nB, entA, entB = self.make_connected_nodes(transport="local")
        msgC = "msgC"
        trec = json.loads(entA["their_channel_record_json"])["transports"][0]
        msgA = createMsgA(trec, msgC)
        server = nB.client.mailbox_server
        local_messages = []
        server.local_transport_handler = local_messages.append
        server.handle_msgA(msgA)
        d = flushEventualQueue()
        def _then(res):
            c = nB.db.execute("SELECT * FROM mailbox_server_messages")
            messages = c.fetchall()
            self.failUnlessEqual(len(messages), 0)
            self.failUnlessEqual(len(local_messages), 1)
            self.failUnlessEqual(local_messages[0], msgC)
        d.addCallback(_then)
        return d

    def test_nonlocal_TID(self):
        nA, nB, entA, entB = self.make_connected_nodes(transport="local")
        msgC = "msgC"
        trec = json.loads(entA["their_channel_record_json"])["transports"][0]
        msgA = createMsgA(trec, msgC)
        server = nB.client.mailbox_server

        row = nB.db.execute("SELECT * FROM mailbox_server_config").fetchone()
        sc = json.loads(row["private_descriptor_json"])
        TID_pubkey = sc["TID_public_key"].decode("hex")
        TID1_tokenid, TID1_token0 = rrid.create_token(TID_pubkey)
        STID1 = rrid.randomize(TID1_token0)

        symkey = "\x00"*32
        tid = server.add_TID(TID1_tokenid, symkey)

        transport_pubkey = server.get_sender_descriptor()["transport_pubkey"]
        trec = {"STID": STID1.encode("hex"),
                "transport_pubkey": transport_pubkey}
        msgA = createMsgA(trec, "msgC")

        local_messages = []
        server.local_transport_handler = local_messages.append
        server.handle_msgA(msgA)

        d = flushEventualQueue()
        def _then(res):
            self.failUnlessEqual(len(local_messages), 0)
            c = nB.db.execute("SELECT * FROM mailbox_server_messages")
            messages = c.fetchall()
            self.failUnlessEqual(len(messages), 1)
            self.failUnlessEqual(messages[0]["tid"], tid)
            self.failUnlessEqual(messages[0]["length"], len(msgC))
            self.failUnlessEqual(messages[0]["msgC"].decode("hex"), msgC)
        d.addCallback(_then)
        return d

