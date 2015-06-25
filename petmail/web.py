import os, json, collections
from twisted.application import service, strports
from twisted.web import server, static, resource, http
from .database import Notice
from .util import equal, make_nonce
from .errors import CommandError

MEDIA_DIRNAME = os.path.join(os.path.dirname(__file__), "media")

def read_media(fn):
    f = open(os.path.join(MEDIA_DIRNAME,fn), "rb")
    #data = f.read().decode("utf-8")
    data = f.read()
    f.close()
    return data

class EventsProtocol:
    def __init__(self, request):
        self.request = request

    def sendComment(self, comment):
        # this is ignored by clients, but can keep the connection open in the
        # face of firewall/NAT timeouts. It also helps unit tests, since
        # apparently twisted.web.client.Agent doesn't consider the connection
        # to be established until it sees the first byte of the reponse body.
        self.request.write(": %s\n\n" % comment)

    def sendEvent(self, data, name=None, id=None, retry=None):
        if name:
            self.request.write("event: %s\n" % name.encode("utf-8"))
            # e.g. if name=foo, then the client web page should do:
            # (new EventSource(url)).addEventListener("foo", handlerfunc)
            # Note that this basically defaults to "message".
        if id:
            self.request.write("id: %s\n" % id.encode("utf-8"))
        if retry:
            self.request.write("retry: %d\n" % retry) # milliseconds
        for line in data.splitlines():
            self.request.write("data: %s\n" % line.encode("utf-8"))
        self.request.write("\n")

    def stop(self):
        self.request.finish()

# note: no versions of IE (including the current IE11) support EventSource

