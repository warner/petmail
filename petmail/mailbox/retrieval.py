import time, struct
from base64 import urlsafe_b64encode, b64decode
from twisted.application import service
from twisted.internet import defer, protocol
from twisted.web import client
from twisted.python import log, failure
from nacl.secret import SecretBox
from nacl.public import PrivateKey, PublicKey, Box
from ..eventual import eventually, fireEventually
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

def encrypt_list_request(serverpubkey, RT, offset=0, now=None, tmppriv=None):
    if not now:
        now = int(time.time())
    now = now + offset
    if not tmppriv:
        tmppriv = PrivateKey.generate()
    tmppub = tmppriv.public_key.encode()
    boxed0 = Box(tmppriv, PublicKey(serverpubkey)).encrypt(RT, "\x00"*24)
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

class Connector:
    # behave enough like an IConnector to appease ReconnectingClientFactory
    def __init__(self, res):
        self.res = res
    def connect(self):
        self.res._maybeStart()
    def stopConnecting(self):
        self.res._stop_eventsource()

class ReconnectingEventSource(service.MultiService,
                              protocol.ReconnectingClientFactory):
    def __init__(self, baseurl, connection_starting, handler):
        service.MultiService.__init__(self)
        # we don't use any of the basic Factory/ClientFactory methods of
        # this, just the ReconnectingClientFactory.retry, stopTrying, and
        # resetDelay methods.

        self.baseurl = baseurl
        self.connection_starting = connection_starting
        self.handler = handler
        # IService provides self.running, toggled by {start,stop}Service.
        # self.active is toggled by {,de}activate. If both .running and
        # .active are True, then we want to have an outstanding EventSource
        # and will start one if necessary. If either is False, then we don't
        # want one to be outstanding, and will initiate shutdown.
        self.active = False
        self.connector = Connector(self)
        self.es = None # set we have an outstanding EventSource
        self.when_stopped = [] # list of Deferreds

    def isStopped(self):
        return not self.es

    def startService(self):
        service.MultiService.startService(self) # sets self.running
        self._maybeStart()

    def stopService(self):
        # clears self.running
        d = defer.maybeDeferred(service.MultiService.stopService, self)
        d.addCallback(self._maybeStop)
        return d

    def activate(self):
        assert not self.active
        self.active = True
        self._maybeStart()

    def deactivate(self):
        assert self.active
        self.active = False
        return self._maybeStop()

    def _maybeStart(self):
        if not (self.active and self.running):
            return
        self.continueTrying = True
        url = self.connection_starting()
        self.es = EventSource(url, self.handler, self.resetDelay)
        d = self.es.start()
        d.addBoth(self._stopped)

    def _stopped(self, res):
        self.es = None
        # we might have stopped because of a connection error, or because of
        # an intentional shutdown.
        if self.active and self.running:
            # we still want to be connected, so schedule a reconnection
            if isinstance(res, failure.Failure):
                log.err(res)
            self.retry() # will eventually call _maybeStart
            return
        # intentional shutdown
        self.stopTrying()
        for d in self.when_stopped:
            eventually(d.callback, None)
        self.when_stopped = []

    def _stop_eventsource(self):
        if self.es:
            eventually(self.es.cancel)

    def _maybeStop(self, _=None):
        self.stopTrying() # cancels timer, calls _stop_eventsource()
        if not self.es:
            return defer.succeed(None)
        d = defer.Deferred()
        self.when_stopped.append(d)
        return d

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
