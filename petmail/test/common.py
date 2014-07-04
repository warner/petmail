import os, json
from twisted.python import failure
from twisted.internet import defer
from twisted.application import service
from StringIO import StringIO
from nacl.public import PrivateKey
from nacl.signing import SigningKey
from ..scripts import runner, startstop
from ..scripts.create_node import create_node
from .. import rrid
from .pollmixin import PollMixin

class ShouldFailMixin:
    def shouldFail(self, expected_failure, substring,
                   response_substring,
                   callable, *args, **kwargs):
        assert substring is None or isinstance(substring, str)
        assert response_substring is None or isinstance(response_substring, str)
        d = defer.maybeDeferred(callable, *args, **kwargs)
        def done(res):
            if isinstance(res, failure.Failure):
                res.trap(expected_failure)
                if substring:
                    self.failUnlessIn(substring, str(res),
                                      "'%s' not in '%s' (response is '%s')" %
                                      (substring, str(res),
                                       getattr(res.value, "response", "")))
                if response_substring:
                    self.failUnlessIn(response_substring, res.value.response,
                                      "'%s' not in '%s'" %
                                      (response_substring, res.value.response))
            else:
                self.fail("was supposed to raise %s, not get '%s'" %
                          (expected_failure, res))
        d.addBoth(done)
        return d

class BasedirMixin:
    def make_basedir(self):
        # TestCase.mktemp() creates _trial_temp/MODULE/CLASS/TEST/RANDOM and
        # returns join(that,"temp"). We just want the part that ends with
        # TEST. So we rmdir the RANDOM and return .../TEST
        basedir = self.mktemp()
        random = os.path.dirname(basedir)
        os.rmdir(random)
        test = os.path.dirname(random)
        return test

class NodeRunnerMixin:
    def setUp(self):
        self.sparent = service.MultiService()
        self.sparent.startService()

    def tearDown(self):
        return self.sparent.stopService()

    def createNode(self, basedir, type="agent", relayurl="LOCALDIR",
                   local_mailbox=True):
        so = runner.CreateNodeOptions()
        args = []
        if local_mailbox:
            args.append("--local-mailbox")
        assert relayurl
        args.extend(["--relay-url", relayurl])
        args.append(basedir)
        so.parseOptions(args)
        out,err = StringIO(), StringIO()
        rc = create_node(so, out, err, [type])
        self.failUnlessEqual(rc, 0, (rc, out, err))
        return rc, out ,err

    def buildNode(self, basedir):
        so = runner.StartNodeOptions()
        so.parseOptions([basedir])
        p = startstop.MyPlugin(basedir, os.path.join(basedir, "petmail.db"))
        n = p.makeService(so)
        return n

    def startNode(self, basedir):
        n = self.buildNode(basedir)
        n.setServiceParent(self.sparent)
        return n

    def disable_polling(self, n):
        list(n.agent.im)[0].enable_polling = False

    def accelerate_polling(self, n):
        list(n.agent.im)[0].polling_interval = 0.01

def fake_transport():
    privkey = PrivateKey.generate()
    pubkey_hex = privkey.public_key.encode().encode("hex")
    TT_privkey, TT_pubkey = rrid.create_keypair()
    TTID, TT0 = rrid.create_token(TT_pubkey)
    mbrec = {"transport": {"generic": {"type": "test-return",
                                       "transport_pubkey": pubkey_hex,},
                           "sender": {"TT0": TT0.encode("hex")}},
             "retrieval": {"type": "test-return-retrieval",
                           # extra things that a normal retriever wouldn't
                           # get
                           "privkey": privkey.encode().encode("hex"),
                           "TTID": TTID.encode("hex"),
                           "TT_privkey": TT_privkey.encode("hex"),
                           },
             }
    return mbrec


