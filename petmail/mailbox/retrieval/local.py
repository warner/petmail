
# I know how to "retrieve" messages from an in-process HTTP server, listening
# on the same web server that hosts our node's API and frontend. I am used by
# nodes which have external IP addresses, or for internal/development
# testing.

from twisted.application import service

# reach up to the Client, find the web interface, attach a
# ..server.http_server.ServerResource to "/inbox" (if one isn't already
# there). Find/create our Transport, subscribe to it, so that inbound
# messages are delivered here to us. In this mode, there is no
# RetrievalResource.

class LocalRetriever(service.MultiService):
    """I can 'retrieve' messages from a LocalServer"""
    def __init__(self, tid, descriptor, client, db, server):
        service.MultiService.__init__(self)
        self.tid = tid
        self.client = client
        server.register_local_transport_handler(self.message_handler)

    def message_handler(self, msgC):
        self.client.message_received(self.tid, msgC)
