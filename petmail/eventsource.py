from twisted.python import log
from twisted.internet import reactor, defer
from twisted.protocols import basic
from twisted.web.client import Agent, ResponseDone
from twisted.web.http_headers import Headers

class EventSourceParser(basic.LineOnlyReceiver):
    delimiter = "\n"

    def __init__(self, handler):
        self.current_field = None
        self.current_lines = []
        self.handler = handler
        self.done_deferred = defer.Deferred()

    def connectionLost(self, why):
        if why.check(ResponseDone):
            why = None
        self.done_deferred.callback(why)

    def dataReceived(self, data):
        # exceptions here aren't being logged properly, and tests will hang
        # rather than halt. I suspect twisted.web._newclient's
        # HTTP11ClientProtocol.dataReceived(), which catches everything and
        # responds with self._giveUp() but doesn't log.err.
        try:
            basic.LineOnlyReceiver.dataReceived(self, data)
        except:
            log.err()
            raise

    def lineReceived(self, line):
        if not line:
            # blank line ends the field
            self.fieldReceived(self.current_field,
                               "\n".join(self.current_lines))
            self.current_field = None
            self.current_lines[:] = []
            return
        if self.current_field is None:
            self.current_field, data = line.split(": ", 1)
            self.current_lines.append(data)
        else:
            self.current_lines.append(line)

    def fieldReceived(self, name, data):
        self.handler(name, data)

# es = EventSource(url, handler)
# d = es.start()
# es.cancel()

class EventSource:
    def __init__(self, url, handler):
        self.url = url
        self.handler = handler
        self.started = False
        self.proto = EventSourceParser(self.handler)

    def start(self):
        assert not self.started, "single-use"
        self.started = True
        a = Agent(reactor)
        d = a.request("GET", self.url,
                      Headers({"accept": ["text/event-stream"]}))
        d.addCallback(self._connected)
        return d

    def _connected(self, resp):
        assert resp.code == 200, resp # TODO: return some error instead
        #if resp.headers.getRawHeaders("content-type") == ["text/event-stream"]:
        resp.deliverBody(self.proto)
        return self.proto.done_deferred

    def cancel(self):
        if not hasattr(self.proto, "transport"):
            log.err("EventSource: cancel() called too early, not connected yet")
            # this should kill it as soon as any data is delivered
            def kill(data):
                raise ValueError("dead")
            self.proto.dataReceived = kill
        try:
            # This is gross and fragile. We need a clean way to stop the
            # client connection. p.transport is a
            # twisted.web._newclient.TransportProxyProducer , and its
            # ._producer is the tcp.Port.
            port = self.proto.transport._producer
            port.loseConnection()
        except AttributeError as e:
            log.err(e, "get_events: unable to stop connection")
            # oh well
