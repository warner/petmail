import os.path, json
from twisted.application import service
from nacl.public import PrivateKey
from nacl.signing import SigningKey
from nacl.encoding import HexEncoder as Hex
from . import invitation, rrid
from .errors import CommandError
from .mailbox import channel, retrieval

class Agent(service.MultiService):
    def __init__(self, db, basedir, mailbox_server):
        service.MultiService.__init__(self)
        self.db = db
        self.mailbox_server = mailbox_server

        self.mailbox_retrievers = set()
        mboxes = {}
        c = self.db.execute("SELECT * FROM agent_profile").fetchone()
        if c["advertise_local_mailbox"]:
            local_tid = mailbox_server.get_local_transport()
            local_mbrec = mailbox_server.get_mailbox_record(local_tid)
            mboxes["local"] = local_mbrec["retrieval"]
        c = self.db.execute("SELECT * FROM mailboxes")
        for row in c.fetchall():
            mbrec = json.loads(row["mailbox_record_json"])
            mboxes[row["id"]] = mbrec["retrieval"]

        for mbid, rrec in mboxes.items():
            rc = self.build_retriever(mbid, rrec)
            self.subscribe_to_mailbox(rc)

        self.im = invitation.InvitationManager(db, self)
        c = self.db.execute("SELECT * FROM relay_servers")
        for row in c.fetchall():
            desc = json.loads(row["descriptor_json"])
            if desc["type"] == "localdir":
                from .rendezvous.localdir import LocalDirectoryRendezvousClient
                rdir = os.path.join(os.path.dirname(basedir), ".rendezvous")
                rs = LocalDirectoryRendezvousClient(rdir)
            if desc["type"] == "http":
                from .rendezvous.web_client import HTTPRendezvousClient
                rs = HTTPRendezvousClient(str(desc["url"]))
            self.im.addRendezvousService(rs)
        self.im.setServiceParent(self)

    def build_retriever(self, mbid, rrec):
        # parse descriptor, import correct module and constructor
        def got_msgC(msgC):
            self.msgC_received(mbid, msgC)
        retrieval_type = rrec["type"]
        if retrieval_type == "http":
            return retrieval.HTTPRetriever(rrec, got_msgC)
        elif retrieval_type == "local":
            return retrieval.LocalRetriever(rrec, got_msgC, self.mailbox_server)
        else:
            raise CommandError("unrecognized mailbox-retrieval protocol '%s'"
                               % retrieval_type)

    def subscribe_to_mailbox(self, rc):
        self.mailbox_retrievers.add(rc)
        # the retrieval client gets to make network connections, etc, as soon
        # as it starts. If we are "running" when we add it as a service
        # child, that happens here.
        rc.setServiceParent(self)

    def command_add_mailbox(self, mbrec):
        # TODO: (is this still accurate?) it'd be nice to make sure we can
        # build it, before committing it to the DB. But we need the tid
        # first, which comes from the DB. The commit-after-build below might
        # accomplish this anyways.
        mbid = self.db.insert("INSERT INTO mailboxes"
                              " (mailbox_record_json)"
                              " VALUES (?)",
                              (json.dumps(mbrec),),
                              "mailboxes")
        rc = self.build_retriever(mbid, mbrec["retrieval"])
        self.db.commit()
        self.subscribe_to_mailbox(rc)

    def msgC_received(self, tid, msgC):
        assert msgC.startswith("c0:")
        cid, seqnum, payload_json = channel.process_msgC(self.db, msgC)
        self.payload_received(cid, seqnum, payload_json)

    def payload_received(self, cid, seqnum, payload_json):
        self.db.insert("INSERT INTO inbound_messages"
                        " (cid, seqnum, payload_json)"
                        " VALUES (?,?,?)",
                        (cid, seqnum, payload_json),
                       "inbound_messages")
        self.db.commit()
        #payload = json.loads(payload_json)
        #print "payload_received", cid, seqnum, payload
        #if payload.has_key("basic"):
        #    print "BASIC:", payload["basic"]

    def command_invite(self, petname, code, override_transports=None):
        my_signkey = SigningKey.generate()
        channel_key = PrivateKey.generate()
        my_CID_key = os.urandom(32)

        base_transports = self.get_transports()
        if override_transports:
            base_transports = override_transports
        transports = self.individualize_transports(base_transports)
        tids = ",".join([str(tid) for tid in sorted(transports.keys())])

        payload = { "channel_pubkey": channel_key.public_key.encode(Hex),
                    "CID_key": my_CID_key.encode("hex"),
                    "transports": transports.values(),
                     }
        private = { "my_signkey": my_signkey.encode(Hex),
                    "my_CID_key": my_CID_key.encode("hex"),
                    "my_old_channel_privkey": channel_key.encode(Hex),
                    "my_new_channel_privkey": channel_key.encode(Hex),
                    "transport_ids": tids,
                    }

        self.im.startInvitation(petname, code, my_signkey, payload, private)
        return "invitation for %s started" % petname

    def invitation_done(self, petname, me, them, their_verfkey):
        cid = self.db.insert(
            "INSERT INTO addressbook"
            " (petname, acked,"
            "  next_outbound_seqnum, my_signkey,"
            "  their_channel_record_json,"
            "  my_CID_key, next_CID_token,"
            "  highest_inbound_seqnum,"
            "  my_old_channel_privkey, my_new_channel_privkey,"
            "  they_used_new_channel_key, their_verfkey)"
            " VALUES (?,?, "
            "         ?,?,"
            "         ?,"
            "         ?,?," # my_CID_key, next_CID_token
            "         ?,"   # highest_inbound_seqnum
            "         ?,?,"
            "         ?,?)",
            (petname, 0,
             1, me["my_signkey"],
             json.dumps(them),
             me["my_CID_key"], None,
             0,
             me["my_old_channel_privkey"],
             me["my_new_channel_privkey"],
             0, their_verfkey.encode().encode("hex") ),
            "addressbook")
        return cid

    def invitation_acked(self, cid):
        self.db.update("UPDATE addressbook SET acked=1 WHERE id=?", (cid,),
                       "addressbook", cid)

    def command_send_basic_message(self, cid, message):
        self.send_message(cid, {"basic": message}) # ignore Deferred
        return "maybe sent"

    def send_message(self, cid, payload):
        c = channel.OutboundChannel(self.db, cid)
        return c.send(payload)

    def get_transports(self):
        # returns dict of mbid->pubrecord . These will be individualized
        # before delivery to the peer.
        local_tid = self.mailbox_server.get_local_transport()
        local_mbrec = self.mailbox_server.get_mailbox_record(local_tid)
        transports = {"local": local_mbrec}
        for row in self.db.execute("SELECT * FROM mailboxes").fetchall():
            transports[row["id"]] = json.loads(row["mailbox_record_json"])
        return transports

    def individualize_transports(self, base_transports):
        transports = {}
        for mbid, base in base_transports.items():
            t = base["transport"]["generic"].copy()
            TT0 = base["transport"]["sender"]["TT0"].decode("hex")
            t["STT"] = rrid.randomize(TT0).encode("hex")
            transports[mbid] = t
        return transports

    def command_list_addressbook(self):
        resp = []
        for row in self.db.execute("SELECT * FROM addressbook").fetchall():
            entry = {}
            entry["cid"] = row["id"]
            entry["their_verfkey"] = str(row["their_verfkey"])
            entry["their_channel_record"] = json.loads(row["their_channel_record_json"])
            entry["petname"] = row["petname"]
            # TODO: filter out the long-term stuff
            sk = SigningKey(row["my_signkey"].decode("hex"))
            entry["my_verfkey"] = sk.verify_key.encode(Hex)
            entry["acked"] = bool(row["acked"])
            resp.append(entry)
        return resp

    def command_fetch_all_messages(self):
        c = self.db.execute("SELECT inbound_messages.*,addressbook.petname"
                            " FROM inbound_messages,addressbook"
                            " WHERE inbound_messages.cid = addressbook.id")
        return [{ "id": row["id"],
                  "petname": row["petname"],
                  "cid": row["cid"],
                  "seqnum": row["seqnum"],
                  "payload": json.loads(row["payload_json"]),
                  }
                for row in c.fetchall()]
