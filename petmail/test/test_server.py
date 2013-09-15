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
        d.addCallback(_then)
        return d
    