class TwoNodeMixin(BasedirMixin, NodeRunnerMixin, PollMixin):
    def make_nodes(self, transport="test-return", relay="localdir"):
        assert transport in ["test-return", "local", "none"]
        relayurl = "LOCALDIR"
        if relay == "http":
            basedirR = os.path.join(self.make_basedir(), "relay")
            self.createNode(basedirR, type="relay")
            nR = self.startNode(basedirR)
            self.relay = nR
            row = nR.db.execute("SELECT baseurl FROM node").fetchone()
            relayurl = row["baseurl"]
            assert relayurl

        basedirA = os.path.join(self.make_basedir(), "nodeA")
        local_mailbox = True
        if transport == "none":
            local_mailbox = False
        self.createNode(basedirA, relayurl=relayurl,
                        local_mailbox=local_mailbox)
        basedirB = os.path.join(self.make_basedir(), "nodeB")
        self.createNode(basedirB, relayurl=relayurl,
                        local_mailbox=local_mailbox)

        # TODO: do we need to pre-instantiate these anymore?
        self.buildNode(basedirA)
        self.buildNode(basedirB)
        if transport in ("local", "none"):
            self.tports1 = None
            self.tports2 = None

        nA = self.startNode(basedirA)
        nB = self.startNode(basedirB)

        if transport == "test-return":
            # TODO: the fake_transport() doesn't persist well, so create it
            # on the real (live) nodes instead of the temporary setup ones.
            # This should be fixed.
            self.tports1 = {"local": fake_transport()}
            nA.db.execute("INSERT INTO mailboxes"
                          " (mailbox_record_json)"
                          " VALUES (?)",
                          (json.dumps(self.tports1["local"]),))
            nA.db.commit()
            self.tports2 = {"local": fake_transport()}
            nB.db.execute("INSERT INTO mailboxes"
                          " (mailbox_record_json)"
                          " VALUES (?)",
                          (json.dumps(self.tports2["local"]),))
            nB.db.commit()

        self.accelerate_polling(nA)
        self.accelerate_polling(nB)
        return nA, nB

    def add_new_channel_with_invitation(self, nA, nB,
                                        offer_mailbox=False,
                                        accept_mailbox=False):
        code = "code"
        nA.agent.im._debug_invitations_completed = 0
        nB.agent.im._debug_invitations_completed = 0
        nA.agent.command_invite(u"petname-from-A", code,
                                override_transports=self.tports1,
                                accept_mailbox=accept_mailbox)
        nB.agent.command_invite(u"petname-from-B", code,
                                override_transports=self.tports2,
                                offer_mailbox=offer_mailbox)
        rclientA = list(nA.agent.im)[0]
        rclientB = list(nB.agent.im)[0]
        def check():
            return (nA.agent.im._debug_invitations_completed
                    and nB.agent.im._debug_invitations_completed
                    and rclientA.is_idle()
                    and rclientB.is_idle()
                    )
        d = self.poll(check)
        def _done(_):
            entA = nA.db.execute("SELECT * FROM addressbook").fetchone()
            entB = nB.db.execute("SELECT * FROM addressbook").fetchone()
            return entA, entB
        d.addCallback(_done)
        return d

    def make_connected_nodes(self, transport="test-return"):
        # skip Invitation, just populate the database directly
        nA, nB = self.make_nodes(transport)
        entA, entB = self.add_new_channel(nA, nB)
        return nA, nB, entA, entB

    def add_new_channel(self, nA, nB):
        a_signkey = SigningKey.generate()
        a_chankey = PrivateKey.generate()
        a_CIDkey = os.urandom(32)
        a_transports = nA.agent.individualize_transports(nA.agent.get_transports())

        b_signkey = SigningKey.generate()
        b_chankey = PrivateKey.generate()
        b_CIDkey = os.urandom(32)
        b_transports = nB.agent.individualize_transports(nB.agent.get_transports())

        a_rec = { "channel_pubkey": a_chankey.public_key.encode().encode("hex"),
                  "CID_key": a_CIDkey.encode("hex"),
                  "transports": a_transports.values(),
                  }

        b_rec = { "channel_pubkey": b_chankey.public_key.encode().encode("hex"),
                  "CID_key": b_CIDkey.encode("hex"),
                  "transports": b_transports.values(),
                  }

        q = ("INSERT INTO addressbook"
             " (petname, acked, next_outbound_seqnum,"
             "  my_signkey,"
             "  their_channel_record_json,"
             "  my_CID_key, next_CID_token,"
             "  highest_inbound_seqnum,"
             "  my_old_channel_privkey, my_new_channel_privkey,"
             "  they_used_new_channel_key, their_verfkey)"
             " VALUES(?,?,?,?,?,?,?,?,?,?,?,?)")

        vA=("petname-from-A", 1, 1,
            a_signkey.encode().encode("hex"),
            json.dumps(b_rec),
            a_CIDkey.encode("hex"), None,
            0,
            a_chankey.encode().encode("hex"),
            a_chankey.encode().encode("hex"),
            0, b_signkey.verify_key.encode().encode("hex"),
            )

        vB=("petname-from-A", 1, 1,
            b_signkey.encode().encode("hex"),
            json.dumps(a_rec),
            b_CIDkey.encode("hex"), None,
            0,
            b_chankey.encode().encode("hex"),
            b_chankey.encode().encode("hex"),
            0, a_signkey.verify_key.encode().encode("hex"),
            )

        nA.db.execute(q, vA)
        nA.db.commit()
        nB.db.execute(q, vB)
        nA.db.commit()

        entA = nA.db.execute("SELECT * FROM addressbook").fetchone()
        entB = nB.db.execute("SELECT * FROM addressbook").fetchone()
        return entA, entB

    def add_recipient(self, n):
        ms = n.mailbox_server
        tid = ms.allocate_transport()
        mbrec = ms.get_mailbox_record(tid)
        TT0 = mbrec["transport"]["sender"]["TT0"].decode("hex")
        STT = rrid.randomize(TT0)
        transport_pubkey = mbrec["transport"]["generic"]["transport_pubkey"]
        trec = {"STT": STT.encode("hex"),
                "transport_pubkey": transport_pubkey,
                "retrieval_pubkey": mbrec["retrieval"]["retrieval_pubkey"]}
        return tid, trec

    def create_unknown_STT(self, n):
        row = n.db.execute("SELECT * FROM mailbox_server_config").fetchone()
        sc = json.loads(row["mailbox_config_json"])
        TT_pubkey = sc["TT_public_key"].decode("hex")
        TTID_1, TT0_1 = rrid.create_token(TT_pubkey)
        STT_1 = rrid.randomize(TT0_1)
        return STT_1

def flip_bit(s):
    return s[:-1] + chr(ord(s[-1]) ^ 0x01)
