import os, json, collections
from twisted.application import service, strports
from twisted.web import server, static, resource, http
#from nacl.signing import VerifyKey, BadSignatureError
from nacl.signing import VerifyKey
from nacl.exceptions import BadSignatureError
from .database import Notice
from .util import equal
from .errors import CommandError
from .invitation import VALID_INVITEID, VALID_MESSAGE

MEDIA_DIRNAME = os.path.join(os.path.dirname(__file__), "media")

def read_media(fn):
    f = open(os.path.join(MEDIA_DIRNAME,fn), "rb")
    #data = f.read().decode("utf-8")
    data = f.read()
    f.close()
    return data

class EventsProtocol:
    def __init__(self, request, renderer):
        self.request = request
        self.renderer = renderer

    def notify(self, notice):
        # TODO: set name=table and have the control page use exactly one
        # EventSource (add APIs to subscribe/unsubscribe various tables as
        # those panels are displayed). (or just deliver everything always).
        self.sendEvent(self.renderer(notice))

    def sendComment(self, comment):
        # this is ignored by clients, but can keep the connection open in the
        # face of firewall/NAT timeouts. It also helps unit tests, since
        # apparently twisted.web.client.Agent doesn't consider the connection
        # to be established until it sees the first byte of the reponse body.
        self.request.write(": %s\n\n" % comment)

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

    def stop(self):
        self.request.finish()

class BaseView(resource.Resource):
    def __init__(self, db, agent):
        resource.Resource.__init__(self)
        self.db = db
        self.agent = agent

    # subclasses must define render_event(), which accepts a Notice and
    # returns a JSON-serializable object

    def catchup(self, each):
        c = self.db.execute("SELECT * FROM `%s`" % self.table)
        for row in c.fetchall():
            each(Notice(self.table, "insert", row["id"], row))

    def render_GET(self, request):
        if "text/event-stream" in (request.getHeader("accept") or ""):
            request.setHeader("content-type", "text/event-stream")
            p = EventsProtocol(request, self.render_event)
            self.catchup(p.notify)
            self.db.subscribe(self.table, p.notify)
            def _done(_):
                self.db.unsubscribe(self.table, p.notify)
            request.notifyFinish().addErrback(_done)
            return server.NOT_DONE_YET
        # no event-stream, deliver the non-streaming equivalent
        results = []
        self.catchup(lambda notice: results.append(self.render_event(notice)))
        request.setResponseCode(http.OK, "OK")
        request.setHeader("content-type", "application/json; charset=utf-8")
        return json.dumps(results).encode("utf-8")

def serialize_row(row, keys=None):
    if not row:
        return None
    if not keys:
        keys = row.keys()
    return dict([(key, row[key]) for key in keys])

class MessageView(BaseView):
    table = "inbound_messages"
    def render_event(self, notice):
        new_value = serialize_row(notice.new_value)
        if new_value:
            c = self.db.execute("SELECT petname FROM addressbook WHERE id=?",
                                (notice.new_value["cid"],))
            new_value["petname"] = c.fetchone()["petname"]
        return json.dumps({ "action": notice.action,
                            "id": notice.id,
                            "new_value": new_value,
                            })

class AddressBookView(BaseView):
    table = "addressbook"
    def render_event(self, notice):
        new_value = serialize_row(notice.new_value, ["id", "petname", "acked"])
        return json.dumps({ "action": notice.action,
                            "id": notice.id,
                            "new_value": new_value,
                            })

class BackupScanView(resource.Resource):
    def __init__(self, agent):
        resource.Resource.__init__(self)
        self.agent = agent

    # subclasses must define render_event(), which accepts a Notice and
    # returns a JSON-serializable object

    def render_GET(self, request):
        if "text/event-stream" in (request.getHeader("accept") or ""):
            request.setHeader("content-type", "text/event-stream")
            p = EventsProtocol(request, self.render_event)
            self.agent.subscribe_backup_scan_reporter(p.notify)
            def _done(_):
                self.agent.unsubscribe_backup_scan_reporter(p.notify)
            request.notifyFinish().addErrback(_done)
            return server.NOT_DONE_YET
        return "backup-scan progress only available as an EventStream"

    def render_event(self, notice):
        return json.dumps(notice)