class EventChannel(resource.Resource):
    def __init__(self, db, agent, dispatcher, esid):
        resource.Resource.__init__(self)
        self.db = db
        self.agent = agent
        self.dispatcher = dispatcher
        self.esid = esid
        # this maps topic to set of (table,notifierfunc)
        self.db_subscriptions = collections.defaultdict(set)

    # subclasses must define render_event(), which accepts a Notice and
    # returns a JSON-serializable object

    def render_GET(self, request):
        if "text/event-stream" not in (request.getHeader("accept") or ""):
            request.setResponseCode(http.BAD_REQUEST, "Must use EventSource")
            return "Must use EventSource (Content-Type: text/event-stream)"
        request.setHeader("content-type", "text/event-stream")
        self.events_protocol = EventsProtocol(request)
        request.notifyFinish().addErrback(self._shutdown)
        # tell the frontend it's safe to subscribe
        self.events_protocol.sendEvent(json.dumps({"type": "ready"}))
        return server.NOT_DONE_YET

    def _shutdown(self, _):
        for tns in self.db_subscriptions.values():
            for (table, notifier) in tns:
                self.db.unsubscribe(table, notifier)
        self.dispatcher.channel_closed(self.esid)

    def do_db_subscribe(self, topic, table, notifier):
        self.db.subscribe(table, notifier)
        self.db_subscriptions[topic].add((table, notifier))

    def do_catchup(self, table, notifier):
        c = self.db.execute("SELECT * FROM `%s`" % table)
        for row in c.fetchall():
            notifier(Notice(table, "insert", row["id"], row,
                            {"catchup": True}))

    def subscribe(self, topic, catchup):
        if topic == "addressbook":
            self.do_db_subscribe(topic, "addressbook",
                                 self.deliver_addressbook_event)
            if catchup:
                self.do_catchup("addressbook", self.deliver_addressbook_event)

        elif topic == "messages":
            self.do_db_subscribe(topic, "inbound_messages",
                                 self.deliver_inbound_message_event)
            self.do_db_subscribe(topic, "outbound_messages",
                                 self.deliver_outbound_message_event)
            if catchup:
                self.do_catchup("inbound_messages",
                                self.deliver_inbound_message_event)
                self.do_catchup("outbound_messages",
                                self.deliver_outbound_message_event)

        elif topic == "mailboxes":
            self.do_db_subscribe(topic, "mailboxes",
                                 self.deliver_mailbox_event)
            if catchup:
                self.do_catchup("mailboxes", self.deliver_mailbox_event)
                # send this after any DB row, so the frontend doesn't
                # show and then immediately hide the warning box
                c = self.db.execute("SELECT * FROM agent_profile")
                row = c.fetchone()
                adv_local = bool(row["advertise_local_mailbox"])
                local_url = None
                if adv_local:
                    local_url = self.agent.mailbox_server.baseurl # XXX
                self.deliver_local_mailbox_event(adv_local, local_url)

        else:
            raise ValueError("unknown subscription topic %s" % topic)

    def unsubscribe(self, topic):
        if topic in self.db_subscriptions:
            for (table, notifier) in self.db_subscriptions[topic]:
                self.db.unsubscribe(table, notifier)
            del self.db_subscriptions[topic]

    def some_keys(self, value, keys=None):
        if value is None:
            return None
        if keys is None:
            return value
        return dict([(key, value[key]) for key in keys])

    def deliver_addressbook_event(self, notice):
        new_value = self.some_keys(notice.new_value,
                                   ["id", "petname", "acked",
                                    "invitation_state", "invitation_code",
                                    "accept_mailbox_offer",
                                    ])
        if notice.new_value:
            row = self.db.execute("SELECT * FROM mailboxes WHERE cid=?",
                                (new_value["id"],)).fetchone()
            if row:
                new_value["mailbox_id"] = row["id"]
            they_offered = json.loads(notice.new_value["latest_offered_mailbox_json"] or "null")
            new_value["they_offered_mailbox"] = bool(they_offered)
        self.deliver_event(notice, new_value, "addressbook")

    def deliver_inbound_message_event(self, notice):
        new_value = self.some_keys(notice.new_value,
                                   ["id", "cid", "when_received", "seqnum",
                                    "payload_json"])
        if new_value:
            c = self.db.execute("SELECT petname FROM addressbook WHERE id=?",
                                (new_value["cid"],))
            new_value["petname"] = c.fetchone()["petname"]
        self.deliver_event(notice, new_value, "inbound-messages")

    def deliver_outbound_message_event(self, notice):
        new_value = self.some_keys(notice.new_value,
                                   ["id", "cid", "when_sent", "payload_json"])
        if new_value:
            c = self.db.execute("SELECT petname FROM addressbook WHERE id=?",
                                (new_value["cid"],))
            new_value["petname"] = c.fetchone()["petname"]
        self.deliver_event(notice, new_value, "outbound-messages")

    def deliver_mailbox_event(self, notice):
        new_value = self.some_keys(notice.new_value,
                                   ["id", "cid", "mailbox_record_json"])
        self.deliver_event(notice, new_value, "mailboxes")

    def deliver_local_mailbox_event(self, adv_local, local_url):
        data = json.dumps({ "type": "advertise_local_mailbox",
                            "adv_local": adv_local,
                            "local_url": local_url })
        self.events_protocol.sendEvent(data)

    def deliver_event(self, notice, new_value, event_type):
        data = json.dumps({ "type": event_type,
                            "action": notice.action,
                            "id": notice.id,
                            "new_value": new_value,
                            "tags": notice.tags,
                            })
        self.events_protocol.sendEvent(data)

class EventChannelDispatcher(resource.Resource):
    def __init__(self, db, agent):
        resource.Resource.__init__(self)
        self.db = db
        self.agent = agent
        self.event_channels = {}
        self.unclaimed_event_channels = set()
        # We keep unclaimed EventChannels alive until a timeout. We keep
        # claimed EventChannels alive until they tell us they're done.

    def add_event_channel(self):
        esid = make_nonce()
        self.event_channels[esid] = EventChannel(self.db, self.agent,
                                                 self, esid)
        self.unclaimed_event_channels.add(esid)
        # TODO: timeout
        return esid

    def channel_closed(self, esid):
        # called by the EventChannel when it hears request.notifyFinish,
        # which means the client has disconnected
        self.event_channels.pop(esid)
        self.unclaimed_event_channels.discard(esid) # just in case

    def subscribe(self, esid, topic, catchup):
        self.event_channels[esid].subscribe(topic, catchup)

    def unsubscribe(self, esid, topic):
        self.event_channels[esid].unsubscribe(topic)

    def getChild(self, esid, request):
        try:
            # esid tokens are single-use
            self.unclaimed_event_channels.remove(esid) # can raise KeyError
            return self.event_channels[esid]
        except KeyError:
            return resource.ErrorPage(http.UNAUTHORIZED, "bad esid",
                                      "Invalid esid")


