import os, sys, json
from twisted.python import failure
from twisted.internet import defer
from twisted.internet import threads # CLI tests use deferToThread
from twisted.internet.utils import getProcessOutputAndValue
from twisted.application import service
from StringIO import StringIO
from nacl.public import PrivateKey
from nacl.signing import SigningKey
import wormhole
from wormhole.twisted.util import allocate_port
from wormhole.servers.relay import RelayServer
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
        d = allocate_port()
        def _allocated(port):
            p = "tcp:%d:interface=127.0.0.1" % port
            r = RelayServer(p, None, wormhole.__version__)
            r.setServiceParent(self.sparent)
            self.relay_url = "http://127.0.0.1:%d/wormhole-relay/" % port
        d.addCallback(_allocated)
        return d

    def tearDown(self):
        return self.sparent.stopService()

    def createNode(self, basedir, type="agent", local_mailbox=True):
        so = runner.CreateNodeOptions()
        args = []
        if local_mailbox:
            args.append("--local-mailbox")
        args.extend(["--relay-url", self.relay_url])
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


class CLIinThreadMixin:
    def cli(self, *args, **kwargs):
        stdout, stderr = StringIO(), StringIO()
        d = threads.deferToThread(runner.run, list(args), stdout, stderr,
                                  kwargs.get("petmail"))
        def _done(rc):
            return stdout.getvalue(), stderr.getvalue(), rc
        d.addCallback(_done)
        return d
    def mustSucceed(self, (out, err, rc)):
        if rc != 0:
            self.fail("rc=%s out='%s' err='%s'" % (rc, out, err))
        self.stderr = err
        return out

    def cliMustSucceed(self, *args, **kwargs):
        d = self.cli(*args, **kwargs)
        d.addCallback(self.mustSucceed)
        return d

class CLIinProcessMixin(CLIinThreadMixin):
    def cli(self, *args, **kwargs):
        petmail = runner.petmail_executable[0]
        d = getProcessOutputAndValue(sys.executable, [petmail] + list(args),
                                     os.environ)
        return d

    def anyways(self, res, cb, *args, **kwargs):
        # always run the cleanup callback
        d = defer.maybeDeferred(cb, *args, **kwargs)
        if isinstance(res, failure.Failure):
            # let the original failure passthrough
            d.addBoth(lambda _: res)
        # otherwise the original result was success, so just return the
        # cleanup result
        return d


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
    def make_nodes(self, transport="test-return"):
        assert transport in ["test-return", "local", "none"]

        basedirA = os.path.join(self.make_basedir(), "nodeA")
        local_mailbox = True
        if transport == "none":
            local_mailbox = False
        self.createNode(basedirA, local_mailbox=local_mailbox)
        basedirB = os.path.join(self.make_basedir(), "nodeB")
        self.createNode(basedirB, local_mailbox=local_mailbox)

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

        return nA, nB

    def wait_for_code(self, node, res):
        iid = res["invite-id"]
        i = node.agent.im._debug_invitations[iid]
        d = i._debug_when_got_code = defer.Deferred()
        return d

    def add_new_channel_with_invitation(self, nA, nB,
                                        offer_mailbox=False,
                                        accept_mailbox_offer=False):
        d1 = defer.Deferred()
        d2 = defer.Deferred()
        res = nA.agent.command_invite(u"petname-from-A", maybe_code=None,
                                      override_transports=self.tports1,
                                      accept_mailbox_offer=accept_mailbox_offer,
                                      _debug_when_done=d1)
        d = self.wait_for_code(nA, res)
        def _got_code(code):
            nB.agent.command_invite(u"petname-from-B", code,
                                    override_transports=self.tports2,
                                    offer_mailbox=offer_mailbox,
                                    _debug_when_done=d2)
            return d1
        d.addCallback(_got_code)
        def _A_done(cid_a):
            return d2
        d.addCallback(_A_done)
        def _B_done(cid_b):
            return
        d.addCallback(_B_done)
        def _done(_):
            entA = nA.agent.command_list_addressbook()[0]
            entB = nB.agent.command_list_addressbook()[0]
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
