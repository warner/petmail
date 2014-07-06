import os.path, json, time
from twisted.application import service
from nacl.public import PrivateKey
from nacl.signing import SigningKey
from nacl.encoding import HexEncoder as Hex
from . import invitation, rrid
from .errors import CommandError, ContactNotReadyError
from .mailbox import channel, retrieval
from .util import to_ascii

class Agent(service.MultiService):
    def __init__(self, db, basedir, mailbox_server):
        service.MultiService.__init__(self)
        self.db = db
        self.mailbox_server = mailbox_server

        self.mailbox_retrievers = set()
        c = self.db.execute("SELECT * FROM agent_profile").fetchone()
        self.advertise_local_mailbox = bool(c["advertise_local_mailbox"])
        mboxes = {}
        if self.advertise_local_mailbox:
            local_tid = mailbox_server.get_local_transport()
            local_mbrec = mailbox_server.get_mailbox_record(local_tid)
            mboxes["local"] = local_mbrec["retrieval"]
        for row in self.db.execute("SELECT * FROM mailboxes").fetchall():
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
            self.im.add_rendezvous_service(rs)
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

    def msgC_received(self, tid, msgC):
        assert msgC.startswith("c0:")
        cid, seqnum, payload_json = channel.process_msgC(self.db, msgC)
        self.payload_received(cid, seqnum, payload_json)

    def payload_received(self, cid, seqnum, payload_json):
        self.db.insert("INSERT INTO inbound_messages"
                        " (cid, seqnum, when_received, payload_json)"
                        " VALUES (?,?,?,?)",
                        (cid, seqnum, time.time(), payload_json),
                       "inbound_messages")
        self.db.commit()
        #payload = json.loads(payload_json)
        #print "payload_received", cid, seqnum, payload
        #if payload.has_key("basic"):
        #    print "BASIC:", payload["basic"]

    def command_invite(self, petname, code, reqid=None,
                       generate=False,
                       override_transports=None, offer_mailbox=False,
                       accept_mailbox=False):
        if generate:
            if code:
                raise CommandError("please use --generate or --code, not both")
            code = to_ascii(os.urandom(16), "", "base32")
        my_signkey = SigningKey.generate()
        channel_key = PrivateKey.generate()
        my_CID_key = os.urandom(32)

        base_transports = self.get_transports()
        if override_transports:
            base_transports = override_transports
        transports = self.individualize_transports(base_transports)

        channel = { "channel_pubkey": channel_key.public_key.encode(Hex),
                    "CID_key": my_CID_key.encode("hex"),
                    "transports": transports.values(),
                     }
        payload = { "channel": channel }
        private = { "petname": petname, # used by process_M3 for logging
                    }

        if offer_mailbox:
            tid = self.mailbox_server.allocate_transport(remote=True)
            private["mailbox_tid"] = tid # XXX not used?
            payload["mailbox"] = self.mailbox_server.get_mailbox_record(tid)
        private["accept_mailbox"] = accept_mailbox

        cid = self.db.insert(
            "INSERT INTO addressbook"
            " (petname, acked, when_invited, invitation_code,"
            "  next_outbound_seqnum, my_signkey,"
            "  my_CID_key, next_CID_token,"
            "  highest_inbound_seqnum,"
            "  my_old_channel_privkey,"
            "  my_new_channel_privkey)"
            " VALUES (?,?,?,?, ?,?, ?,?, ?, ?, ?)",
            (petname, 0, time.time(), code,
             1, my_signkey.encode(Hex),
             my_CID_key.encode("hex"), None,
             0,
             channel_key.encode(Hex),
             channel_key.encode(Hex), # at beginning, old=new
             ),
            "addressbook", {"reqid": reqid})

        iid = self.im.start_invitation(cid, code, my_signkey, payload, private)
        self.db.update("UPDATE addressbook SET invitation_id=? WHERE id=?",
                       (iid, cid), "addressbook", cid, {"reqid": reqid})
        return {"contact-id": cid, "invite-id": iid, "petname": petname,
                "code": code,
                "ok": "invitation for %s started: invite-id: %d" %
                (petname, iid)}

    def invitation_done(self, cid, private, them, their_verfkey):
        self.db.update(
            "UPDATE addressbook SET"
            " when_accepted=?,"
            " their_channel_record_json=?,"
            " they_used_new_channel_key=?, their_verfkey=?"
            "WHERE id=?",
            (time.time(),
             json.dumps(them["channel"]),
             0, their_verfkey.encode().encode("hex"),
             cid), "addressbook", cid)
        mailbox = them.get("mailbox")
        if mailbox and private["accept_mailbox"]:
            mbid = self.db.insert("INSERT INTO mailboxes"
                                  " (mailbox_record_json) VALUES (?)",
                                  (json.dumps(mailbox),), "mailboxes")
            rc = self.build_retriever(mbid, mailbox["retrieval"])
            self.subscribe_to_mailbox(rc)
        return cid

    def invitation_acked(self, cid):
        self.db.update("UPDATE addressbook SET acked=1, invitation_id=NULL"
                       " WHERE id=?", (cid,),
                       "addressbook", cid)

    def command_offer_mailbox(self, petname):
        code = to_ascii(os.urandom(16), "mailbox-", "base32")
        self.command_invite(petname, code, offer_mailbox=True)
        return "invitation code: %s" % code

    def command_accept_mailbox(self, petname, code):
        return self.command_invite(petname, code, accept_mailbox=True)

    def command_send_basic_message(self, cid, message):
        try:
            self.send_message(cid, {"basic": message}) # ignore Deferred
        except ContactNotReadyError:
            raise CommandError("cid %d is not ready for messages" % cid)
        return "maybe sent"

    def send_message(self, cid, payload):
        row = self.db.execute("SELECT acked, their_channel_record_json"
                              " FROM addressbook WHERE id=?", (cid,)).fetchone()
        if not row["acked"] or not row["their_channel_record_json"]:
            raise ContactNotReadyError("cid %d is not ready for messages" % cid)
        self.db.insert("INSERT INTO outbound_messages"
                       " (cid, when_sent, payload_json)"
                       " VALUES (?,?,?)",
                       (cid, time.time(), json.dumps(payload)),
                       "outbound_messages")
        self.db.commit() # XXX ?. Or wait for c.send() to commit?
        c = channel.OutboundChannel(self.db, cid)
        return c.send(payload)

    def get_transports(self):
        # returns dict of mbid->pubrecord . These will be individualized
        # before delivery to the peer.
        transports = {}
        if self.advertise_local_mailbox:
            local_tid = self.mailbox_server.get_local_transport()
            local_mbrec = self.mailbox_server.get_mailbox_record(local_tid)
            transports["local"] = local_mbrec
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
        # these entries might merely be incomplete invitations
        for row in self.db.execute("SELECT * FROM addressbook").fetchall():
            entry = {}
            # these properties are set right away
            entry["cid"] = row["id"]
            entry["petname"] = row["petname"]
            entry["acked"] = bool(row["acked"])
            entry["invitation_context"] = {
                "when_invited": row["when_invited"],
                "code": row["invitation_code"],
                }
            sk = SigningKey(row["my_signkey"].decode("hex"))
            entry["my_verfkey"] = sk.verify_key.encode(Hex)

            # these appear when the invitation process is complete
            if row["when_accepted"] is not None:
                entry["invitation_context"]["when_accepted"] = row["when_accepted"]
            if row["their_verfkey"] is not None:
                entry["their_verfkey"] = str(row["their_verfkey"])
            if row["their_channel_record_json"] is not None:
                entry["their_channel_record"] = json.loads(row["their_channel_record_json"])
            # TODO: filter out the long-term stuff
            resp.append(entry)
        return resp

    def command_set_petname(self, cid, petname):
        self.db.update("UPDATE addressbook SET petname=? WHERE id=?",
                       (petname, cid),
                       "addressbook", cid)
        self.db.commit()

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
