import os, json
from twisted.application import service, strports
from twisted.web import server, static, resource, http
from twisted.python import log
from .database import Notice
from .util import make_nonce, equal
from .errors import CommandError

MEDIA_DIRNAME = os.path.join(os.path.dirname(__file__), "media")

def read_media(fn):
    f = open(os.path.join(MEDIA_DIRNAME,fn), "rb")
    #data = f.read().decode("utf-8")
    data = f.read()
    f.close()
    return data

class DBEventsProtocol:
    def __init__(self, request, renderer):
        self.request = request
        self.renderer = renderer

    def notify(self, notice):
        # TODO: set name=table and have the control page use exactly one
        # EventSource (add APIs to subscribe/unsubscribe various tables as
        # those panels are displayed). (or just deliver everything always).
        self.sendEvent(json.dumps(self.renderer(notice)))

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

class BaseEvents(resource.Resource):
    def __init__(self, db, client):
        resource.Resource.__init__(self)
        self.db = db
        self.client = client

    def render_GET(self, request):
        request.setHeader("content-type", "text/event-stream")
        p = DBEventsProtocol(request, self.render_event)
        c = self.db.execute("SELECT * FROM `%s`" % self.table)
        for row in c.fetchall():
            p.notify(Notice(self.table, "insert", row["id"], row))
        self.client.subscribe(self.table, p.notify)
        def _done(_):
            self.client.unsubscribe(self.table, p.notify)
        request.notifyFinish().addErrback(_done)
        return server.NOT_DONE_YET

def serialize_row(row):
    return dict([(key, row[key]) for key in row.keys()])

class MessageEvents(BaseEvents):
    table = "inbound_messages"
    def render_event(self, notice):
        return { "action": notice.action,
                 "id": notice.id,
                 "new_value": serialize_row(notice.new_value),
                }

class EventDispatcher(resource.Resource):
    def __init__(self, db, client):
        resource.Resource.__init__(self)
        self.db = db
        self.client = client

    def getChild(self, path, request):
        if path == "messages":
            return MessageEvents(self.db, self.client)
        request.setResponseCode(http.NOT_FOUND, "Unknown Event Type")
        return "Unknown Event Type"

handlers = {}

class BaseHandler(resource.Resource):
    def __init__(self, db, client, payload):
        resource.Resource.__init__(self)
        self.db = db
        self.client = client
        self.payload = payload
    def render_POST(self, request):
        err = None
        try:
            results = self.handle(self.payload.get("args", {}))
            if isinstance(results, (str, unicode)):
                results = {"ok": results}
        except CommandError, e:
            # this is the only way to signal a "known" error
            err = unicode(e.msg)
        if err:
            request.setResponseCode(http.BAD_REQUEST, "command error")
            request.setHeader("content-type", "text/plain; charset=utf-8")
            return err.encode("utf-8")
        assert "ok" in results, (results, type(results))
        request.setResponseCode(http.OK, "OK")
        request.setHeader("content-type", "application/json; charset=utf-8")
        return json.dumps(results).encode("utf-8")

class SampleError(Exception):
    pass

class Sample(BaseHandler):
    def handle(self, payload):
        self.client._debug_sample = payload["data"]
        if payload.get("error"):
            raise CommandError("sample error text")
        if payload.get("server-error"):
            raise SampleError("sample server error")
        if payload.get("success-object"):
            return {"ok": "sample ok object", "otherstuff": "stuff"}
        return "sample ok"
handlers["sample"] = Sample

class Invite(BaseHandler):
    def handle(self, payload):
        petname = unicode(payload["petname"])
        code = str(payload["code"])
        return self.client.command_invite(petname, code)
handlers["invite"] = Invite

class ListAddressbook(BaseHandler):
    def handle(self, payload):
        return {"ok": "ok",
                "addressbook": self.client.command_list_addressbook()}
handlers["list-addressbook"] = ListAddressbook

class AddMailbox(BaseHandler):
    def handle(self, payload):
        self.client.command_add_mailbox(str(payload["descriptor"]))
        return {"ok": "ok"}
handlers["add-mailbox"] = AddMailbox

class EnableLocalMailbox(BaseHandler):
    def handle(self, payload):
        self.client.command_enable_local_mailbox()
        return {"ok": "ok"}
handlers["enable-local-mailbox"] = EnableLocalMailbox

class SendBasic(BaseHandler):
    def handle(self, payload):
        cid = int(payload["cid"])
        message = payload["message"]
        return self.client.command_send_basic_message(cid, message)
handlers["send-basic"] = SendBasic

class FetchMessages(BaseHandler):
    def handle(self, payload):
        return {"ok": "ok",
                "messages": self.client.command_fetch_all_messages()}
handlers["fetch-messages"] = FetchMessages

class API(resource.Resource):
    def __init__(self, access_token, db, client):
        resource.Resource.__init__(self)
        self.access_token = access_token
        self.db = db
        self.client = client

    def getChild(self, path, request):
        # everything requires a token, check it here
        if path == "events":
            # Server-Sent Events use a GET, token must live in queryargs
            if not equal(request.args["token"][0], self.access_token):
                request.setResponseCode(http.UNAUTHORIZED, "bad token")
                return "Invalid token"
            return EventDispatcher(self.db, self.client)
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
        c = self.db.execute("SELECT token FROM webapi_opener_tokens")
        tokens = [str(row[0]) for row in c.fetchall()]
        if opener_token not in tokens:
            return ("Sorry, that opener-token is expired or invalid,"
                    " please run 'petmail open' again\n")
        # good opener-token, single-use
        self.db.execute("DELETE FROM webapi_opener_tokens WHERE token=?",
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
    def __init__(self, basedir, node):
        service.MultiService.__init__(self)
        self.basedir = basedir
        self.node = node

        self.root = root = Root()

        site = server.Site(root)
        webport = str(node.get_node_config("webport"))
        self.port_service = strports.service(webport, site)
        self.port_service.setServiceParent(self)

    def enable_client(self, client, db):
        # Access tokens last as long as the node is running: they are
        # cleared at each startup. It's important to clear these before
        # the web port starts listening, to avoid a race with 'petmail
        # open' adding a new nonce
        db.execute("DELETE FROM `webapi_access_tokens`")
        db.execute("DELETE FROM `webapi_opener_tokens`")

        # The access token will be used by both CLI commands (which read
        # it directly from the database) and the frontend web client
        # (which fetches it from /open-control with a single-use opener
        # token).
        access_token = make_nonce()
        db.execute("INSERT INTO `webapi_access_tokens` VALUES (?)",
                   (access_token,))
        db.commit()

        self.root.putChild("open-control", ControlOpener(db, access_token))
        self.root.putChild("control", Control(access_token))

        api = resource.Resource() # /api
        api_v1 = API(access_token, db, client) # /api/v1
        api.putChild("v1", api_v1)
        self.root.putChild("api", api)

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

    def get_root(self):
        return self.root

    def get_baseurl(self):
        webhost = str(self.node.get_node_config("webhost"))
        assert webhost
        webport = str(self.node.get_node_config("webport"))
        pieces = webport.split(":")
        assert pieces[0] == "tcp"
        assert int(pieces[1]) != 0
        return "http://%s:%d/" % (webhost, int(pieces[1]))
