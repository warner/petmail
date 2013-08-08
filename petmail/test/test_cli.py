from StringIO import StringIO
from twisted.trial import unittest
from ..scripts import runner, webwait

# Test arg parsing and construction of the JSON request body, and the right
# webapi endpoint being specified. Do not actually do HTTP. Do not run any
# node code. Generate a fake HTTP response, then test response parsing and
# rc/stdout/stderr generation.

OK = {"ok": True, "text": "ok"}

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
        self.failUnlessEqual(path, "sample")
        self.failUnlessEqual(body, {"data": "no data"})
        self.failUnlessEqual(rc, 0)
        self.failUnlessEqual(out, "sample ok object\n")
        self.failUnlessEqual(err, "")

    def test_invite(self):
        path,body,rc,out,err = self.call(OK, "invite", "code")
        self.failUnlessEqual(rc, 0, str((rc,err)))
        self.failUnlessEqual(err, "")
        self.failUnlessEqual(out, "ok\n")
        self.failUnlessEqual(path, "invite")
        self.failUnlessEqual(body, {"code": "code", "petname": None})

