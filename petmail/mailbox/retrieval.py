import time, struct
from base64 import urlsafe_b64encode, b64decode
from twisted.application import service
from twisted.web import client
from twisted.python import log
from nacl.secret import SecretBox
from nacl.public import PrivateKey, PublicKey, Box
from ..eventual import fireEventually
from ..util import equal, remove_prefix
from ..eventsource import ReconnectingEventSource

class LocalRetriever(service.MultiService):
    """I can 'retrieve' messages from an in-process HTTPMailboxServer. This
    server listens on the same web server that hosts our node's API and
    frontend. I am used by nodes which have external IP addresses, or for
    internal/development testing. I am also used for the admin/provisioning
    channel of a public mailbox server (when customers to talk to the server
    itself, as opposed to remote senders to delivering messages to
    customers).
    """
    def __init__(self, descriptor, got_msgC, server):
        service.MultiService.__init__(self)
        server.register_local_transport_handler(got_msgC)

ENABLE_POLLING = False

# retrieval code

def encrypt_list_request(serverpubkey, RT, offset=0, now=None, tmppriv=None):
    if not now:
        now = int(time.time())
    now = now + offset
    if not tmppriv:
        tmppriv = PrivateKey.generate()
    tmppub = tmppriv.public_key.encode()
    assert len(tmppub) == 32
    nonce = "\x00"*24 # safe because we use a new random keypair each time
    assert len(RT) == 8
    m = struct.pack(">Q8s", now, RT)
    boxed0 = Box(tmppriv, PublicKey(serverpubkey)).encrypt(m, nonce)
    assert boxed0[:24] == nonce
    boxed = boxed0[24:] # we elide the nonce, always 0
    req = tmppub + boxed
    return req, tmppub

class NotListResponseError(Exception):
    pass
class WrongPubkeyError(Exception):
    pass
class NotFetchResponseError(Exception):
    pass
class WrongFetchTokenError(Exception):
    pass

def decrypt_list_entry(boxed, symkey, tmppub):
    sbox = SecretBox(symkey)
    msg = remove_prefix(sbox.decrypt(boxed),
                        "list:", NotListResponseError)
    (got_tmppub, fetch_token, delete_token,
     length) = struct.unpack(">32s32s32sQ", msg)
    if not equal(got_tmppub, tmppub):
        raise WrongPubkeyError
    return fetch_token, delete_token, length

def decrypt_fetch_response(symkey, fetch_token, boxed):
    msg = remove_prefix(SecretBox(symkey).decrypt(boxed),
                        "fetch:", NotFetchResponseError)
    got_fetch_token = msg[:32]
    if not equal(got_fetch_token, fetch_token):
        raise WrongFetchTokenError
    msgC = msg[32:]
    return msgC

class HTTPRetriever(service.MultiService):
    """I provide a retriever that fetches messages from an HTTP server
    defined in mailbox.server.RetrievalResource. I can either poll or use
    Server-Sent Events to discover new messages. Once I've retrieved them, I
    delete them from the server. I handle transport encryption to hide the
    message contents as I grab them."""
    def __init__(self, descriptor, got_msgC):
        service.MultiService.__init__(self)
        self.descriptor = descriptor
        self.baseurl = str(descriptor["baseurl"])
        assert self.baseurl.endswith("/")
        self.server_pubkey = descriptor["retrieval_pubkey"].decode("hex")
        self.symkey = descriptor["retrieval_symkey"].decode("hex")
        self.RT = descriptor["RT"].decode("hex")
        self.got_msgC = got_msgC
        self.clock_offset = 0 # TODO
        self.fetchable = [] # list of (fetch_token, delete_token, length)
        self.source = ReconnectingEventSource(self.baseurl,
                                              self.start_source,
                                              self.handle_SSE)
        self.source.setServiceParent(self)
        self.source.activate()

    def start_source(self):
        # each time we start the EventSource, we must establish a new URL
        req, tmppub = encrypt_list_request(self.server_pubkey, self.RT,
                                           offset=self.clock_offset)
        self.tmppub = tmppub
        self.fetchable = []
        url = self.baseurl + "list?t=%s" % urlsafe_b64encode(req)
        return url

    def handle_SSE(self, name, data):
        if name != "data":
            return
        self.fetchable = [decrypt_list_entry(b64decode(boxed),
                                             self.symkey, self.tmppub)
                          for boxed in data.split()]

        d = self.source.deactivate()
        d.addCallback(self.fetch)
        d.addErrback(log.err)
        def _start_polling_again(_):
            if not self.running:
                return
            return self.source.activate()
        d.addCallback(_start_polling_again)

    def fetch(self, _):
        if not self.running: return
        if not self.fetchable:
            return
        fetch_t, delete_t, length = self.fetchable.pop(0)
        url = self.baseurl + "fetch?t=%s" % urlsafe_b64encode(fetch_t)
        d = client.getPage(url, method="GET")
        def _fetched(page):
            if not self.running: return
            msgC = decrypt_fetch_response(self.symkey, fetch_t, page)
            self.got_msgC(msgC)
        d.addCallback(_fetched)
        def _delete(_):
            if not self.running: return
            url = self.baseurl + "delete?t=%s" % urlsafe_b64encode(delete_t)
            return client.getPage(url, method="POST")
        d.addCallback(_delete)
        def _fetch_more(_):
            if not self.running: return
            return fireEventually().addCallback(self.fetch)
        d.addCallback(_fetch_more)
        return d
