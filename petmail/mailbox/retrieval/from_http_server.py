
# I provide a retriever that fetches messages from an HTTP server defined in
# mailbox.server.RetrievalResource. I can either poll or use Server-Sent
# Events to discover new messages. Once I've retrieved them, I delete them
# from the server. I handle transport encryption to hide the message contents
# as I grab them.

from twisted.application import service, internet
from twisted.web import client
from twisted.python import log
from ...eventual import eventually

ENABLE_POLLING = False

class HTTPRetriever(service.MultiService):
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
