import time, struct
from twisted.application import service, internet
from twisted.web import client
from twisted.python import log
from nacl.secret import SecretBox
from nacl.public import PrivateKey, PublicKey, Box
from ..eventual import eventually
from ..util import equal, remove_prefix

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

def encrypt_list_request(serverpubkey, TID, now=None, offset=0, tmppriv=None):
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
    return req

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
        self.got_msgC = got_msgC
        self.ts = internet.TimerService(10*60, self.poll)
        if ENABLE_POLLING:
            self.ts.setServiceParent(self)

    def poll(self):
        # TODO: transport security, SSE, overlap prevention, deletion (server
        # currently serves each message just once)
        d = client.getPage(self.descriptor["url"], method="POST")
        def _done(page):
            # the response is a single msgC, or an empty string
            if page:
                self.got_msgC(page)
                eventually(self.poll) # repeat until drained
        d.addCallback(_done)
        d.addErrback(log.err)