class ViewDispatcher(resource.Resource):
    def __init__(self, db, agent):
        resource.Resource.__init__(self)
        self.db = db
        self.agent = agent

    def getChild(self, path, request):
        if path == "messages":
            return MessageView(self.db, self.agent)
        if path == "addressbook":
            return AddressBookView(self.db, self.agent)
        if path == "backup-scan":
            return BackupScanView(self.agent)
        request.setResponseCode(http.NOT_FOUND, "Unknown Event Type")
        return "Unknown Event Type"

handlers = {}

class BaseHandler(resource.Resource):
    def __init__(self, db, agent, payload):
        resource.Resource.__init__(self)
        self.db = db
        self.agent = agent
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
        self.agent._debug_sample = payload["data"]
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
        return self.agent.command_invite(petname, code)
handlers["invite"] = Invite

class OfferMailbox(BaseHandler):
    def handle(self, payload):
        petname = unicode(payload["petname"])
        return self.agent.command_offer_mailbox(petname)
handlers["offer-mailbox"] = OfferMailbox

class AcceptMailbox(BaseHandler):
    def handle(self, payload):
        petname = unicode(payload["petname"])
        code = str(payload["code"])
        return self.agent.command_accept_mailbox(petname, code)
handlers["accept-mailbox"] = AcceptMailbox

class ListAddressbook(BaseHandler):
    def handle(self, payload):
        return {"ok": "ok",
                "addressbook": self.agent.command_list_addressbook()}
handlers["list-addressbook"] = ListAddressbook

class SendBasic(BaseHandler):
    def handle(self, payload):
        cid = int(payload["cid"])
        message = payload["message"]
        return self.agent.command_send_basic_message(cid, message)
handlers["send-basic"] = SendBasic

class FetchMessages(BaseHandler):
    def handle(self, payload):
        return {"ok": "ok",
                "messages": self.agent.command_fetch_all_messages()}
handlers["fetch-messages"] = FetchMessages

class BackupStartScan(BaseHandler):
    def handle(self, payload):
        return self.agent.command_backup_start_scan()
handlers["start-backup-scan"] = BackupStartScan

class BackupStartHash(BaseHandler):
    def handle(self, payload):
        return self.agent.command_backup_start_hash()
handlers["start-backup-hash"] = BackupStartHash

class BackupStartSchedule(BaseHandler):
    def handle(self, payload):
        return self.agent.command_backup_start_schedule()
handlers["start-backup-schedule"] = BackupStartSchedule

class BackupStartUpload(BaseHandler):
    def handle(self, payload):
        return self.agent.command_backup_start_upload()
handlers["start-backup-upload"] = BackupStartUpload

class MyErrorPage(resource.ErrorPage):
    def __init__(self, code, brief):
        resource.ErrorPage.__init__(self, code, brief, brief)

class API(resource.Resource):
    def __init__(self, access_token, db, agent):
        resource.Resource.__init__(self)
        self.access_token = access_token
        self.db = db
        self.agent = agent

    def getChild(self, path, request):
        # everything requires a token, check it here
        if path == "views":
            # Server-Sent Events use a GET, token must live in queryargs
            if not equal(request.args["token"][0], self.access_token):
                return MyErrorPage(http.UNAUTHORIZED, "bad token")
            return ViewDispatcher(self.db, self.agent)
        payload = json.loads(request.content.read())
        if not equal(payload["token"], self.access_token):
            return MyErrorPage(http.UNAUTHORIZED, "bad token")
        rclass = handlers.get(path)
        if not rclass:
            return MyErrorPage(http.NOT_FOUND, "unknown API method")
        r = rclass(self.db, self.agent, payload)
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


