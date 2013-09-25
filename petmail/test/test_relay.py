from twisted.trial import unittest
from twisted.internet import defer
from twisted.application import service
from twisted.web.client import getPage
from twisted.web.error import Error as WebError
from nacl.signing import SigningKey
from .. import web, util, eventsource
from ..rendezvous import web_client
from .common import NodeRunnerMixin, ShouldFailMixin
from .pollmixin import PollMixin

class Accumulator(service.MultiService):
    def __init__(self):
        service.MultiService.__init__(self)
        self.messages = []
    def messages_received(self, channelID, messages):
        self.messages.append( (channelID, messages) )

class Relay(NodeRunnerMixin, ShouldFailMixin, PollMixin, unittest.TestCase):
    def test_basic(self):
        port = util.allocate_port()
        w = web.WebPort("tcp:%d:interface=127.0.0.1" % port, "token")
        w.enable_relay()
        w.setServiceParent(self.sparent)

    def GET(self, url):
        return getPage(url, method="GET",
                       headers={"accept": "application/json"})
    def POST(self, url, data):
        return getPage(url, method="POST", postdata=data,
                       headers={"accept": "application/json",
                                "content-type": "application/json"})

    def test_channel(self):
        port = util.allocate_port()
        w = web.WebPort("tcp:%d:interface=127.0.0.1" % port, "token")
        w.enable_relay()
        w.setServiceParent(self.sparent)
        baseurl = "http://localhost:%d/" % port
        sk = SigningKey.generate()
        channelid = sk.verify_key.encode().encode("hex")
        url = baseurl + "relay/" + channelid # must be hex
        msg1 = "r0:" + sk.sign("msg1").encode("hex")
        msg2 = "r0:" + sk.sign("msg2").encode("hex")
        destroy1 = "r0:" + sk.sign("i0:destroy:one").encode("hex")
        destroy2 = "r0:" + sk.sign("i0:destroy:two").encode("hex")

        def lines(*messages):
            return "".join(["data: %s\n\n" % msg for msg in messages])

        d = defer.succeed(None)
        d.addCallback(lambda _: self.GET(baseurl))
        d.addCallback(lambda res: self.failUnlessEqual(res, "Hello\n"))
        d.addCallback(lambda _: self.GET(url))
        d.addCallback(lambda res: self.failUnlessEqual(res, ""))

        d.addCallback(lambda _: self.POST(url, msg1))
        d.addCallback(lambda res: self.failUnlessEqual(res, "OK\n"))
        d.addCallback(lambda _: self.GET(url))
        d.addCallback(lambda res: self.failUnlessEqual(res, lines(msg1)))
        # duplicates are dismissed
        d.addCallback(lambda _: self.POST(url, msg1))
        d.addCallback(lambda res: self.failUnlessEqual(res, "ignoring duplicate message\n"))
        d.addCallback(lambda _: self.GET(url))
        d.addCallback(lambda res: self.failUnlessEqual(res, lines(msg1)))

        d.addCallback(lambda _: self.POST(url, msg2))
        d.addCallback(lambda res: self.failUnlessEqual(res, "OK\n"))
        d.addCallback(lambda _: self.GET(url))
        d.addCallback(lambda res: self.failUnlessEqual(res, lines(msg1,msg2)))

        # now test the various error conditions
        # invalid channel
        d.addCallback(lambda _:
                      self.shouldFail(WebError, "400 Bad Request",
                                      "invalid channel id",
                                      self.GET, url+"NOTHEX"))
        d.addCallback(lambda _:
                      self.shouldFail(WebError, "400 Bad Request",
                                      "unrecognized rendezvous message prefix",
                                      self.POST, url, "r1:badversion"))
        d.addCallback(lambda _:
                      self.shouldFail(WebError, "400 Bad Request",
                                      "invalid rendezvous message",
                                      self.POST, url, "r0:NOTHEX"))
        d.addCallback(lambda _:
                      self.shouldFail(WebError, "400 Bad Request",
                                      "invalid rendezvous message signature",
                                      self.POST, url, "r0:d00dbadfeede"))

        # and channel destruction
        d.addCallback(lambda _: self.POST(url, destroy1))
        d.addCallback(lambda res: self.failUnlessEqual(res, "OK\n"))
        d.addCallback(lambda _: self.GET(url))
        d.addCallback(lambda res:
                      self.failUnlessEqual(res, lines(msg1,msg2,destroy1)))
        d.addCallback(lambda _: self.POST(url, destroy2))
        d.addCallback(lambda res: self.failUnlessEqual(res, "Destroyed\n"))
        d.addCallback(lambda _: self.GET(url))
        d.addCallback(lambda res: self.failUnlessEqual(res, ""))

        return d

    def test_events_before(self):
        # deliver a message before subscribing
        port = util.allocate_port()
        w = web.WebPort("tcp:%d:interface=127.0.0.1" % port, "token")
        w.enable_relay()
        w.setServiceParent(self.sparent)
        baseurl = "http://localhost:%d/" % port
        sk = SigningKey.generate()
        channelid = sk.verify_key.encode().encode("hex")
        url = baseurl + "relay/" + channelid # must be hex
        msg1 = "r0:" + sk.sign("msg1").encode("hex")
        msg2 = "r0:" + sk.sign("msg2").encode("hex")
        destroy1 = "r0:" + sk.sign("i0:destroy:one").encode("hex")
        destroy2 = "r0:" + sk.sign("i0:destroy:two").encode("hex")

        fields = []
        def handler(name, data):
            fields.append( (name,data) )
        def check_f(min_fields):
            if len(fields) < min_fields:
                return False
            return True

        client_done = []

        d = defer.succeed(None)
        d.addCallback(lambda _: self.POST(url, msg1))
        def _connect(_):
            d1 = eventsource.EventSource(url, handler).start()
            client_done.append(d1)
        d.addCallback(_connect)

        d.addCallback(lambda _: self.poll(lambda: check_f(2)))
        def _then1(_):
            self.failUnlessEqual(len(fields), 2)
            self.failUnlessEqual(fields[0][0], "") # comment
            self.failUnlessEqual(fields[0][1], "beginning Relay event stream")
            self.failUnlessEqual(fields[1][0], "data")
            self.failUnlessEqual(fields[1][1], msg1)
        d.addCallback(_then1)

        d.addCallback(lambda _: self.POST(url, msg2))

        d.addCallback(lambda _: self.poll(lambda: check_f(3)))
        def _then2(_):
            self.failUnlessEqual(len(fields), 3)
            self.failUnlessEqual(fields[2][0], "data")
            self.failUnlessEqual(fields[2][1], msg2)
        d.addCallback(_then2)

        d.addCallback(lambda _: self.POST(url, destroy1))
        d.addCallback(lambda _: self.POST(url, destroy2))
        # the relay doesn't deliver the last destroy message: the channel is
        # destroyed before that can happen. So we expect 4 messages, not 5.

        d.addCallback(lambda _: self.poll(lambda: check_f(4)))
        def _then3(_):
            self.failUnlessEqual(len(fields), 4)
        d.addCallback(_then3)

        def _stop(_):
            w.relay.unsubscribe_all()
            return client_done[0]
        d.addCallback(_stop)
        return d

    def test_events_after(self):
        # all messages are delivered *after* subscribing
        port = util.allocate_port()
        w = web.WebPort("tcp:%d:interface=127.0.0.1" % port, "token")
        w.enable_relay()
        w.setServiceParent(self.sparent)
        baseurl = "http://localhost:%d/" % port
        sk = SigningKey.generate()
        channelid = sk.verify_key.encode().encode("hex")
        url = baseurl + "relay/" + channelid # must be hex
        msg1 = "r0:" + sk.sign("msg1").encode("hex")
        msg2 = "r0:" + sk.sign("msg2").encode("hex")
        destroy1 = "r0:" + sk.sign("i0:destroy:one").encode("hex")
        destroy2 = "r0:" + sk.sign("i0:destroy:two").encode("hex")

        fields = []
        def handler(name, data):
            fields.append( (name,data) )
        def check_f(min_fields):
            if len(fields) < min_fields:
                return False
            return True

        # this doesn't fire until the event stream has closed. We'll wait it
        # at the end of the test
        client_done = eventsource.EventSource(url, handler).start()

        d = defer.succeed(None)
        d.addCallback(lambda _: self.POST(url, msg1))

        d.addCallback(lambda _: self.poll(lambda: check_f(2)))
        def _then1(_):
            self.failUnlessEqual(len(fields), 2)
            self.failUnlessEqual(fields[0][0], "") # comment
            self.failUnlessEqual(fields[0][1], "beginning Relay event stream")
            self.failUnlessEqual(fields[1][0], "data")
            self.failUnlessEqual(fields[1][1], msg1)
        d.addCallback(_then1)

        d.addCallback(lambda _: self.POST(url, msg2))

        d.addCallback(lambda _: self.poll(lambda: check_f(3)))
        def _then2(_):
            self.failUnlessEqual(len(fields), 3)
            self.failUnlessEqual(fields[2][0], "data")
            self.failUnlessEqual(fields[2][1], msg2)
        d.addCallback(_then2)

        d.addCallback(lambda _: self.POST(url, destroy1))
        d.addCallback(lambda _: self.POST(url, destroy2))
        # the relay doesn't deliver the last destroy message: the channel is
        # destroyed before that can happen. So we expect 4 messages, not 5.

        d.addCallback(lambda _: self.poll(lambda: check_f(4)))
        def _then3(_):
            self.failUnlessEqual(len(fields), 4)
        d.addCallback(_then3)

        def _stop(_):
            w.relay.unsubscribe_all()
            return client_done
        d.addCallback(_stop)
        return d

    def test_client(self):
        port = util.allocate_port()
        w = web.WebPort("tcp:%d:interface=127.0.0.1" % port, "token")
        w.enable_relay()
        w.setServiceParent(self.sparent)
        baseurl = "http://localhost:%d/" % port
        sk = SigningKey.generate()
        channelid = sk.verify_key.encode().encode("hex")
        url = baseurl + "relay/" + channelid # must be hex
        msg1 = "r0:" + sk.sign("msg1").encode("hex")
        msg2 = "r0:" + sk.sign("msg2").encode("hex")
        destroy1 = "r0:" + sk.sign("i0:destroy:one").encode("hex")
        destroy2 = "r0:" + sk.sign("i0:destroy:two").encode("hex")

        a = Accumulator()
        a.setServiceParent(self.sparent)
        c = web_client.HTTPRendezvousClient(baseurl)
        c.setServiceParent(a)

        c.subscribe(channelid)
        d = self.POST(url, msg1)
        def _then1(_):
            self.failUnlessEqual(len(a.messages), 1)
            self.failUnlessEqual(a.messages[0], (channelid, set([msg1])))
            return self.POST(url, msg2)
        d.addCallback(_then1)
        def _then2(_):
            self.failUnlessEqual(len(a.messages), 2)
            self.failUnlessEqual(a.messages[1], (channelid, set([msg2])))
        d.addCallback(_then2)
        d.addCallback(lambda _: self.POST(url, destroy1))
        d.addCallback(lambda _: self.POST(url, destroy2))
        def _then3(_):
            self.failUnlessEqual(len(a.messages), 3)
            self.failUnlessEqual(a.messages[2], (channelid, set([destroy1])))
        d.addCallback(_then3)

        def _stop(_):
            w.relay.unsubscribe_all()
        d.addCallback(_stop)
        return d
