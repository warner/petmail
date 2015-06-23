import os, json
from twisted.trial import unittest
from nacl.public import PrivateKey
from .common import TwoNodeMixin
from ..errors import CommandError
from ..mailbox.retrieval import HTTPRetriever

def fetchone(db, tablename):
    return db.execute("SELECT * FROM %s" % tablename).fetchone()
def fetchall(db, tablename):
    return db.execute("SELECT * FROM %s" % tablename).fetchall()

class Creation(TwoNodeMixin, unittest.TestCase):
    def test_unknown_retrieval_type(self):
        basedir1 = os.path.join(self.make_basedir(), "node1")
        self.createNode(basedir1)
        n1 = self.startNode(basedir1)
        bogus_retriever = {"type": "bogus"}
        self.failUnlessRaises(CommandError,
                              n1.agent.build_retriever, 1, bogus_retriever)

    def test_http_retriever(self):
        basedir1 = os.path.join(self.make_basedir(), "node1")
        self.createNode(basedir1)
        n1 = self.startNode(basedir1)
        rrec = {"type": "http",
                "baseurl": "/",
                "RT": "",
                "retrieval_pubkey": "",
                "retrieval_symkey": ""}
        rc = n1.agent.build_retriever(1, rrec)
        self.failUnless(isinstance(rc, HTTPRetriever))

class Invite(TwoNodeMixin, unittest.TestCase):

    def test_offer_mailbox(self):
        nA, nB = self.make_nodes(transport="none")
        self.failUnlessEqual(len(nA.agent.get_transports()), 0)
        d = self.add_new_channel_with_invitation(nA, nB, offer_mailbox=True,
                                                 accept_mailbox_offer=True)
        def _then((entA,entB)):
            self.failUnlessEqual(entA["their_verfkey"], entB["my_verfkey"])
            self.failUnlessEqual(entB["their_verfkey"], entA["my_verfkey"])
            st = fetchone(nB.db, "mailbox_server_transports")
            sj = fetchone(nB.db, "mailbox_server_config")
            s = json.loads(sj["mailbox_config_json"])
            r_privkey = PrivateKey(s["retrieval_privkey"].decode("hex"))
            r_pubkey = r_privkey.public_key.encode().encode("hex")
            t_privkey = PrivateKey(s["transport_privkey"].decode("hex"))
            t_pubkey = t_privkey.public_key.encode().encode("hex")

            transports = nA.agent.get_transports()
            self.failUnlessEqual(len(transports), 1)
            self.failUnless(1 in transports)
            t1 = transports[1]["transport"]
            self.failUnlessEqual(t1["generic"]["type"], "http")
            self.failUnlessEqual(t1["generic"]["url"], nB.baseurl+"mailbox")
            self.failUnlessEqual(t1["generic"]["transport_pubkey"], t_pubkey)
            self.failUnlessIn("TT0", t1["sender"])
            # TODO: when RRID crypto is done, check TT0 better

            r = transports[1]["retrieval"]
            self.failUnlessEqual(r["type"], "http")
            self.failUnlessEqual(r["baseurl"], nB.baseurl+"retrieval/")
            self.failUnlessEqual(r["RT"], st["RT"])
            self.failUnlessEqual(r["retrieval_pubkey"], r_pubkey)
            self.failUnlessEqual(r["retrieval_symkey"], st["symkey"])

            retrievers = nA.agent.mailbox_retrievers
            self.failUnlessEqual(len(retrievers), 1)
            self.failUnless(isinstance(list(retrievers)[0], HTTPRetriever))
            return nA.disownServiceParent()
        d.addCallback(_then)
        d.addCallback(lambda _: self.startNode(nA.basedir))
        def _then2(nA2):
            retrievers = nA2.agent.mailbox_retrievers
            self.failUnlessEqual(len(retrievers), 1)
            self.failUnless(isinstance(list(retrievers)[0], HTTPRetriever))
        d.addCallback(_then2)

        return d

    def test_offer_mailbox_rejected(self):
        nA, nB = self.make_nodes(transport="none")
        self.failUnlessEqual(len(nA.agent.get_transports()), 0)
        d = self.add_new_channel_with_invitation(nA, nB, offer_mailbox=True)
        def _then((entA,entB)):
            self.failUnlessEqual(entA["their_verfkey"], entB["my_verfkey"])
            self.failUnlessEqual(entB["their_verfkey"], entA["my_verfkey"])
            transports = nA.agent.get_transports()
            self.failIf(transports)
        d.addCallback(_then)
        return d
