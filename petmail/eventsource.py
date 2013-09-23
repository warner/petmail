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

class EventSourceError(Exception):
    pass

# es = EventSource(url, handler)
# d = es.start()
# es.cancel()

class EventSource: # TODO: service.Service
    def __init__(self, url, handler, when_connected=None):
        self.url = url
        self.handler = handler
        self.when_connected = when_connected
        self.started = False
        self.cancelled = False
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
        if resp.code != 200:
            raise EventSourceError("%d: %s" % (resp.code, resp.phrase))
        if self.when_connected:
            self.when_connected()
        #if resp.headers.getRawHeaders("content-type") == ["text/event-stream"]:
        resp.deliverBody(self.proto)
        if self.cancelled:
            self.kill_connection()
        return self.proto.done_deferred

    def cancel(self):
        self.cancelled = True
        if not self.proto.transport:
            # _connected hasn't been called yet, but that self.cancelled
            # should take care of it when the connection is established
            def kill(data):
                # this should kill it as soon as any data is delivered
                raise ValueError("dead")
            self.proto.dataReceived = kill # just in case
            return
        self.kill_connection()

    def kill_connection(self):
        if (hasattr(self.proto.transport, "_producer")
            and self.proto.transport._producer):
            # This is gross and fragile. We need a clean way to stop the
            # client connection. p.transport is a
            # twisted.web._newclient.TransportProxyProducer , and its
            # ._producer is the tcp.Port.
            self.proto.transport._producer.loseConnection()
        else:
            log.err("get_events: unable to stop connection")
            # oh well
            #err = EventSourceError("unable to cancel")
            try:
                self.proto.done_deferred.callback(None)
            except defer.AlreadyCalledError:
                pass
