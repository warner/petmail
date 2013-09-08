import os, json
from twisted.application import service
from StringIO import StringIO
from nacl.public import PrivateKey
from nacl.signing import SigningKey
from ..scripts import runner, startstop
from ..scripts.create_node import create_node
from .. import rrid
from .pollmixin import PollMixin

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

    def createNode(self, basedir, type="client", relayurl=None):
        so = runner.CreateNodeOptions()
        args = []
        if relayurl:
            args.extend(["--relay-url", relayurl])
        args.append(basedir)
        so.parseOptions(args)
        out,err = StringIO(), StringIO()
        rc = create_node(so, out, err, [type])
        self.failUnlessEqual(rc, 0, (rc, out, err))
        return rc, out ,err

    def startNode(self, basedir):
        so = runner.StartNodeOptions()
        so.parseOptions([basedir])
        p = startstop.MyPlugin(basedir, os.path.join(basedir, "petmail.db"))
        n = p.makeService(so)
        n.setServiceParent(self.sparent)
        return n

    def disable_polling(self, n):
        list(n.client.im)[0].enable_polling = False

    def accelerate_polling(self, n):
        list(n.client.im)[0].polling_interval = 0.01

def fake_transport():
    privkey = PrivateKey.generate()
    pubkey_hex = privkey.public_key.encode().encode("hex")
    TID_tokenid, TID_privkey, TID_token0 = rrid.create()
    private = {"privkey": privkey,
               "TID": (TID_tokenid, TID_privkey, TID_token0) }
    # this is what lives in our database. All channels that share the same
    # transport will use the same thing.
    db_record = { "for_sender": {"type": "test-return",
                                 "transport_pubkey": pubkey_hex,
                                 },
                  "for_recipient": {"TID": TID_token0.encode("hex") },
                  }
    return private, db_record


class TwoNodeMixin(BasedirMixin, NodeRunnerMixin, PollMixin):
    def make_nodes(self, transport="test-return", relay="localdir"):
        relayurl = None
        if relay == "http":
            basedirR = os.path.join(self.make_basedir(), "relay")
            self.createNode(basedirR, "relay")
            nR = self.startNode(basedirR)
            row = nR.db.execute("SELECT baseurl FROM node").fetchone()
            relayurl = row["baseurl"]

        basedirA = os.path.join(self.make_basedir(), "nodeA")
        self.createNode(basedirA, relayurl=relayurl)
        nA = self.startNode(basedirA)
        self.accelerate_polling(nA)

        basedirB = os.path.join(self.make_basedir(), "nodeB")
        self.createNode(basedirB, relayurl=relayurl)
        nB = self.startNode(basedirB)
        self.accelerate_polling(nB)

        if transport == "test-return":
            self.tport1 = fake_transport()
            self.tports1 = {0: self.tport1[1]}
            nA.db.execute("INSERT INTO mailboxes"
                          " (sender_descriptor_json, private_descriptor_json)"
                          " VALUES (?,?)",
                          (json.dumps(self.tport1[1]["for_sender"]),
                           json.dumps(self.tport1[1]["for_recipient"])))
            nA.db.commit()
            self.tport2 = fake_transport()
            self.tports2 = {0: self.tport2[1]}
            nB.db.execute("INSERT INTO mailboxes"
                          " (sender_descriptor_json, private_descriptor_json)"
                          " VALUES (?,?)",
                          (json.dumps(self.tport2[1]["for_sender"]),
                           json.dumps(self.tport2[1]["for_recipient"])))
            nB.db.commit()
        elif transport == "local":
            nA.client.command_enable_local_mailbox()
            nB.client.command_enable_local_mailbox()
            self.tports1 = None
            self.tports2 = None
        else:
            raise KeyError("huh?")

        return nA, nB

    def add_new_channel_with_invitation(self, nA, nB):
        code = "code"
        nA.client.im._debug_invitations_completed = 0
        nB.client.im._debug_invitations_completed = 0
        nA.client.command_invite(u"petname-from-A", code,
                                 override_transports=self.tports1)
        nB.client.command_invite(u"petname-from-B", code,
                                 override_transports=self.tports2)
        rclientA = list(nA.client.im)[0]
        rclientB = list(nB.client.im)[0]
        def check():
            return (nA.client.im._debug_invitations_completed
                    and nB.client.im._debug_invitations_completed
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
        a_transports = nA.client.individualize_transports(nA.client.get_transports())

        b_signkey = SigningKey.generate()
        b_chankey = PrivateKey.generate()
        b_CIDkey = os.urandom(32)
        b_transports = nB.client.individualize_transports(nB.client.get_transports())

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
