
# I manage an HTTP mailbox server that can accept messages sent by
# petmail.mailbox.delivery.http . I define a ServerResource which accepts the
# POSTs and delivers their msgA to a Mailbox.

from twisted.application import service
from twisted.web import resource
from nacl.public import PrivateKey, PublicKey, Box
from ..eventual import eventually
from .transport import parseMsgA, parseMsgB
from .. import rrid

# the Mailbox object decrypts msgA to get msgB, decrypts the TID, looks up a
# Transport, then dispatches msgB to the transport

# the Transport queues the message somewhere, maybe on disk.

# an HTTP "RetrievalResource" is used by remote clients to pull their
# messages from the Transport. It offers polling and subscription. The
# corresponding client code lives in mailbox.retrieval.from_http_server .

# when using mailbox.retrieval.direct_http, we don't use a RetrievalResource:
# the direct_http retriever subscribes directly to the Transport.

class ServerResource(resource.Resource):
    """I accept POSTs with msgA."""
    def __init__(self, message_handler):
        resource.Resource.__init__(self)
        self.message_handler = message_handler

    def render_POST(self, request):
        msgA = request.content.read()
        # the sender is allowed to observe the following failures:
        #  unrecognized version prefix ("a0:")
        #  message not boxed to our mailbox pubkey
        # but no others. self.messageReceived() will raise any observable
        # errors, and defer the rest of processing until later
        self.message_handler(msgA)
        return "ok"


class BaseServer(service.MultiService):
    """I am a base Petmail Mailbox Server. I accept messages from clients
    over some sort of transport (perhaps HTTP), identify which transport
    (e.g. recipient) they are aimed at, decrypt the outer msgA, and queue the
    inner msgB. Later, the recipient will come along and collect their
    messages.

    My persistent state includes: my TID private key, a list of registered
    transports (including a TID for each, the message queue, and retrieval
    credential verifiers), and perhaps some replay-prevention state.
    """

    def __init__(self):
        service.MultiService.__init__(self)

class HTTPServer(BaseServer):
    def __init__(self, webroot):
        BaseServer.__init__(self)
        webroot.putChild("inbox", ServerResource(self.handle_msgA))

class LocalServer(HTTPServer):
    """I am a local HTTP-based server, attached to our webapi port. I don't
    persist anything myself, but expect my creator to provide me with our
    persistent state.
    """

    def __init__(self, desc):
        HTTPServer.__init__(self)
        self.TID_privkey = desc["TID_private_key"].decode("hex")
        self.privkey = PrivateKey(desc["transport_privkey"].decode("hex"))
        # The general HTTPServer hosts multiple transports, and needs a
        # mapping from TID to a handler (e.g. a queue and some retrieval
        # credentials). The LocalServer is not shared, so it has exactly one
        # transport.
        self.TID_tokenid = desc["TID_tokenid"]

    def register_handler(self, handler):
        self.handler = handler

    def handle_msgA(self, msgA):
        pubkey1_s, boxed = parseMsgA(msgA)
        msgB = Box(self.privkey, PublicKey(pubkey1_s)).decrypt(boxed)
        # this ends the observable errors
        eventually(self.handle_msgB, msgB)

    def handle_msgB(self, msgB):
        MSTID, msgC = parseMsgB(msgB)
        TID = rrid.decrypt(self.TID_privkey, MSTID)
        if TID != self.TID_tokenid:
            raise KeyError("unrecognized transport identifier")
        self.handler(msgC)

