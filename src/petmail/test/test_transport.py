import json
from twisted.trial import unittest
from nacl.public import PrivateKey, PublicKey, Box
from .common import TwoNodeMixin
from ..mailbox import channel
from ..mailbox.delivery import createMsgA, ReturnTransport, OutboundHTTPTransport
from ..mailbox.server import parseMsgA, parseMsgB

class Transports(TwoNodeMixin, unittest.TestCase):
    def test_create_from_channel(self):
        nA, nB, entA, entB = self.make_connected_nodes()
        c = channel.OutboundChannel(nA.db, entA["id"])
        transports = c.createTransports()
        self.failUnlessEqual(len(transports), 2)
        classes = set([t.__class__ for t in transports])
        self.failUnlessEqual(classes, set([ReturnTransport,
                                           OutboundHTTPTransport]))
        self.failUnless(isinstance(transports[0], ReturnTransport))

    def test_msgA(self):
        nA, nB, entA, entB = self.make_connected_nodes()
        msgC = "msgC"

        trec = json.loads(entA["their_channel_record_json"])["transports"][0]
        msgA = createMsgA(trec, msgC)

        pubkey1_s, boxed = parseMsgA(msgA)
        tpriv_hex = self.tports2["local"]["retrieval"]["privkey"]
        tpriv = PrivateKey(tpriv_hex.decode("hex"))
        b = Box(tpriv, PublicKey(pubkey1_s))
        msgB = b.decrypt(boxed)

        MSTT, msgC2 = parseMsgB(msgB)
        self.failUnlessEqual(msgC, msgC2)

        # TODO: use a stable fake TT private key instead of randomly
        # generating one (and throwing it away) in Agent.build_transports(),
        # so we can decrypt it here and make sure it matches

    def test_local(self):
        nA, nB, entA, entB = self.make_connected_nodes(transport="local")
        chanAB = json.loads(entA["their_channel_record_json"])
        transportsAB = chanAB["transports"]
        self.failUnlessEqual(len(transportsAB), 1)
        self.failUnlessEqual(transportsAB[0]["type"], "http")

        local_tids = [row["id"]
                      for row in (nA.db.execute("SELECT * FROM"
                                                " mailbox_server_transports")
                                  .fetchall())
                      if row["symkey"] is None]
        self.failUnlessEqual(len(local_tids), 1)
        tid_1 = nA.agent.mailbox_server.get_local_transport()
        tid_2 = nA.agent.mailbox_server.get_local_transport()
        self.failUnlessEqual(tid_1, tid_2)

    def test_send_local(self):
        nA, nB, entA, entB = self.make_connected_nodes(transport="local")
        #chanAB = json.loads(entA["their_channel_record_json"])
        messages = []
        def message_received(mbid, msgC):
            messages.append((mbid,msgC))
        nB.agent.msgC_received = message_received
        d = nA.agent.send_message(entA["id"], {"hi": "world"})
        def _sent(res):
            self.failUnlessEqual(len(messages), 1)
            self.failUnlessEqual(messages[0][0], "local")
        d.addCallback(_sent)
        return d



    def test_send_local_payload(self):
        nA, nB, entA, entB = self.make_connected_nodes(transport="local")
        P1 = {"hi": "world"}
        P2 = {"hi": "2"}

        payloads = []
        def payload_received(tid, seqnum, payload_json):
            payloads.append((tid,seqnum,payload_json))
        nB.agent.payload_received = payload_received
        d = nA.agent.send_message(entA["id"], P1)
        def _sent(res):
            self.failUnlessEqual(len(payloads), 1)
            tid,seqnum,payload_json = payloads[0]
            self.failUnlessEqual(tid, entB["id"])
            self.failUnlessEqual(seqnum, 1)
            self.failUnlessEqual(json.loads(payload_json), P1)
        d.addCallback(_sent)

        # now bounce node B and confirm that it can grab the server port when
        # it comes back up
        d.addCallback(lambda _: nB.disownServiceParent())
        d.addCallback(lambda _: self.startNode(nB.basedir))
        def _new_nodeB(new_nB):
            new_nB.agent.payload_received = payload_received
        d.addCallback(_new_nodeB)
        d.addCallback(lambda _: nA.agent.send_message(entA["id"], P2))
        def _sent2(res):
            self.failUnlessEqual(len(payloads), 2)
            tid,seqnum,payload_json = payloads[1]
            self.failUnlessEqual(tid, entB["id"])
            self.failUnlessEqual(seqnum, 2)
            self.failUnlessEqual(json.loads(payload_json), P2)
        d.addCallback(_sent2)

        return d

    def test_send_local_payload_stored(self):
        nA, nB, entA, entB = self.make_connected_nodes(transport="local")
        P1 = {"hi": "world"}

        d = nA.agent.send_message(entA["id"], P1)
        def _sent(res):
            c = nB.db.execute("SELECT * FROM inbound_messages")
            rows = c.fetchall()
            self.failUnlessEqual(len(rows), 1)
            self.failUnlessEqual(rows[0]["id"], 1) # global msgid
            self.failUnlessEqual(rows[0]["cid"], entB["id"])
            self.failUnlessEqual(rows[0]["seqnum"], 1)
            self.failUnlessEqual(json.loads(rows[0]["payload_json"]), P1)
        d.addCallback(_sent)
        d.addCallback(lambda _: nB.agent.command_fetch_all_messages())
        def _fetched(messages):
            self.failUnlessEqual(len(messages), 1)
            self.failUnlessEqual(messages[0]["id"], 1)
            self.failUnlessEqual(messages[0]["cid"], entB["id"])
            self.failUnlessEqual(messages[0]["seqnum"], 1)
            self.failUnlessEqual(messages[0]["payload"], P1)
        d.addCallback(_fetched)

        return d
