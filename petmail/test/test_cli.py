import textwrap
from StringIO import StringIO
from twisted.trial import unittest
from ..scripts import runner, webwait

# Test arg parsing and construction of the JSON request body, and the right
# webapi endpoint being specified. Do not actually do HTTP. Do not run any
# node code. Generate a fake HTTP response, then test response parsing and
# rc/stdout/stderr generation.

OK = {"ok": "ok"}

class CLI(unittest.TestCase):
    def setUp(self):
        webwait._debug_no_http = self.called
    def tearDown(self):
        webwait._debug_no_http = None

    def called(self, command, args):
        self._command = command
        self._args = args
        return True, self._response

    def call(self, response, *args):
        self._command = None
        self._args = None
        self._response = response
        out,err = StringIO(), StringIO()
        rc = runner.run(args, out, err) # invokes self.called()
        return self._command, self._args, rc, out.getvalue(), err.getvalue()

    def test_sample(self):
        path,body,rc,out,err = self.call({"ok": "sample ok object"}, "sample")
        self.failUnlessEqual((rc, err), (0, ""))
        self.failUnlessEqual(path, "sample")
        self.failUnlessEqual(body, {"data": "no data", "error": 0,
                                    "server-error": 0, "success-object": 0})
        self.failUnlessEqual(out, "sample ok object\n")

    def test_invite(self):
        path,body,rc,out,err = self.call(OK, "invite", "code")
        self.failUnlessEqual((rc, err), (0, ""))
        self.failUnlessEqual(path, "invite")
        self.failUnlessEqual(body, {"code": "code", "petname": None})
        self.failUnlessEqual(out, "ok\n")

    def test_addressbook(self):
        r = {"ok": "ok",
             "addressbook": [{"cid": "42",
                              "their_verfkey": "key1",
                              "their_transport": "tport1",
                              "petname": u"pet",
                              "my_transport": "tport2",
                              "my_verfkey": "key2",
                              "acked": True}],
             }
        path,body,rc,out,err = self.call(r, "addressbook")
        self.failUnlessEqual((rc, err), (0, ""))
        self.failUnlessEqual(path, "list-addressbook")
        self.failUnlessEqual(body, {})
        expected = textwrap.dedent(u'''\
        "pet" (42):
         acknowledged
         their verfkey: key1
         (our verfkey): key2
        ''')
        self.failUnlessEqual(out, expected)

    def test_add_mailbox(self):
        path,body,rc,out,err = self.call(OK,
                                         "add-mailbox", "mailbox-descriptor")
        self.failUnlessEqual((rc, err), (0, ""))
        self.failUnlessEqual(path, "add-mailbox")
        self.failUnlessEqual(body, {"descriptor": "mailbox-descriptor"})
        self.failUnlessEqual(out, "ok\n")
