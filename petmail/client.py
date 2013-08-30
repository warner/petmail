import os.path, weakref, json
from twisted.application import service
from nacl.signing import SigningKey
from nacl.encoding import HexEncoder as Hex
from . import invitation, rrid
from .rendezvous import localdir
from .errors import CommandError

class Client(service.MultiService):
    def __init__(self, db, basedir):
        service.MultiService.__init__(self)
        self.db = db

        self.subscribers = weakref.WeakKeyDictionary()

        self.mailboxClients = set()
        c = self.db.cursor()
        c.execute("SELECT `private_descriptor` FROM `mailboxes`")
        for row in c.fetchall():
            rc = self.buildRetrievalClient(str(row[0]))
            self.subscribeToMailbox(rc)

        self.im = invitation.InvitationManager(db, self)
        rdir = os.path.join(os.path.dirname(basedir), ".rendezvous")
        rs_localdir = localdir.LocalDirectoryRendezvousClient(rdir)
        self.im.addRendezvousService(rs_localdir)
        self.im.setServiceParent(self)

    def buildRetrievalClient(self, private_descriptor):
        # parse descriptor, import correct module and constructor
        bits = private_descriptor.split(":")
        retrieval_type = bits[0]
        if retrieval_type == "direct-http":
            from .mailbox.retrieval import direct_http
            retrieval_class = direct_http.DirectHTTPMailboxRetrievalClient
        else:
            raise CommandError("unrecognized mailbox-retrieval protocol '%s'"
                               % retrieval_type)
        rc = retrieval_class(private_descriptor, self, self.db)
        return rc

    def subscribeToMailbox(self, rc):
        self.mailboxClients.add(rc)
        # the retrieval client gets to make network connections, etc, as soon
        # as it starts. If we are "running" when we add it as a service
        # child, that happens here.
        rc.setServiceParent(self)

    def command_add_mailbox(self, private_descriptor):
        # make sure we can build it, before committing it to the DB
        rc = self.buildRetrievalClient(private_descriptor)
        c = self.db.cursor()
        c.execute("INSERT INTO mailboxes (private_descriptor) VALUES (?)",
                  (private_descriptor,))
        self.db.commit()
        self.subscribeToMailbox(rc)

    def command_invite(self, petname, code):
        TID_tokenid, TID_privkey, TID_token0 = rrid.create()
        # the mailbox will hold TID_tokenid and TID_privkey, and will tell us
        # TID_token0. TID_privkey will be the same for all customers of the
        # mailbox.
        mailbox = {"descriptor": json.dumps({}), "TID": TID_token0}
        self.im.startInvitation(petname, code, mailbox)
        return "invitation for %s started" % petname

    def command_list_addressbook(self):
        resp = []
        c = self.db.cursor()
        c.execute("SELECT * FROM addressbook")
        for row in c.fetchall():
            entry = {}
            entry["their_verfkey"] = str(row["their_verfkey"])
            entry["their_mailbox_descriptor"] = str(row["their_mailbox_descriptor"])
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
