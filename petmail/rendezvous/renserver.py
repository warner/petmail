import collections
from twisted.application import service, strports
from twisted.web import resource, server, static

class Channel(resource.Resource):
    def __init__(self, channelid, channels):
        resource.Resource.__init__(self)
        self.channelid = channelid
        self.channels = channels
    def render_POST(self, request):
        message = request.content.read()
        # TODO: check signature
        # TODO: look for two valid deletion messages
        self.channels[self.channelid].append(message)
        return "OK\n"
    def render_GET(self, request):
        if "text/event-stream" in request.headers.get("accept", ""):
            #request.setHeader("content-type", "text/event-stream")
            # TODO: EventSource
            pass
        if not self.channelid in self.channels:
            return ""
        return "\n".join(self.channels[self.channelid])+"\n"

class Relay(resource.Resource):
    def __init__(self):
        resource.Resource.__init__(self)
        self.channels = collections.defaultdict(list)
    def getChild(self, path, request):
        return Channel(path, self.channels)

class Root(resource.Resource):
    # child_FOO is a nevow thing, not a twisted.web.resource thing
    def __init__(self):
        resource.Resource.__init__(self)
        self.putChild("", static.Data("I am a renserver\n", "text/plain"))
        self.putChild("relay", Relay())

class RelayServer(service.MultiService):
    def __init__(self):
        service.MultiService.__init__(self)
        root = Root()
        site = server.Site(root)
        strports.service("tcp:9008", site).setServiceParent(self)


application = service.Application("renserver")
RelayServer().setServiceParent(application)
