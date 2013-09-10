
# I manage an HTTP mailbox server that can accept messages sent by
# petmail.mailbox.delivery.http . I define a ServerResource which accepts the
# POSTs and delivers their msgA to a Mailbox.

from twisted.application import service
from twisted.web import resource
from nacl.public import PrivateKey, PublicKey, Box
from .. import rrid
from ..eventual import eventually
from ..util import remove_prefix, split_into
from ..netstring import split_netstrings_and_trailer

def parseMsgA(msgA):
    key_and_boxed = remove_prefix(msgA, "a0:")
    pubkey1_s, boxed = split_into(key_and_boxed, [32], True)
    return pubkey1_s, boxed

def parseMsgB(msgB):
    (MSTID,),msgC = split_netstrings_and_trailer(msgB)
    return MSTID, msgC

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

class HTTPMailboxServer(BaseServer):
    """I am a local HTTP-based server, attached to our webapi port. I don't
    persist anything myself, but expect my creator to provide me with our
    persistent state. I can deliver messages to a local transport (endpoints
    inside our same process), or write messages to disk for later retrieval
    by remote clients.
    """

    def __init__(self, web, baseurl, enable_retrieval, desc):
        BaseServer.__init__(self)
        self.baseurl = baseurl
        self.privkey = PrivateKey(desc["transport_privkey"].decode("hex"))
        self.TID_privkey = desc["TID_private_key"].decode("hex")

        # If we feed a local transport, it will have just one TID. If we
        # queue messages for any other transports, they'll each have their
        # own TID and handler (e.g. a queue and some retrieval credentials).
        self.local_TID0 = desc["local_TID0"].decode("hex")
        self.local_TID_tokenid = desc["local_TID_tokenid"].decode("hex")

        # this is how we get messages from senders
        web.get_root().putChild("mailbox", ServerResource(self.handle_msgA))

        if enable_retrieval:
            # add a second resource for clients to retrieve messages
            raise NotImplementedError()

    def get_retrieval_descriptor(self):
        return { "type": "local",
                 "transport_privkey": self.privkey.encode().encode("hex"),
                 "TID_private_key": self.TID_privkey.encode("hex"),
                 "TID": self.local_TID0.encode("hex"),
                 "TID_tokenid": self.local_TID_tokenid.encode("hex"),
                 }

    def get_sender_descriptor(self):
        baseurl = self.baseurl
        assert baseurl.endswith("/")
        pubkey = self.privkey.public_key
        return { "type": "http",
                 "url": baseurl + "mailbox",
                 "transport_pubkey": pubkey.encode().encode("hex"),
                 }

    def register_local_transport_handler(self, handler):
        self.local_transport_handler = handler

    def handle_msgA(self, msgA):
        pubkey1_s, boxed = parseMsgA(msgA)
        msgB = Box(self.privkey, PublicKey(pubkey1_s)).decrypt(boxed)
        # this ends the sender-observable errors
        eventually(self.handle_msgB, msgB)

    def handle_msgB(self, msgB):
        MSTID, msgC = parseMsgB(msgB)
        TID = rrid.decrypt(self.TID_privkey, MSTID)
        if TID == self.local_TID_tokenid:
            self.local_transport_handler(msgC)
        else:
            # TODO: look up registered transports, queue message
            self.signal_unrecognized_TID(TID)

    def signal_unrecognized_TID(self, TID):
        # this can be overridden by unit tests
        raise KeyError("unrecognized transport identifier")

