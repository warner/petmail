from twisted.python import log, failure
from twisted.internet import defer
from twisted.application import service, internet
from twisted.web import client
from ..eventual import eventually
from ..invitation import VALID_INVITEID, VALID_MESSAGE
from .. import eventsource

# this is allowed to do seen-message-stripping as an optimization, but is not
# required to do so. It is not required to check version numbers ("r0:") or
# signatures.

class ChannelWatcher(service.MultiService):
    """I handle a single channel. I subscribe immediately. I live until I am
    unsibscribed and the last pending request or send is retired"""
    def __init__(self, rclient, channelID, url, enable_polling, polling_interval):
        service.MultiService.__init__(self)
        self.rclient = rclient
        self.channelID = channelID
        self.url = url
        self.pending_request = False
        self.pending_send = False
        self.outbound_queue = []
        self.ts = None
        if enable_polling:
            self.ts = internet.TimerService(polling_interval, self.poll)
            self.ts.setServiceParent(self)

    def maybeDisown(self):
        if self.pending_request or self.pending_send:
            return
        assert not self.outbound_queue
        self.disownServiceParent()

    def unsubscribe(self):
        if self.ts:
            self.ts.disownServiceParent() # stop any polling
            del self.ts
        self.maybeDisown()

    def poll(self):
        if self.pending_request:
            return # we're busy, call again later
        self.pending_request = True

        # create a watcher for this channel
        def _handler(name, data):
            if name == "data":
                # we expect the value to start with "r0:" followed by a
                # hex-encoded signed message
                self.rclient.messagesReceived(self.channelID, set([data]))
        d = eventsource.get_events(self.url, _handler)
        # If the relay can do EventSource, the handler will be fed with
        # incoming events, and the Deferred won't fire until they hang up. If
        # it can't, get_events() will do a regular GET, and the handler will
        # be fed, and the Deferred will fire. If an error occurs, it will
        # fire with a Failure.

        # so if we're still subscribed when the Deferred fires, we should
        # reschedule for later.
        d.addBoth(self._http_done)

    def _http_done(self, res):
        self.pending_request = False
        if isinstance(res, failure.Failure):
            log.msg("HTTP error polling %s: %s" % (self.channelID, res))
        # if we're still subscribed, the poller will trigger again later. no
        # need to do anything now.
        self.maybeDisown()

    def send(self, msg):
        d = defer.Deferred()
        self.outbound_queue.append((msg,d))
        self.maybeSend()
        return d # fires when this message is retired

    def maybeSend(self):
        if not self.outbound_queue:
            return
        if self.pending_send:
            return
        self.pending_send = True
        msg,done_deferred = self.outbound_queue.pop(0)
        d = client.getPage(self.url, method="POST", postdata=msg)
        def _sent(resp):
            log.msg("HTTP POST to %s happy: %s" % (self.channelID, resp))
            eventually(done_deferred.callback, resp)
        def _err(f):
            log.err(f)
            eventually(done_deferred.callback, f)
        d.addCallbacks(_sent, _err)
        def _done(_):
            self.pending_send = False
            self.maybeSend()
        d.addBoth(_done)

class HTTPRendezvousClient(service.MultiService):
    """I talk to a remote HTTP-based rendezvous server."""
    # start with simple polling. TODO: EventSourceProtocol
    enable_polling = True # disabled by some unit tests
    polling_interval = 2

    def __init__(self, baseurl):
        service.MultiService.__init__(self)
        self.baseurl = baseurl
        assert self.baseurl.endswith("/")
        self.subscriptions = {}

    def is_idle(self):
        return not list(self)

    def subscribe(self, channelID):
        assert VALID_INVITEID.search(channelID), channelID
        assert channelID not in self.subscriptions
        c = ChannelWatcher(self, channelID,
                           self.baseurl + "relay/" + channelID,
                           self.enable_polling, self.polling_interval)
        self.subscriptions[channelID] = c
        c.setServiceParent(self)

    def messagesReceived(self, channelID, messages):
        if channelID not in self.subscriptions:
            return # too late
        self.parent.messagesReceived(channelID, messages)

    def unsubscribe(self, channelID):
        self.subscriptions[channelID].unsubscribe()
        # they will disconnect themselves when ready

    def poll(self):
        #print "entering poll"
        # we may unsubscribe while in the loop, so copy self.subscriptions
        for c in self.subscriptions.values()[:]:
            c.poll()

    def send(self, channelID, msg):
        assert isinstance(channelID, str)
        assert VALID_INVITEID.search(channelID), channelID
        assert VALID_MESSAGE.search(msg), msg
        return self.subscriptions[channelID].send(msg)
