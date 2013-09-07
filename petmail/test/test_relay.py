from twisted.trial import unittest
from twisted.web.client import getPage
from .. import web, util
from .common import NodeRunnerMixin

class Relay(NodeRunnerMixin, unittest.TestCase):
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
        url = baseurl + "relay/channelID"
        HEADERS = {"accept": "application/json"}

        d = getPage(baseurl)
        d.addCallback(lambda res: self.failUnlessEqual(res, "Hello\n"))
        d.addCallback(lambda _: getPage(url, headers=HEADERS))

        d.addCallback(lambda res: self.failUnlessEqual(res, ""))
        d.addCallback(lambda _: getPage(url, method="POST", postdata="msg1"))
        d.addCallback(lambda res: self.failUnlessEqual(res, "OK\n"))
        d.addCallback(lambda _: getPage(url, headers=HEADERS))
        d.addCallback(lambda res: self.failUnlessEqual(res, "msg1\n"))

        d.addCallback(lambda _: getPage(url, method="POST", postdata="msg2"))
        d.addCallback(lambda res: self.failUnlessEqual(res, "OK\n"))
        d.addCallback(lambda _: getPage(url, headers=HEADERS))
        d.addCallback(lambda res: self.failUnlessEqual(res, "msg1\nmsg2\n"))
        return d
