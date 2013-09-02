from twisted.application import service
from . import database, web

class Node(service.MultiService):
    def __init__(self, basedir, dbfile):
        service.MultiService.__init__(self)
        self.basedir = basedir
        self.dbfile = dbfile

        self.sqlite, self.db = database.get_db(dbfile)
        self.init_webport()
        self.client = None
        c = self.db.cursor()
        c.execute("SELECT name FROM services")
        for (name,) in c.fetchall():
            name = str(name)
            if name == "client":
                self.init_client(self.webroot)
                self.web.enable_client(self.client, self.db)
            else:
                raise ValueError("Unknown service '%s'" % name)

    def startService(self):
        #print "NODE STARTED"
        service.MultiService.startService(self)

    def get_node_config(self, name):
        c = self.db.cursor()
        c.execute("SELECT %s FROM node LIMIT 1" % name)
        (value,) = c.fetchone()
        return value

    def set_node_config(self, name, value):
        c = self.db.cursor()
        c.execute("UPDATE node SET %s=?" % name, (value,))
        self.db.commit()

    def init_webport(self):
        self.web = web.WebPort(self.basedir, self)
        self.web.setServiceParent(self)
        self.webroot = self.web.getRoot()

    def init_client(self, webroot):
        from . import client
        self.client = client.Client(self.db, self.basedir, webroot)
        self.client.setServiceParent(self)
