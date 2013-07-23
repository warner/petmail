import os, json
from twisted.application import service, strports
from twisted.web import server, static, resource, http
from twisted.python import log
from .util import make_nonce

MEDIA_DIRNAME = os.path.join(os.path.dirname(__file__), "media")

def read_media(fn):
    f = open(os.path.join(MEDIA_DIRNAME,fn), "rb")
    #data = f.read().decode("utf-8")
    data = f.read()
    f.close()
    return data

class SSEProtocol:
    def __init__(self, request):
        self.request = request
    def connectionLost(self, f=None):
        pass
    def sendEvent(self, data, name=None, id=None, retry=None):
        if name:
            self.request.write("event: %s\n" % name.encode("utf-8"))
        if id:
            self.request.write("id: %s\n" % id.encode("utf-8"))
        if retry:
            self.request.write("retry: %d\n" % retry) # milliseconds
        for line in data.splitlines():
            self.request.write("data: %s\n" % line.encode("utf-8"))
        self.request.write("\n")
    def loseConnection(self):
        self.request.finish()

class SSEResource(resource.Resource):
    def render_GET(self, request):
        request.setHeader("content-type", "text/event-stream")
        p = self.buildProtocol(request)
        request.notifyFinish().addErrback(p.connectionLost)
        return server.NOT_DONE_YET

    def buildProtocol(self, request):
        return SSEProtocol(request)

class ClientEventsProtocol(SSEProtocol):
    def __init__(self, db, client, request):
        SSEProtocol.__init__(self, request)
        self.db = db
        self.client = client
        client.control_subscribe_events(self)
    def connectionLost(self, f=None):
        self.client.control_unsubscribe_events(self)
    def event(self, what, data):
        self.sendEvent(data, name=what)

class Events(SSEResource):
    def __init__(self, control, db, client):
        SSEResource.__init__(self)
        self.control = control
        self.db = db
        self.client = client

    def buildProtocol(self, request):
        return ClientEventsProtocol(self.db, self.client, request)

    def render_GET(self, request):
        token = request.args["token"][0]
        if token not in self.control.get_tokens():
            request.setHeader("content-type", "text/plain")
            return ("Sorry, this session token is expired,"
                    " please run 'petmail open' again\n")
        return SSEResource.render_GET(self, request)

class API(resource.Resource):
    def __init__(self, control, db, client):
        resource.Resource.__init__(self)
        self.control = control
        self.db = db
        self.client = client

    def render_POST(self, request):
        r = json.loads(request.content.read())
        if not r["token"] in self.control.get_tokens():
            request.setResponseCode(http.UNAUTHORIZED, "bad token")
            return "Invalid token"
        method = str(r["method"])
        c = self.db.cursor()
        data = None
        text = "unknown query"
        if method == "webport":
            c.execute("SELECT `webport` FROM `node`")
            text = c.fetchone()[0]
        elif method == "inbox_location":
            c.execute("SELECT `inbox_location` FROM `client_config`")
            text = c.fetchone()[0]
        elif method == "relay_connected":
            connected = self.client.control_relayConnected()
            if connected:
                text = "connected"
            else:
                text = "not connected"
        elif method == "pubkey":
            c.execute("SELECT `pubkey` FROM `client_config`")
            text = c.fetchone()[0]
        elif method == "profile-set-name":
            self.client.control_setProfileName(str(r["args"]["name"]))
        elif method == "profile-name":
            text = self.client.control_getProfileName()
        elif method == "profile-set-icon":
            self.client.control_setProfileIcon(str(r["args"]["icon-data"]))
            data = {}
        elif method == "profile-get-icon":
            data = {"icon-data": self.client.control_getProfileIcon()}
        elif method == "getOutboundInvitations":
            data = self.client.control_getOutboundInvitationsJSONable()
        elif method == "getAddressBook":
            data = self.client.control_getAddressBookJSONable()
        elif method == "deleteAddressBookEntry":
            self.client.control_deleteAddressBookEntry(str(r["args"]["petname"]))
        elif method == "sendMessage":
            self.client.control_sendMessage(r["args"])
        elif method == "startInvitation":
            self.client.control_startInvitation(r["args"])
        elif method == "sendInvitation":
            data = self.client.control_sendInvitation(str(r["args"]["name"]))
        elif method == "cancelInvitation":
            self.client.control_cancelInvitation(r["args"])
        elif method == "acceptInvitation":
            self.client.control_acceptInvitation(str(r["args"]["name"]),
                                                 str(r["args"]["code"]))
            text = "process started"
        else:
            raise ValueError("Unknown method '%s'" % method)
        if data is not None:
            return json.dumps(data)
        return json.dumps({"text": str(text)})

