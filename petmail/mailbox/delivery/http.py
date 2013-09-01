
# I call mailbox.transport to create msgA, then perform an HTTP POST to a
# mailbox server.

from twisted.internet import defer

class OutboundHTTPTransport:
    def __init__(self, db, trecord):
        self.db = db
        self.trecord = trecord

    def send(self, msgC):
        return defer.succeed(None)
