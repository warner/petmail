import time, struct, base64
from twisted.application import service, internet
from twisted.web import client
from twisted.python import log
from nacl.secret import SecretBox
from nacl.public import PrivateKey, PublicKey, Box
from ..eventual import eventually
from ..util import equal, remove_prefix
from ..eventsource import EventSource

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

def encrypt_list_request(serverpubkey, TID, offset=0, now=None, tmppriv=None):
    if not now:
        now = int(time.time())
    now = now + offset
    if not tmppriv:
        tmppriv = PrivateKey.generate()
    tmppub = tmppriv.public_key.encode()
    boxed0 = Box(tmppriv, PublicKey(serverpubkey)).encrypt(TID, "\x00"*24)
    assert boxed0[:24] == "\x00"*24
    boxed = boxed0[24:] # we elide the nonce, always 0
    req = struct.pack(">L32s", now, tmppub) + boxed
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
        self.server_pubkey = descriptor["server_pubkey"].decode("hex")
        self.symkey = descriptor["transport_symkey"].decode("hex")
        self.TID = descriptor["TID"].decode("hex")
        self.got_msgC = got_msgC
        self.clock_offset = 0
        #self.ts = internet.TimerService(10*60, self.poll)
        #if ENABLE_POLLING:
        #    self.ts.setServiceParent(self)

    def connect(self):
        # each time we start the EventSource, we must establish a new URL.
        req, tmppub = encrypt_list_request(self.server_pubkey, self.TID,
                                           offset=self.clock_offset)
        url = self.baseurl + "list?t=%s" % base64.urlsafe_b64encode(req)
        self.es = EventSource(url, self.handle_SSE)
        self.es.start()

    def handle_SSE(self, name, data):
        # TODO: transport security, SSE, overlap prevention, deletion (server
        # currently serves each message just once)
        boxed = data.decode("hex")
        (fetch_token, delete_token,
         length) = decrypt_list_entry(boxed, self.symkey, tmppub)
        url = self.baseurl + "fetch?t=%s" % fetch_token.encode("hex")
        d = client.getPage(url, method="GET")
        def _done(page):
            msgC = decrypt_fetch_response(self.symkey, fetch_token, page)
            self.got_msgC(msgC)
            url = self.baseurl + "delete?t=%s" % delete_token.encode("hex")
            return client.getPage(url, method="POST")
        d.addCallback(_done)
        d.addErrback(log.err)