class Control(resource.Resource):
    def __init__(self, db):
        resource.Resource.__init__(self)
        self.db = db

    def get_tokens(self):
        c = self.db.cursor()
        c.execute("SELECT `token` FROM `webui_access_tokens`")
        return set([str(row[0]) for row in c.fetchall()])

    def render_GET(self, request):
        request.setHeader("content-type", "text/plain")
        if "nonce" not in request.args:
            return "Please use 'petmail open' to get to the control panel\n"
        nonce = request.args["nonce"][0]
        c = self.db.cursor()
        c.execute("SELECT nonce FROM webui_initial_nonces")
        nonces = [str(row[0]) for row in c.fetchall()]
        if nonce not in nonces:
            return ("Sorry, that nonce is expired or invalid,"
                    " please run 'petmail open' again\n")
        # good nonce, single-use
        c.execute("DELETE FROM webui_initial_nonces WHERE nonce=?", (nonce,))
        # this token lasts as long as the node is running: it is cleared at
        # startup
        token = make_nonce()
        c.execute("INSERT INTO `webui_access_tokens` VALUES (?)", (token,))
        self.db.commit()
        request.setHeader("content-type", "text/html")
        return read_media("login.html") % token

    def render_POST(self, request):
        token = request.args["token"][0]
        if token not in self.get_tokens():
            request.setHeader("content-type", "text/plain")
            return ("Sorry, this session token is expired,"
                    " please run 'petmail open' again\n")
        return read_media("control.html") % {"token": token}


class Root(resource.Resource):
    # child_FOO is a nevow thing, not in twisted.web.resource thing
    def __init__(self, db):
        resource.Resource.__init__(self)
        self.putChild("", static.Data("Hello\n", "text/plain"))
        self.putChild("media", static.File(MEDIA_DIRNAME))

class WebPort(service.MultiService):
    def __init__(self, basedir, node, db):
        service.MultiService.__init__(self)
        self.basedir = basedir
        self.node = node
        self.db = db

        root = Root(db)
        if node.client:
            self.db.cursor().execute("DELETE FROM `webui_access_tokens`")
            self.db.commit()
            c = Control(db)
            capi = API(c, db, node.client)
            c.putChild("api", capi)
            client_events = Events(c, db, node.client)
            c.putChild("events", client_events)
            root.putChild("control", c)

        site = server.Site(root)
        webport = str(node.get_node_config("webport"))
        self.port_service = strports.service(webport, site)
        self.port_service.setServiceParent(self)

    def startService(self):
        service.MultiService.startService(self)

        # now update the webport, if we started with port=0 . This is gross.
        webport = str(self.node.get_node_config("webport"))
        pieces = webport.split(":")
        if pieces[0:2] == ["tcp", "0"]:
            d = self.port_service._waitingForPort
            def _ready(port):
                try:
                    got_port = port.getHost().port
                    pieces[1] = str(got_port)
                    new_webport = ":".join(pieces)
                    self.node.set_node_config("webport", new_webport)
                except:
                    log.err()
                return port
            d.addCallback(_ready)