class Channel(resource.Resource):
    def __init__(self, channelid, channels, destroy_messages, subscribers,
                 enable_eventsource=True, reverse_messages=False):
        resource.Resource.__init__(self)
        self.channelid = channelid
        self.channels = channels
        self.destroy_messages = destroy_messages
        self.subscribers = subscribers
        self.enable_eventsource = enable_eventsource
        self._test_reverse_messages = reverse_messages

    def render_POST(self, request):
        channel = self.channels[self.channelid]
        destroy_messages = self.destroy_messages[self.channelid]
        message = request.content.read()
        # reject junk
        if not message.startswith("r0:"):
            request.setResponseCode(http.BAD_REQUEST)
            return "unrecognized rendezvous message prefix"
        if not VALID_MESSAGE.search(message):
            request.setResponseCode(http.BAD_REQUEST)
            return "invalid rendezvous message"
        # ignore dups
        if message in channel:
            return "ignoring duplicate message\n"
        # check signature
        try:
            m = message[len("r0:"):].decode("hex")
            i0 = VerifyKey(self.channelid.decode("hex")).verify(m)
        except BadSignatureError:
            request.setResponseCode(http.BAD_REQUEST)
            return "invalid rendezvous message signature"
        # look for two valid deletion messages
        if i0.startswith("i0:destroy:"):
            destroy_messages.add(i0)
        if len(destroy_messages) >= 2:
            del self.channels[self.channelid]
            del self.destroy_messages[self.channelid]
            for p in self.subscribers[self.channelid]:
                p.stop()
            del self.subscribers[self.channelid]
            return "Destroyed\n"
        channel.append(message)
        for p in self.subscribers[self.channelid]:
            p.notify(message)
        return "OK\n"

    def render_GET(self, request):
        if ("text/event-stream" in (request.getHeader("accept") or "")
            and self.enable_eventsource):
            # EventSource protocol
            request.setHeader("content-type", "text/event-stream")
            p = EventsProtocol(request, lambda m: m)
            p.sendComment("beginning Relay event stream")
            for m in self.channels[self.channelid]:
                p.notify(m)
            self.subscribers[self.channelid].add(p)
            def _done(_):
                self.subscribers[self.channelid].remove(p)
            request.notifyFinish().addErrback(_done)
            return server.NOT_DONE_YET
        if not self.channelid in self.channels:
            return ""
        messages = self.channels[self.channelid]
        if self._test_reverse_messages:
            messages = reversed(messages)
        return "".join(["data: %s\n\n" % msg for msg in messages])

class Relay(resource.Resource):
    enable_eventsource = True # disabled for certain tests
    reverse_messages = False # enabled for certain tests

    def __init__(self):
        resource.Resource.__init__(self)
        self.channels = collections.defaultdict(list)
        self.destroy_messages = collections.defaultdict(set)
        self.subscribers = collections.defaultdict(set)

    def getChild(self, path, request):
        if not VALID_INVITEID.search(path):
            return MyErrorPage(http.BAD_REQUEST, "invalid channel id")
        return Channel(path, self.channels, self.destroy_messages,
                       self.subscribers, self.enable_eventsource,
                       self.reverse_messages)

    def unsubscribe_all(self):
        # for tests
        for eps in self.subscribers.values():
            for ep in eps:
                ep.stop()

class Root(resource.Resource):
    # child_FOO is a nevow thing, not a twisted.web.resource thing
    def __init__(self):
        resource.Resource.__init__(self)
        self.putChild("", static.Data("Hello\n", "text/plain"))
        self.putChild("media", static.File(MEDIA_DIRNAME))

class WebPort(service.MultiService):
    def __init__(self, listenport, access_token):
        service.MultiService.__init__(self)
        self.root = Root()
        site = server.Site(self.root)
        assert listenport != "tcp:0" # must be configured
        self.port_service = strports.service(listenport, site)
        self.port_service.setServiceParent(self)
        self.access_token = access_token

    def enable_agent(self, agent, db):
        token = self.access_token
        self.root.putChild("open-control", ControlOpener(db, token))
        self.root.putChild("control", Control(token))
        api = resource.Resource() # /api
        self.root.putChild("api", api)
        api.putChild("v1", API(token, db, agent)) # /api/v1

    def enable_relay(self):
        self.relay = Relay() # for tests
        self.root.putChild("relay", self.relay)

    def get_root(self):
        return self.root
