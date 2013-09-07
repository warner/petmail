import os.path, json
from twisted.application import service
from nacl.signing import SigningKey
from nacl.encoding import HexEncoder as Hex
from . import invitation, rrid
from .rendezvous import localdir
from .errors import CommandError
from .mailbox import channel, retrieval

class Client(service.MultiService):
    def __init__(self, db, basedir, mailbox_server):
        service.MultiService.__init__(self)
        self.db = db
        self.mailbox_server = mailbox_server

        self.local_server = None
        self.mailboxClients = set()
        c = self.db.execute("SELECT id, private_descriptor_json FROM mailboxes")
        for row in c.fetchall():
            privdesc = json.loads(row["private_descriptor_json"])
            rc = self.buildRetrievalClient(row["id"], privdesc)
            self.subscribeToMailbox(rc)

        self.im = invitation.InvitationManager(db, self)
        rdir = os.path.join(os.path.dirname(basedir), ".rendezvous")
        rs_localdir = localdir.LocalDirectoryRendezvousClient(rdir)
        self.im.addRendezvousService(rs_localdir)
        self.im.setServiceParent(self)

    def subscribe(self, table, observer):
        self.db.subscribe(table, observer)

    def unsubscribe(self, table, observer):
        self.db.unsubscribe(table, observer)

    def buildRetrievalClient(self, tid, private_descriptor):
        # parse descriptor, import correct module and constructor
        extra_args = {}
        retrieval_type = private_descriptor["type"]
        if retrieval_type == "http":
            retrieval_class = retrieval.HTTPRetriever
        elif retrieval_type == "local":
            retrieval_class = retrieval.LocalRetriever
            assert self.mailbox_server
            extra_args["server"] = self.mailbox_server
        else:
            raise CommandError("unrecognized mailbox-retrieval protocol '%s'"
                               % retrieval_type)
        def got_msgC(msgC):
            self.msgC_received(tid, msgC)
        rc = retrieval_class(private_descriptor, got_msgC, **extra_args)
        return rc

    def subscribeToMailbox(self, rc):
        self.mailboxClients.add(rc)
        # the retrieval client gets to make network connections, etc, as soon
        # as it starts. If we are "running" when we add it as a service
        # child, that happens here.
        rc.setServiceParent(self)

    def command_add_mailbox(self, sender_descriptor, private_descriptor):
        # it'd be nice to make sure we can build it, before committing it to
        # the DB. But we need the tid first, which comes from the DB. The
        # commit-after-build below might accomplish this anyways.
        tid = self.db.insert("INSERT INTO mailboxes"
                             " (sender_descriptor_json,private_descriptor_json)"
                             " VALUES (?,?)",
                             (json.dumps(sender_descriptor),
                              json.dumps(private_descriptor)),
                             "mailboxes")
        rc = self.buildRetrievalClient(tid, private_descriptor)
        self.db.commit()
        self.subscribeToMailbox(rc)

    def command_enable_local_mailbox(self):
        # create the persistent state needed to run a mailbox from our webapi
        # port. Then activate it. This should only be called once.
        for row in self.db.execute("SELECT * FROM mailboxes").fetchall():
            privdesc = json.loads(row["private_descriptor_json"])
            if privdesc["type"] == "local":
                raise CommandError("local server already activated")
        server = self.mailbox_server
        self.command_add_mailbox(server.get_sender_descriptor(),
                                 server.get_retrieval_descriptor())
        # that will build a Retriever that connects to the local mailbox
        # server, with persistence for later runs

        # TODO: consider telling the server, here, to start accepting TIDs
        # for the local client (and not accepting such TIDs by default) (and
        # persist that state for later)

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

    def _command_invite(self, petname, code, override_transports=None):
        base_transports = self.get_transports()
        if override_transports:
            base_transports = override_transports
        transports = self.individualize_transports(base_transports)
        return self.im.startInvitation(petname, code, transports)
    def command_invite(self, petname, code, override_transports=None):
        # ignore the Deferred: the command form is launch-and-forget
        self._command_invite(petname, code, override_transports)
        return "invitation for %s started" % petname

    def command_send_basic_message(self, cid, message):
        self.send_message(cid, {"basic": message}) # ignore Deferred
        return "maybe sent"

    def send_message(self, cid, payload):
        c = channel.OutboundChannel(self.db, cid)
        return c.send(payload)

    def get_transports(self):
        # returns dict of tid->pubrecord . These will be individualized
        # before delivery to the peer.
        transports = {}
        for row in self.db.execute("SELECT * FROM mailboxes").fetchall():
            transports[row["id"]] = {
                "for_sender": json.loads(row["sender_descriptor_json"]),
                "for_recipient": json.loads(row["private_descriptor_json"]),
                }
        return transports

    def individualize_transports(self, base_transports):
        transports = {}
        for tid, base in base_transports.items():
            t = base["for_sender"].copy()
            TID_token0 = base["for_recipient"]["TID"].decode("hex")
            t["STID"] = rrid.randomize(TID_token0).encode("hex")
            transports[tid] = t
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
