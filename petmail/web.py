import os, json
from twisted.application import service, strports
from twisted.web import server, static, resource, http
from twisted.python import log
from .util import make_nonce, equal

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
    def __init__(self, access_token, db, client):
        SSEResource.__init__(self)
        self.access_token = access_token
        self.db = db
        self.client = client

    def buildProtocol(self, request):
        return ClientEventsProtocol(self.db, self.client, request)

    def render_GET(self, request):
        token = request.args["token"][0]
        if not equal(token, self.access_token):
            request.setHeader("content-type", "text/plain")
            return ("Sorry, this session token is expired,"
                    " please run 'petmail open' again\n")
        return SSEResource.render_GET(self, request)

class CommandError(Exception):
    def __init__(self, msg):
        self.msg = msg

handlers = {}

class BaseHandler(resource.Resource):
    def __init__(self, db, client, payload):
        resource.Resource.__init__(self)
        self.db = db
        self.client = client
        self.payload = payload
    def render_POST(self, request):
        try:
            results = self.handle(self.payload.get("args", {}))
            if isinstance(results, str):
                data = {"ok": True, "text": results}
            else:
                data = results
        except CommandError, e:
            request.setResponseCode(http.BAD_REQUEST, "command error")
            data = {"err": e.msg}
        return json.dumps(data)

class Sample(BaseHandler):
    def handle(self, payload):
        self.client._debug_sample = payload["data"]
        if payload.get("error"):
            raise CommandError("sample error text")
        if payload.get("server-error"):
            raise ValueError("sample server error")
        if payload.get("success-object"):
            return {"ok": "sample ok object"}
        return "sample ok"
handlers["sample"] = Sample

class Invite(BaseHandler):
    def handle(self, payload):
        self.client.command_invite(payload["petname"], payload["code"])
        return "ok"
handlers["invite"] = Invite

class API(resource.Resource):
    def __init__(self, access_token, db, client):
        resource.Resource.__init__(self)
        self.access_token = access_token
        self.db = db
        self.client = client

    def getChild(self, path, request):
        # everything requires a token, check it here
        payload = json.loads(request.content.read())
        if not equal(payload["token"], self.access_token):
            request.setResponseCode(http.UNAUTHORIZED, "bad token")
            return "Invalid token"
        rclass = handlers.get(path)
        if not rclass:
            request.setResponseCode(http.NOT_FOUND, "unknown method")
            return "Unknown method"
        r = rclass(self.db, self.client, payload)
        return r

class OFF:
    def render_POST(self, request):
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

class ControlOpener(resource.Resource):
    def __init__(self, db, access_token):
        resource.Resource.__init__(self)
        self.db = db
        self.access_token = access_token

    def render_GET(self, request):
        request.setHeader("content-type", "text/plain")
        if "opener-token" not in request.args:
            return "Please use 'petmail open' to get to the control panel\n"
        opener_token = request.args["opener-token"][0]
        c = self.db.cursor()
        c.execute("SELECT token FROM webapi_opener_tokens")
        tokens = [str(row[0]) for row in c.fetchall()]
        if opener_token not in tokens:
            return ("Sorry, that opener-token is expired or invalid,"
                    " please run 'petmail open' again\n")
        # good opener-token, single-use
        c.execute("DELETE FROM webapi_opener_tokens WHERE token=?",
                  (opener_token,))
        self.db.commit()

        request.setHeader("content-type", "text/html")
        return read_media("login.html") % self.access_token

class Control(resource.Resource):
    def __init__(self, access_token):
        resource.Resource.__init__(self)
        self.access_token = access_token

    def render_POST(self, request):
        token = request.args["token"][0]
        if not equal(token, self.access_token):
            request.setHeader("content-type", "text/plain")
            return ("Sorry, this access token is expired,"
                    " please run 'petmail open' again\n")
        return read_media("control.html") % {"token": token}


class Root(resource.Resource):
    # child_FOO is a nevow thing, not a twisted.web.resource thing
    def __init__(self):
        resource.Resource.__init__(self)
        self.putChild("", static.Data("Hello\n", "text/plain"))
        self.putChild("media", static.File(MEDIA_DIRNAME))

class WebPort(service.MultiService):
    def __init__(self, basedir, node, db):
        service.MultiService.__init__(self)
        self.basedir = basedir
        self.node = node

        root = Root()

        if node.client:
            # Access tokens last as long as the node is running: they are
            # cleared at each startup. It's important to clear these before
            # the web port starts listening, to avoid a race with 'petmail
            # open' adding a new nonce
            cursor = db.cursor()
            cursor.execute("DELETE FROM `webapi_access_tokens`")
            cursor.execute("DELETE FROM `webapi_opener_tokens`")

            # The access token will be used by both CLI commands (which read
            # it directly from the database) and the frontend web client
            # (which fetches it from /open-control with a single-use opener
            # token).
            access_token = make_nonce()
            cursor.execute("INSERT INTO `webapi_access_tokens` VALUES (?)",
                           (access_token,))
            db.commit()

            root.putChild("open-control", ControlOpener(db, access_token))
            root.putChild("control", Control(access_token))

            api = resource.Resource() # /api
            api_v1 = API(access_token, db, node.client) # /api/v1
            client_events = Events(access_token, db, node.client) # /api/v1/events
            api_v1.putChild("events", client_events)
            api.putChild("v1", api_v1)
            root.putChild("api", api)

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
