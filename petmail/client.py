import os.path, weakref, json
from twisted.application import service
from . import invitation
from .rendezvous import localdir

class Client(service.MultiService):
    def __init__(self, db, basedir):
        service.MultiService.__init__(self)
        self.db = db
        c = self.db.cursor()
        c.execute("SELECT `inbox_location` FROM `client_config`")
        inbox_location = str(c.fetchone()[0])
        print "INBOX", inbox_location

        self.subscribers = weakref.WeakKeyDictionary()

        c.execute("SELECT `pubkey` FROM `client_config`");
        self.vk_s = str(c.fetchone()[0])

        self.im = invitation.InvitationManager(db, self)
        self.im.setServiceParent(self)
        rdir = os.path.join(os.path.dirname(basedir), ".rendezvous")
        rs_localdir = localdir.LocalDirectoryRendezvousClient(rdir)
        self.im.addRendezvousService(rs_localdir)

    def command_invite(self, petname, code):
        my_transport_record = {}
        my_private_transport_record = {}
        self.im.startInvitation(petname, code, my_transport_record,
                                my_private_transport_record)

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
        print "SENDMESSAGE", args
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
