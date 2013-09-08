from twisted.python import log
from twisted.internet import defer
from twisted.application import service, internet
from twisted.web import client
from ..invitation import VALID_INVITEID, VALID_MESSAGE

# this is allowed to do seen-message-stripping as an optimization, but is not
# required to do so. It is not required to check version numbers ("r0:") or
# signatures.

class HTTPRendezvousClient(service.MultiService):
    """I talk to a remote HTTP-based rendezvous server."""
    # start with simple polling. TODO: EventSourceProtocol
    enable_polling = True # disabled by some unit tests
    polling_interval = 60

    def __init__(self, baseurl):
        service.MultiService.__init__(self)
        self.baseurl = baseurl
        assert self.baseurl.endswith("/")
        self.subscriptions = set()
        self._debug_pending = 0

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
        ds = []
        for channelID in list(self.subscriptions):
            ds.append(self.pollChannel(channelID))
        return defer.DeferredList(ds)

    def pollChannel(self, channelID):
        url = self.baseurl + "relay/" + channelID
        self._debug_pending += 1
        d = client.getPage(url, headers={"accept": "application/json"})
        d.addCallback(self.http_response, channelID)
        d.addErrback(self.http_error, channelID)
        return d

    def http_response(self, data, channelID):
        self._debug_pending -= 1
        # we expect a concatenated list of messages, each of which starts
        # with "r0:" followed by a hex-encoded signed message and a newline
        if not data:
            return
        messages = data.strip().split("\n")
        self.parent.messagesReceived(channelID, set(messages))

    def http_error(self, f, channelID):
        self._debug_pending -= 1
        log.msg("HTTP error polling %s: %s" % (channelID, f))

    def send(self, channelID, msg):
        assert isinstance(channelID, str)
        assert channelID in self.subscriptions
        assert VALID_INVITEID.search(channelID), channelID
        assert VALID_MESSAGE.search(msg), msg

        url = self.baseurl + "relay/" + channelID
        self._debug_pending += 1
        d = client.getPage(url, method="POST", postdata=msg)
        def _done(res):
            self._debug_pending -= 1
            return res
        d.addBoth(_done)
        def _sent(resp):
            log.msg("HTTP POST to %s happy: %s" % (channelID, resp))
        def _err(f):
            log.err(f)
        d.addCallbacks(_sent, _err)
        return d
