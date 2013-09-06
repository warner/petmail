import json
from twisted.application import service
from . import database, web

class Node(service.MultiService):
    def __init__(self, basedir, dbfile, enable_polling=True):
        service.MultiService.__init__(self)
        self.basedir = basedir
        self.dbfile = dbfile
        self.enable_polling = enable_polling

        self.db = database.make_observable_db(dbfile)
        self.init_webport()
        self.init_mailbox_server()
        self.client = None
        c = self.db.execute("SELECT name FROM services")
        for (name,) in c.fetchall():
            name = str(name)
            if name == "client":
                self.init_client()
                self.web.enable_client(self.client, self.db)
            else:
                raise ValueError("Unknown service '%s'" % name)

    def startService(self):
        #print "NODE STARTED"
        service.MultiService.startService(self)

    def get_node_config(self, name):
        c = self.db.execute("SELECT %s FROM node LIMIT 1" % name)
        (value,) = c.fetchone()
        return value

    def set_node_config(self, name, value):
        self.db.execute("UPDATE node SET %s=?" % name, (value,))
        self.db.commit()

    def init_webport(self):
        self.web = web.WebPort(self.basedir, self)
        self.web.setServiceParent(self)

    def init_mailbox_server(self):
        from .mailbox.server import HTTPMailboxServer
        # TODO: learn/be-told our IP addr/hostname
        c = self.db.execute("SELECT * FROM mailbox_server_config")
        row = c.fetchone()
        s = HTTPMailboxServer(self.web, bool(row["enable_retrieval"]),
                              json.loads(row["private_descriptor_json"]))
        s.setServiceParent(self)
        self.mailbox_server = s

    def init_client(self):
        from . import client
        self.client = client.Client(self.db, self.basedir, self.mailbox_server,
                                    self.enable_polling)
        self.client.setServiceParent(self)
