import os.path, weakref, json
from twisted.application import service
from nacl.signing import SigningKey
from nacl.encoding import HexEncoder as Hex
from . import invitation, rrid
from .rendezvous import localdir
from .errors import CommandError
from .mailbox import channel

class Client(service.MultiService):
    def __init__(self, db, basedir, mailbox_server):
        service.MultiService.__init__(self)
        self.db = db
        self.mailbox_server = mailbox_server

        self.subscribers = weakref.WeakKeyDictionary()

        self.local_server = None
        self.mailboxClients = set()
        c = self.db.cursor()
        c.execute("SELECT id, private_descriptor_json FROM mailboxes")
        for row in c.fetchall():
            privdesc = json.loads(row["private_descriptor_json"])
            rc = self.buildRetrievalClient(row["id"], privdesc)
            self.subscribeToMailbox(rc)

        self.im = invitation.InvitationManager(db, self)
        rdir = os.path.join(os.path.dirname(basedir), ".rendezvous")
        rs_localdir = localdir.LocalDirectoryRendezvousClient(rdir)
        self.im.addRendezvousService(rs_localdir)
        self.im.setServiceParent(self)

    def buildRetrievalClient(self, tid, private_descriptor):
        # parse descriptor, import correct module and constructor
        extra_args = {}
        retrieval_type = private_descriptor["type"]
        if retrieval_type == "http":
            from .mailbox.retrieval import HTTPRetriever
            retrieval_class = HTTPRetriever
        elif retrieval_type == "local":
            from .mailbox.retrieval import LocalRetriever
            retrieval_class = LocalRetriever
            if not self.mailbox_server:
                raise ValueError("LocalRetriever requires MailboxServer")
            extra_args["server"] = self.mailbox_server
        else:
            raise CommandError("unrecognized mailbox-retrieval protocol '%s'"
                               % retrieval_type)
        rc = retrieval_class(tid, private_descriptor, self, self.db,
                             **extra_args)
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
        c = self.db.cursor()
        c.execute("INSERT INTO mailboxes"
                  " (sender_descriptor_json, private_descriptor_json)"
                  " VALUES (?,?)",
                  (json.dumps(sender_descriptor),
                   json.dumps(private_descriptor)))
        tid = c.lastrowid
        rc = self.buildRetrievalClient(tid, private_descriptor)
        self.db.commit()
        self.subscribeToMailbox(rc)

    def command_enable_local_mailbox(self):
        # create the persistent state needed to run a mailbox from our webapi
        # port. Then activate it. This should only be called once.
        c = self.db.cursor()
        c.execute("SELECT * FROM mailboxes")
        for row in c.fetchall():
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

    def message_received(self, tid, msgC):
        assert msgC.startswith("c0:")
        pass

    def command_invite(self, petname, code, override_transports=None):
        base_transports = self.get_transports()
        if override_transports:
            base_transports = override_transports
        transports = self.individualize_transports(base_transports)
        self.im.startInvitation(petname, code, transports)
        return "invitation for %s started" % petname

    def send_message(self, cid, payload):
        c = channel.OutboundChannel(self.db, cid)
        return c.send(payload)

    def get_transports(self):
        # returns dict of tid->pubrecord . These will be individualized
        # before delivery to the peer.
        c = self.db.cursor()
        transports = {}
        c.execute("SELECT * FROM mailboxes")
        for row in c.fetchall():
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
        c = self.db.cursor()
        c.execute("SELECT * FROM addressbook")
        for row in c.fetchall():
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

class OFF:
    def control_relayConnected(self):
        return bool(self.connection)

    def control_getProfileName(self):
        c = self.db.cursor()
        c.execute("SELECT `name` FROM `client_profile`")
        return c.fetchone()[0]

    def control_setProfileName(self, name):
        c = self.db.cursor()
        c.execute("UPDATE `client_profile` SET `name`=?", (name,))
        self.db.commit()

    def control_getProfileIcon(self):
        c = self.db.cursor()
        c.execute("SELECT `icon_data` FROM `client_profile`")
        return c.fetchone()[0]

    def control_setProfileIcon(self, icon_data):
        c = self.db.cursor()
        c.execute("UPDATE `client_profile` SET `icon_data`=?", (icon_data,))
        self.db.commit()

    def control_sendMessage(self, args):
        #print "SENDMESSAGE", args
        msg_to = str(args["to"])
        msg_body = str(args["message"])
        self.send_message_to_relay("send", msg_to, msg_body)

    def control_getAddressBookJSONable(self):
        c = self.db.cursor()
        c.execute("SELECT `petname`,`selfname`,`icon_data`,`their_pubkey`"
                  " FROM `addressbook`"
                  " ORDER BY `petname` ASC")
        data = [{ "petname": str(row[0]),
                  "selfname": str(row[1]),
                  "icon_data": str(row[2]),
                  "their_pubkey": str(row[3]),
                  }
                for row in c.fetchall()]
        return data
    def control_deleteAddressBookEntry(self, petname):
        c = self.db.cursor()
        c.execute("DELETE FROM `addressbook` WHERE `petname`=?", (petname,))
        self.db.commit()
        self.notify("address-book-changed", None)

    def control_subscribe_events(self, subscriber):
        self.subscribers[subscriber] = None
    def control_unsubscribe_events(self, subscriber):
        self.subscribers.pop(subscriber, None)
    def notify(self, what, data):
        for s in self.subscribers:
            msg = json.dumps({"message": data})
            s.event(what, msg) # TODO: eventual-send
