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

def get_events(url, handler):
    p = EventSourceParser(handler)
    a = Agent(reactor)
    d = a.request("GET", url, Headers({"accept": ["text/event-stream"]}))
    def _connected(resp):
        assert resp.code == 200, resp # TODO: return some error instead
        assert resp.headers.getRawHeaders("content-type") == ["text/event-stream"]
        resp.deliverBody(p)
        return p.done_deferred
    d.addCallback(_connected)
    return d
