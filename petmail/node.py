import json
from twisted.application import service
from . import database, web, util

class Node(service.MultiService):
    def __init__(self, basedir, dbfile):
        service.MultiService.__init__(self)
        self.basedir = basedir
        self.dbfile = dbfile

        self.db = database.make_observable_db(dbfile)
        self.init_webport()
        self.agent = None
        c = self.db.execute("SELECT name FROM services")
        for (name,) in c.fetchall():
            name = str(name)
            if name == "agent":
                self.init_mailbox_server(self.baseurl)
                self.init_agent()
                self.web.enable_agent(self.agent, self.db)
            elif name == "relay":
                self.web.enable_relay()
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
        # Access tokens last as long as the node is running: they are cleared
        # at each startup.
        self.db.execute("DELETE FROM `webapi_access_tokens`")
        self.db.execute("DELETE FROM `webapi_opener_tokens`")
        self.db.commit()

        access_token = util.make_nonce()

        c = self.db.execute("SELECT * FROM node").fetchone()
        self.web = web.WebPort(str(c["listenport"]), access_token)
        self.web.setServiceParent(self)
        self.baseurl = str(c["baseurl"])

        # The access token will be used by both CLI commands (which read it
        # directly from the database) and the frontend web client (which
        # fetches it from /open-control with a single-use opener token).
        # 'petmail start' polls the DB for this token to determine when the
        # node is ready. NOTE: the web server won't actually start listening
        # on the port until startService(), so there's a tiny race here.
        self.db.execute("INSERT INTO `webapi_access_tokens` VALUES (?)",
                        (access_token,))
        self.db.commit()

    def init_mailbox_server(self, baseurl):
        from .mailbox.server import HTTPMailboxServer
        # TODO: learn/be-told our IP addr/hostname
        c = self.db.execute("SELECT * FROM mailbox_server_config")
        row = c.fetchone()
        s = HTTPMailboxServer(self.db, self.web, baseurl,
                              bool(row["enable_retrieval"]),
                              json.loads(row["private_descriptor_json"]))
        s.setServiceParent(self)
        self.mailbox_server = s

    def init_agent(self):
        from . import agent
        self.agent = agent.Agent(self.db, self.basedir, self.mailbox_server)
        self.agent.setServiceParent(self)
