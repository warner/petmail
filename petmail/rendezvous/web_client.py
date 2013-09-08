from twisted.python import log, failure
from twisted.application import service, internet
from twisted.web import client
from ..invitation import VALID_INVITEID, VALID_MESSAGE
from .. import eventsource

# this is allowed to do seen-message-stripping as an optimization, but is not
# required to do so. It is not required to check version numbers ("r0:") or
# signatures.

class Marker:
    pass

class HTTPRendezvousClient(service.MultiService):
    """I talk to a remote HTTP-based rendezvous server."""
    # start with simple polling. TODO: EventSourceProtocol
    enable_polling = True # disabled by some unit tests
    polling_interval = 2

    def __init__(self, baseurl):
        service.MultiService.__init__(self)
        self.baseurl = baseurl
        assert self.baseurl.endswith("/")
        self.subscriptions = set()
        self.pending_requests = set()
        self.pending_sends = set()

    def is_idle(self):
        if self.pending_requests:
            return False
        if self.pending_sends:
            return False
        return True

    def subscribe(self, channelID):
        assert VALID_INVITEID.search(channelID), channelID
        self.subscriptions.add(channelID)
        if len(self.subscriptions) == 1 and self.enable_polling:
            self.ts = internet.TimerService(self.polling_interval, self.poll)
            self.ts.setServiceParent(self)

    def unsubscribe(self, channelID):
        self.subscriptions.remove(channelID)
        if not self.subscriptions and self.enable_polling:
            self.ts.disownServiceParent()
            del self.ts

    def poll(self):
        #print "entering poll"
        # we may unsubscribe while in the loop, so copy self.subscriptions
        for channelID in list(self.subscriptions):
            self.pollChannel(channelID)

    def pollChannel(self, channelID):
        if channelID in self.pending_requests:
            return
        url = self.baseurl + "relay/" + channelID
        self.pending_requests.add(channelID)

        # create a watcher for this channel
        def _handler(name, data):
            if name == "data":
                # we expect the value to start with "r0:" followed by a
                # hex-encoded signed message
                self.parent.messagesReceived(channelID, set([data]))
        d = eventsource.get_events(url, _handler)
        # If the relay can do EventSource, the handler will be fed with
        # incoming events, and the Deferred won't fire until they hang up. If
        # it can't, get_events() will do a regular GET, and the handler will
        # be fed, and the Deferred will fire. If an error occurs, it will
        # fire with a Failure.

        # so if we're still subscribed when the Deferred fires, we should
        # reschedule for later.
        d.addBoth(self._http_done, channelID)

    def _http_done(self, res, channelID):
        self.pending_requests.remove(channelID)
        if isinstance(res, failure.Failure):
            log.msg("HTTP error polling %s: %s" % (channelID, res))
        # if we're still subscribed, the poller will trigger again later. no
        # need to do anything now.

    def send(self, channelID, msg):
        assert isinstance(channelID, str)
        assert channelID in self.subscriptions
        assert VALID_INVITEID.search(channelID), channelID
        assert VALID_MESSAGE.search(msg), msg

        url = self.baseurl + "relay/" + channelID
        m = Marker()
        self.pending_sends.add(m)
        d = client.getPage(url, method="POST", postdata=msg)
        def _done(res):
            self.pending_sends.remove(m)
            return res
        d.addBoth(_done)
        def _sent(resp):
            log.msg("HTTP POST to %s happy: %s" % (channelID, resp))
        def _err(f):
            log.err(f)
        d.addCallbacks(_sent, _err)
        return d
