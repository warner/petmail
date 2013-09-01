
# I call mailbox.transport to create msgA, then return it

from twisted.internet import defer
from .common import createMsgA

class LoopbackTransport:
    def __init__(self, db, trecord):
        self.db = db
        self.trecord = trecord

    def send(self, msgC):
        msgA = createMsgA(self.trecord, msgC)
        return defer.succeed(msgA)
