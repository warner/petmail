import os, json
from twisted.trial import unittest
from twisted.internet import defer
from wormhole.twisted.transcribe import Wormhole, WrongPasswordError
from .. import invitation
from .common import BasedirMixin, NodeRunnerMixin, TwoNodeMixin, fake_transport
from ..errors import CommandError

class Invite(BasedirMixin, NodeRunnerMixin, unittest.TestCase):
    # low-level test of the Invitation class
    def test_one(self):
        basedir1 = os.path.join(self.make_basedir(), "node1")
        self.createNode(basedir1)
        n1 = self.startNode(basedir1)

        sp = b"alice signed payload"
        maybe_code = None
        cid = n1.db.insert(
            "INSERT INTO addressbook"
            " (petname,"
            "  invitation_state, when_invited, invitation_code,"
            "  wormhole_payload)"
            " VALUES (?, ?,?,?, ?)",
            ("bob",
             invitation.INVITE_WAITING_FOR_CODE, 0, maybe_code,
             sp.encode("hex")))
        n1.db.commit()

        i = n1.agent.im.create_invitation(cid)
        d1 = i._debug_when_got_code = defer.Deferred()
        d2 = i.activate()
        # this requires a server roundtrip to allocate the channel, so the
        # code won't be known yet
        rows = list(n1.db.execute("SELECT * from addressbook").fetchall())
        self.failUnlessEqual(len(rows), 1)
        r = rows[0]
        self.failUnlessEqual(r["id"], cid)
        self.failUnlessEqual(r["invitation_code"], None)
        self.failUnlessEqual(r["wormhole"], None)
        self.failUnlessEqual(r["wormhole_payload"], sp.encode("hex"))

        def _got_code(code):
            self.code = code
            rows = list(n1.db.execute("SELECT * from addressbook").fetchall())
            self.failUnlessEqual(len(rows), 1)
            r = rows[0]
            self.failUnlessEqual(r["invitation_code"], code)
            wormhole_data = r["wormhole"]
            json.loads(wormhole_data)
            self.failUnlessEqual(r["wormhole_payload"], sp.encode("hex"))

            w = Wormhole(i.appid, i.relay)
            w.set_code(code)
            d3 = w.get_data(b"bob signed payload")
            return d3 # wait for bob's side to finish
        d1.addCallback(_got_code)
        def _bob_done(alice_data):
            self.failUnlessEqual(alice_data, sp)
            return d2 # now wait for alice's side to finish
        d1.addCallback(_bob_done)
        def _alice_done(bob_data):
            self.failUnlessEqual(bob_data, b"bob signed payload")
        d1.addCallback(_alice_done)
        return d1

    def test_duplicate_code(self):
        basedir1 = os.path.join(self.make_basedir(), "node1")
        self.createNode(basedir1)
        n1 = self.startNode(basedir1)
        code = "123-code"
        tports = {"local": fake_transport()}
        n1.agent.command_invite(u"petname-from-1", code,
                                override_transports=tports)
        self.failUnlessRaises(CommandError,
                              n1.agent.command_invite, u"new-petname", code)


class Two(TwoNodeMixin, unittest.TestCase):
    def test_two(self):
        nA, nB = self.make_nodes()
        d = self.add_new_channel_with_invitation(nA, nB)
        def _done((entA,entB)):
            self.failUnlessEqual(entA["their_verfkey"], entB["my_verfkey"])
            self.failUnlessEqual(entB["their_verfkey"], entA["my_verfkey"])
        d.addCallback(_done)
        return d

    def test_external_code(self):
        nA, nB = self.make_nodes()
        code = "123-code"

        d1 = defer.Deferred()
        nA.agent.command_invite(u"petname-from-A", code,
                                override_transports=self.tports1,
                                _debug_when_done=d1)
        d2 = defer.Deferred()
        nB.agent.command_invite(u"petname-from-B", code,
                                override_transports=self.tports2,
                                _debug_when_done=d2)
        d1.addCallback(lambda _: d2)
        def _done(res):
            entA = nA.agent.command_list_addressbook()[0]
            entB = nB.agent.command_list_addressbook()[0]
            self.failUnlessEqual(entA["their_verfkey"], entB["my_verfkey"])
            self.failUnlessEqual(entB["their_verfkey"], entA["my_verfkey"])
            rows = list(nA.db.execute("SELECT * from addressbook").fetchall())
            self.failUnlessEqual(len(rows), 1)
            r = rows[0]
            self.failUnlessEqual(r["id"], entA["cid"])
            self.failUnlessEqual(r["invitation_code"], code)
            self.failUnlessEqual(r["wormhole"], None)
            self.failUnlessEqual(r["wormhole_payload"], None)
        d1.addCallback(_done)
        return d1

    def test_wrong_password(self):
        nA, nB = self.make_nodes()
        code = "123-code"

        d1 = defer.Deferred()
        nA.agent.command_invite(u"petname-from-A", code,
                                override_transports=self.tports1,
                                _debug_when_done=d1)
        d2 = defer.Deferred()
        nB.agent.command_invite(u"petname-from-B", code+"WRONG",
                                override_transports=self.tports2,
                                _debug_when_done=d2)
        d3 = self.assertFailure(d1, WrongPasswordError)
        d3.addCallback(lambda _: self.assertFailure(d2, WrongPasswordError))
        def _done(res):
            self.failUnlessEqual(nA.agent.command_list_addressbook(), [])
            self.failUnlessEqual(nB.agent.command_list_addressbook(), [])
        d3.addCallback(_done)
        return d3
