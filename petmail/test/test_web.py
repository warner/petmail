import os, re
from twisted.trial import unittest
from twisted.internet import defer
from twisted.web.client import getPage
from .common import BasedirMixin, NodeRunnerMixin, CLIinThreadMixin

class Web(BasedirMixin, NodeRunnerMixin, CLIinThreadMixin, unittest.TestCase):
    def do_cli(self, command, *args):
        return self.cliMustSucceed("-d", self.basedir, command, *args)

    def test_opener(self):
        self.basedir = os.path.join(self.make_basedir(), "node")
        self.createNode(self.basedir)
        n = self.startNode(self.basedir)

        d = defer.succeed(None)

        d.addCallback(lambda _: self.do_cli("open", "--no-open"))
        def _stash_opener_url(res):
            mo = re.search(r'Please open: (.*)\n', res)
            opener_url = mo.group(1)
            token = (n.db.execute("SELECT * FROM webapi_opener_tokens")
                     .fetchone()["token"])
            expected = n.baseurl + "open-control?opener-token=" + token
            self.failUnlessEqual(opener_url, expected)
            self.opener_url = opener_url
            self.bad_opener_url = n.baseurl + "open-control?opener-token=BAD"
            self.lame_opener_url = n.baseurl + "open-control"
        d.addCallback(_stash_opener_url)

        d.addCallback(lambda _: getPage(self.lame_opener_url, method="GET"))
        def _check_lame_login_page(page):
            self.failUnlessIn("Please use 'petmail open' to get to the control panel", page)
        d.addCallback(_check_lame_login_page)

        d.addCallback(lambda _: getPage(self.bad_opener_url, method="GET"))
        def _check_bad_login_page(page):
            self.failUnlessIn("Sorry, that opener-token is expired or invalid, please run 'petmail open' again", page)
        d.addCallback(_check_bad_login_page)

        d.addCallback(lambda _: getPage(self.opener_url, method="GET"))
        def _check_login_page(page):
            self.failUnlessIn('<form id="login" ', page)
            token = (n.db.execute("SELECT * FROM webapi_access_tokens")
                     .fetchone()["token"])
            self.failUnlessIn('<input type="hidden" name="token" value="%s">'
                              % token, page)
            tokens = (n.db.execute("SELECT * FROM webapi_opener_tokens")
                      .fetchall())
            self.failUnlessEqual(len(tokens), 0)
        d.addCallback(_check_login_page)

        return d
