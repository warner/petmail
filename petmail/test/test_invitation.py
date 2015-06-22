import os, json, time
from twisted.trial import unittest
from twisted.internet import defer
from wormhole.twisted.transcribe import SymmetricWormhole
from .common import BasedirMixin, NodeRunnerMixin, TwoNodeMixin, fake_transport
from ..errors import CommandError

class Invite(BasedirMixin, NodeRunnerMixin, unittest.TestCase):
    def test_one(self):
        start = time.time()

        basedir1 = os.path.join(self.make_basedir(), "node1")
        self.createNode(basedir1)
        n1 = self.startNode(basedir1)

        cid = 456
        sp = b"alice signed payload"
        i = n1.agent.im.create_invitation(cid, None, sp)
        d1 = i._debug_when_got_code = defer.Deferred()
        d2 = i.activate()
        # this requires a server roundtrip to allocate the channel, so the
        # code won't be known yet
        rows = list(n1.db.execute("SELECT * from invitations").fetchall())
        self.failUnlessEqual(len(rows), 1)
        r = rows[0]
        self.failUnlessEqual(r["channel_id"], 456)
        self.failUnlessEqual(r["code"], None)
        self.failUnlessEqual(r["wormhole"], None)
        self.failUnlessEqual(r["payload_for_them"], sp.encode("hex"))

        def _got_code(code):
            self.code = code
            rows = list(n1.db.execute("SELECT * from invitations").fetchall())
            self.failUnlessEqual(len(rows), 1)
            r = rows[0]
            self.failUnlessEqual(r["channel_id"], 456)
            self.failUnlessEqual(r["code"], code)
            wormhole_data = r["wormhole"]
            json.loads(wormhole_data)

            w = SymmetricWormhole(i.appid, i.relay)
            w.set_code(code)
            d3 = w.get_data(b"bob signed payload")
            return d3 # wait for bob's side to finish
        d1.addCallback(_got_code)
        def _bob_done(alice_data):
            self.failUnlessEqual(alice_data, sp)
            return d2 # now wait for alice's side to finish
        d1.addCallback(_bob_done)
        def _alice_done(code_and_bob_data):
            code, bob_data = code_and_bob_data
            self.failUnlessEqual(code, self.code)
            self.failUnlessEqual(bob_data, b"bob signed payload")
        d1.addCallback(_alice_done)
        return d1

    def test_duplicate_code(self):
        basedir1 = os.path.join(self.make_basedir(), "node1")
        self.createNode(basedir1)
        n1 = self.startNode(basedir1)
        self.disable_polling(n1)
        code = "code"
        tports = {"local": fake_transport()}
        n1.agent.command_invite(u"petname-from-1", code,
                                override_transports=tports)
        self.failUnlessRaises(CommandError,
                              n1.agent.command_invite, u"new-petname", code)

    def test_generate(self):
        basedir1 = os.path.join(self.make_basedir(), "node1")
        self.createNode(basedir1)
        n1 = self.startNode(basedir1)
        self.disable_polling(n1)
        tports = {"local": fake_transport()}
        res = n1.agent.command_invite(u"petname-from-1",
                                      code=None, generate=True,
                                      override_transports=tports)
        self.failUnless("code" in res)
        self.failUnless(len(res["code"]) > 10)

    def test_change_petname(self):
        basedir1 = os.path.join(self.make_basedir(), "node1")
        self.createNode(basedir1)
        n1 = self.startNode(basedir1)
        self.disable_polling(n1)
        tports = {"local": fake_transport()}
        res = n1.agent.command_invite(u"old-petname",
                                      code=None, generate=True,
                                      override_transports=tports)
        self.failUnless("code" in res)
        self.failUnless(len(res["code"]) > 10)
        entries = n1.db.execute("SELECT * FROM addressbook").fetchall()
        self.failUnlessEqual(len(entries), 1)
        petname = entries[0]["petname"]
        self.failUnlessEqual(petname, u"old-petname")

    def test_change_accept_mailbox(self):
        basedir1 = os.path.join(self.make_basedir(), "node1")
        self.createNode(basedir1)
        n1 = self.startNode(basedir1)
        self.disable_polling(n1)
        tports = {"local": fake_transport()}
        res = n1.agent.command_invite(u"petname",
                                      code=None, generate=True,
                                      override_transports=tports)
        self.failUnless("code" in res)
        self.failUnless(len(res["code"]) > 10)
        entries = n1.db.execute("SELECT * FROM addressbook").fetchall()
        self.failUnlessEqual(len(entries), 1)
        old_accept = entries[0]["accept_mailbox_offer"]
        self.failUnlessEqual(old_accept, False)

        n1.agent.command_control_accept_mailbox_offer(entries[0]["id"], True)
        new_accept = n1.db.execute("SELECT * FROM addressbook").fetchone()["accept_mailbox_offer"]
        self.failUnlessEqual(new_accept, True)

    def test_bad_args(self):
        basedir1 = os.path.join(self.make_basedir(), "node1")
        self.createNode(basedir1)
        n1 = self.startNode(basedir1)
        self.disable_polling(n1)
        e = self.failUnlessRaises(CommandError,
                                  n1.agent.command_invite,
                                  u"new-petname", "code",
                                  generate=True)
        self.failUnlessEqual(e.msg, "please use --generate or --code, not both")


class Two(TwoNodeMixin, unittest.TestCase):
    def test_two(self):
        nA, nB = self.make_nodes()
        d = self.add_new_channel_with_invitation(nA, nB)
        def _done((entA,entB)):
            self.failUnlessEqual(nA.agent.command_list_addressbook()[0]["cid"],
                                 entA["id"])
            self.failUnlessEqual(nB.agent.command_list_addressbook()[0]["cid"],
                                 entB["id"])
        d.addCallback(_done)
        return d