handlers = {}

class BaseHandler(resource.Resource):
    def __init__(self, db, agent, event_dispatcher, payload):
        resource.Resource.__init__(self)
        self.db = db
        self.agent = agent
        self.event_dispatcher = event_dispatcher
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
        maybe_code = payload.get("code")
        if maybe_code:
            maybe_code = str(maybe_code) # might be None
        reqid = payload.get("reqid")
        accept_mailbox_offer = payload.get("accept_mailbox", False)
        offer_mailbox = payload.get("offer_mailbox", False)
        return self.agent.command_invite(petname, maybe_code, reqid,
                                         offer_mailbox=offer_mailbox,
                                         accept_mailbox_offer=accept_mailbox_offer)
handlers["invite"] = Invite

class AcceptMailboxOffer(BaseHandler):
    """Set/clear the 'will accept a mailbox offer' flag for an existing CID."""
    def handle(self, payload):
        cid = int(payload["cid"])
        accept = bool(payload["accept"])
        return self.agent.command_control_accept_mailbox_offer(cid, accept)
handlers["accept-mailbox"] = AcceptMailboxOffer

class ListAddressbook(BaseHandler):
    def handle(self, payload):
        return {"ok": "ok",
                "addressbook": self.agent.command_list_addressbook()}
handlers["list-addressbook"] = ListAddressbook

class SetPetname(BaseHandler):
    def handle(self, payload):
        self.agent.command_set_petname(payload["cid"], payload["petname"]);
        return {"ok": "ok"}
handlers["set-petname"] = SetPetname

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

class EventChannelCreate(BaseHandler):
    def handle(self, payload):
        esid = self.event_dispatcher.add_event_channel()
        return {"ok": "ok", "esid": esid}
handlers["eventchannel-create"] = EventChannelCreate

class EventChannelSubscribe(BaseHandler):
    def handle(self, payload):
        self.event_dispatcher.subscribe(str(payload["esid"]),
                                        str(payload["topic"]),
                                        payload.get("catchup", False))
        return {"ok": "ok"}
handlers["eventchannel-subscribe"] = EventChannelSubscribe

class EventChannelUnsubscribe(BaseHandler):
    def handle(self, payload):
        self.event_dispatcher.unsubscribe(str(payload["esid"]),
                                          str(payload["topic"]))
        return {"ok": "ok"}
handlers["eventchannel-unsubscribe"] = EventChannelUnsubscribe


class API(resource.Resource):
    def __init__(self, access_token, db, agent):
        resource.Resource.__init__(self)
        self.access_token = access_token
        self.db = db
        self.agent = agent
        self.event_dispatcher = EventChannelDispatcher(db, agent)

    def getChild(self, path, request):
        if path == "events":
            # Server-Sent Events use a GET with a use-once URL, not a token
            return self.event_dispatcher
        # everything else requires a token, check it here
        payload = json.loads(request.content.read())
        if not equal(payload["token"], self.access_token):
            return resource.ErrorPage(http.UNAUTHORIZED, "bad token",
                                      "Invalid token")
        rclass = handlers.get(path)
        if not rclass:
            return resource.ErrorPage(http.NOT_FOUND, "unknown method",
                                      "Unknown method")
        r = rclass(self.db, self.agent, self.event_dispatcher, payload)
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
        self.root.putChild("api", API(token, db, agent))

    def get_root(self):
        return self.root
