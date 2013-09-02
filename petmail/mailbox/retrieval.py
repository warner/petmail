from twisted.application import service, internet
from twisted.web import client
from twisted.python import log
from ..eventual import eventually

class LocalRetriever(service.MultiService):
    """I can 'retrieve' messages from an in-process HTTPMailboxServer. This
    server listens on the same web server that hosts our node's API and
    frontend. I am used by nodes which have external IP addresses, or for
    internal/development testing. I am also used for the admin/provisioning
    channel of a public mailbox server (when customers to talk to the server
    itself, as opposed to remote senders to delivering messages to
    customers).
    """
    def __init__(self, tid, descriptor, client, db, server):
        service.MultiService.__init__(self)
        self.tid = tid
        self.client = client
        server.register_local_transport_handler(self.message_handler)

    def message_handler(self, msgC):
        self.client.message_received(self.tid, msgC)

ENABLE_POLLING = False

class HTTPRetriever(service.MultiService):
    """I provide a retriever that fetches messages from an HTTP server
    defined in mailbox.server.RetrievalResource. I can either poll or use
    Server-Sent Events to discover new messages. Once I've retrieved them, I
    delete them from the server. I handle transport encryption to hide the
    message contents as I grab them."""
    def __init__(self, tid, descriptor, client, db):
        service.MultiService.__init__(self)
        self.tid = tid
        self.descriptor = descriptor
        self.client = client
        self.db = db
        self.ts = internet.TimerService(10*60, self.poll)
        if ENABLE_POLLING:
            self.ts.setServiceParent(self)

    def poll(self):
        # TODO: transport security, SSE, overlap prevention, deletion (server
        # currently serves each message just once)
        d = client.getPage(self.descriptor["url"])
        def _done(page):
            # the response is a single msgC, or an empty string
            if page:
                self.client.message_received(self.tid, page)
                eventually(self.poll) # repeat until drained
        d.addCallback(_done)
        d.addErrback(log.err)
