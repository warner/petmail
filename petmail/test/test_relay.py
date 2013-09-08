from twisted.trial import unittest
from twisted.web.client import getPage
from twisted.web.error import Error as WebError
from nacl.signing import SigningKey
from .. import web, util
from .common import NodeRunnerMixin, ShouldFailMixin

class Relay(NodeRunnerMixin, ShouldFailMixin, unittest.TestCase):
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


        d = getPage(baseurl)
        d.addCallback(lambda res: self.failUnlessEqual(res, "Hello\n"))
        d.addCallback(lambda _: getPage(url, headers=HEADERS))
        d.addCallback(lambda res: self.failUnlessEqual(res, ""))

        d.addCallback(lambda _: getPage(url, method="POST", postdata=msg1))
        d.addCallback(lambda res: self.failUnlessEqual(res, "OK\n"))
        d.addCallback(lambda _: getPage(url, headers=HEADERS))
        d.addCallback(lambda res: self.failUnlessEqual(res, msg1+"\n"))
        # duplicates are dismissed
        d.addCallback(lambda _: getPage(url, method="POST", postdata=msg1))
        d.addCallback(lambda res: self.failUnlessEqual(res, "ignoring duplicate message\n"))
        d.addCallback(lambda _: getPage(url, headers=HEADERS))
        d.addCallback(lambda res: self.failUnlessEqual(res, msg1+"\n"))

        d.addCallback(lambda _: getPage(url, method="POST", postdata=msg2))
        d.addCallback(lambda res: self.failUnlessEqual(res, "OK\n"))
        d.addCallback(lambda _: getPage(url, headers=HEADERS))
        d.addCallback(lambda res: self.failUnlessEqual(res,
                                                       msg1+"\n"+msg2+"\n"))

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
        return d
