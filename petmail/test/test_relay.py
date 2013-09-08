from StringIO import StringIO
from twisted.trial import unittest
from twisted.internet import reactor, protocol, defer
from twisted.web.client import getPage, Agent
from twisted.web.http_headers import Headers
from twisted.web.error import Error as WebError
from nacl.signing import SigningKey
from .. import web, util
from ..scripts.messages import get_field, EOFError
from .common import NodeRunnerMixin, ShouldFailMixin
from .pollmixin import PollMixin

class Accumulator(protocol.Protocol):
    def __init__(self):
        self.data = ""
    def dataReceived(self, more):
        self.data += more

class Relay(NodeRunnerMixin, ShouldFailMixin, PollMixin, unittest.TestCase):
    def test_basic(self):
        port = util.allocate_port()
        w = web.WebPort("tcp:%d:interface=127.0.0.1" % port, "token")
        w.enable_relay()
        w.setServiceParent(self.sparent)

    def test_channel(self):
        port = util.allocate_port()
        w = web.WebPort("tcp:%d:interface=127.0.0.1" % port, "token")
        w.enable_relay()
        w.setServiceParent(self.sparent)
        baseurl = "http://localhost:%d/" % port
        sk = SigningKey.generate()
        channelid = sk.verify_key.encode().encode("hex")
        url = baseurl + "relay/" + channelid # must be hex
        HEADERS = {"accept": "application/json"}
        msg1 = "r0:" + sk.sign("msg1").encode("hex")
        msg2 = "r0:" + sk.sign("msg2").encode("hex")
        destroy1 = "r0:" + sk.sign("i0:destroy:one").encode("hex")
        destroy2 = "r0:" + sk.sign("i0:destroy:two").encode("hex")

        def lines(*messages):
            return "\n".join(messages)+"\n"

        d = getPage(baseurl)
        d.addCallback(lambda res: self.failUnlessEqual(res, "Hello\n"))
        d.addCallback(lambda _: getPage(url, headers=HEADERS))
        d.addCallback(lambda res: self.failUnlessEqual(res, ""))

        d.addCallback(lambda _: getPage(url, method="POST", postdata=msg1))
        d.addCallback(lambda res: self.failUnlessEqual(res, "OK\n"))
        d.addCallback(lambda _: getPage(url, headers=HEADERS))
        d.addCallback(lambda res: self.failUnlessEqual(res, lines(msg1)))
        # duplicates are dismissed
        d.addCallback(lambda _: getPage(url, method="POST", postdata=msg1))
        d.addCallback(lambda res: self.failUnlessEqual(res, "ignoring duplicate message\n"))
        d.addCallback(lambda _: getPage(url, headers=HEADERS))
        d.addCallback(lambda res: self.failUnlessEqual(res, lines(msg1)))

        d.addCallback(lambda _: getPage(url, method="POST", postdata=msg2))
        d.addCallback(lambda res: self.failUnlessEqual(res, "OK\n"))
        d.addCallback(lambda _: getPage(url, headers=HEADERS))
        d.addCallback(lambda res: self.failUnlessEqual(res, lines(msg1,msg2)))

        # now test the various error conditions
        # invalid channel
        d.addCallback(lambda _:
                      self.shouldFail(WebError, "400 Bad Request",
                                      "invalid channel id",
                                      getPage, url+"NOTHEX"))
        d.addCallback(lambda _:
                      self.shouldFail(WebError, "400 Bad Request",
                                      "unrecognized rendezvous message prefix",
                                      getPage, url, method="POST",
                                      postdata="r1:badversion"))
        d.addCallback(lambda _:
                      self.shouldFail(WebError, "400 Bad Request",
                                      "invalid rendezvous message",
                                      getPage, url, method="POST",
                                      postdata="r0:NOTHEX"))
        d.addCallback(lambda _:
                      self.shouldFail(WebError, "400 Bad Request",
                                      "invalid rendezvous message signature",
                                      getPage, url, method="POST",
                                      postdata="r0:d00dbadfeede"))

        # and channel destruction
        d.addCallback(lambda _: getPage(url, method="POST", postdata=destroy1))
        d.addCallback(lambda res: self.failUnlessEqual(res, "OK\n"))
        d.addCallback(lambda _: getPage(url, headers=HEADERS))
        d.addCallback(lambda res:
                      self.failUnlessEqual(res, lines(msg1,msg2,destroy1)))
        d.addCallback(lambda _: getPage(url, method="POST", postdata=destroy2))
        d.addCallback(lambda res: self.failUnlessEqual(res, "Destroyed\n"))
        d.addCallback(lambda _: getPage(url, headers=HEADERS))
        d.addCallback(lambda res: self.failUnlessEqual(res, ""))

        return d

    def parse(self, data):
        if not data.endswith("\n"):
            return None # won't parse partial response
        s = StringIO(data)
        fields = []
        try:
            while True:
                fields.append(get_field(s))
        except EOFError:
            return fields

    def check_n(self, acc, min_fields):
        fields = self.parse(acc.data)
        if fields is None:
            return False
        if len(fields) < min_fields:
            return False
        return True

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

        acc = Accumulator()
        a = Agent(reactor)

        d = defer.succeed(None)
        d.addCallback(lambda _: getPage(url, method="POST", postdata=msg1))
        d.addCallback(lambda _:
                      a.request("GET", url,
                                Headers({"accept": ["text/event-stream"]})))
        def _connected(resp):
            self.failUnlessEqual(resp.code, 200)
            self.failUnlessEqual(resp.headers.getRawHeaders("content-type"),
                                 ["text/event-stream"])
            resp.deliverBody(acc)
        d.addCallback(_connected)

        d.addCallback(lambda _: self.poll(lambda: self.check_n(acc, 2)))
        def _then1(_):
            fields = self.parse(acc.data)
            self.failUnlessEqual(len(fields), 2)
            self.failUnlessEqual(fields[0][0], "") # comment
            self.failUnlessEqual(fields[0][1], "beginning Relay event stream")
            self.failUnlessEqual(fields[1][0], "data")
            self.failUnlessEqual(fields[1][1], msg1)
        d.addCallback(_then1)

        d.addCallback(lambda _: getPage(url, method="POST", postdata=msg2))

        d.addCallback(lambda _: self.poll(lambda: self.check_n(acc, 3)))
        def _then2(_):
            fields = self.parse(acc.data)
            self.failUnlessEqual(len(fields), 3)
            self.failUnlessEqual(fields[2][0], "data")
            self.failUnlessEqual(fields[2][1], msg2)
        d.addCallback(_then2)

        d.addCallback(lambda _: getPage(url, method="POST", postdata=destroy1))
        d.addCallback(lambda _: getPage(url, method="POST", postdata=destroy2))
        # the relay doesn't deliver the last destroy message: the channel is
        # destroyed before that can happen. So we expect 4 messages, not 5.

        d.addCallback(lambda _: self.poll(lambda: self.check_n(acc, 4)))
        def _then3(_):
            fields = self.parse(acc.data)
            self.failUnlessEqual(len(fields), 4)
        d.addCallback(_then3)

        def _stop(_):
            w.relay.unsubscribe_all()
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

        acc = Accumulator()
        a = Agent(reactor)
        d = a.request("GET", url, Headers({"accept": ["text/event-stream"]}))
        def _connected(resp):
            self.failUnlessEqual(resp.code, 200)
            self.failUnlessEqual(resp.headers.getRawHeaders("content-type"),
                                 ["text/event-stream"])
            resp.deliverBody(acc)
            self.failUnlessEqual(len(acc.data), 0)
        d.addCallback(_connected)

        d.addCallback(lambda _: getPage(url, method="POST", postdata=msg1))

        d.addCallback(lambda _: self.poll(lambda: self.check_n(acc, 2)))
        def _then1(_):
            fields = self.parse(acc.data)
            self.failUnlessEqual(len(fields), 2)
            self.failUnlessEqual(fields[0][0], "") # comment
            self.failUnlessEqual(fields[0][1], "beginning Relay event stream")
            self.failUnlessEqual(fields[1][0], "data")
            self.failUnlessEqual(fields[1][1], msg1)
        d.addCallback(_then1)

        d.addCallback(lambda _: getPage(url, method="POST", postdata=msg2))

        d.addCallback(lambda _: self.poll(lambda: self.check_n(acc, 3)))
        def _then2(_):
            fields = self.parse(acc.data)
            self.failUnlessEqual(len(fields), 3)
            self.failUnlessEqual(fields[2][0], "data")
            self.failUnlessEqual(fields[2][1], msg2)
        d.addCallback(_then2)

        d.addCallback(lambda _: getPage(url, method="POST", postdata=destroy1))
        d.addCallback(lambda _: getPage(url, method="POST", postdata=destroy2))
        # the relay doesn't deliver the last destroy message: the channel is
        # destroyed before that can happen. So we expect 4 messages, not 5.

        d.addCallback(lambda _: self.poll(lambda: self.check_n(acc, 4)))
        def _then3(_):
            fields = self.parse(acc.data)
            self.failUnlessEqual(len(fields), 4)
        d.addCallback(_then3)

        def _stop(_):
            w.relay.unsubscribe_all()
        d.addCallback(_stop)
        return d
