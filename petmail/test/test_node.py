import os, sys
from StringIO import StringIO
from twisted.trial import unittest
from twisted.internet import threads # CLI tests use deferToThread
from twisted.internet import defer
from twisted.internet.utils import getProcessOutputAndValue
from ..scripts import runner
from .common import BasedirMixin, NodeRunnerMixin

class Basic(unittest.TestCase):
    def test_one(self):
        self.assert_(True, "yay!")

# most tests will just do Node.startService and invoke CLI commands by
# talking directly to the web handler: no network, no other processes.

# To cover the HTTP interface, we need a few tests which run the CLI command
# with deferToThread (to handle the time.sleep and blocking IO).

# And we need one or two tests that exercise the daemonization in 'petmail
# start', which requires a subprocess.

class CLIinThreadMixin:
    def cli(self, *args, **kwargs):
        stdout, stderr = StringIO(), StringIO()
        d = threads.deferToThread(runner.run, list(args), stdout, stderr)
        def _done(rc):
            return stdout.getvalue(), stderr.getvalue(), rc
        d.addCallback(_done)
        return d
    def mustSucceed(self, (out, err, rc)):
        if rc != 0:
            self.fail("rc=%s out='%s' err='%s'" % (rc, out, err))
        return out

    def cliMustSucceed(self, *args, **kwargs):
        d = self.cli(*args, **kwargs)
        d.addCallback(self.mustSucceed)
        return d

class CLIinProcessMixin(CLIinThreadMixin):
    def cli(self, *args, **kwargs):
        petmail = runner.petmail_executable[0]
        d = getProcessOutputAndValue(sys.executable, [petmail] + list(args),
                                     os.environ)
        return d

    def anyways(self, res, cb, *args, **kwargs):
        # always run the cleanup callback
        d = defer.maybeDeferred(cb, *args, **kwargs)
        # if it succeeds, return the original result (which might be a
        # Failure). Otherwise return the cleanup failure.
        d.addCallbacks(lambda _: res, lambda f: f)
        return d

class Run(CLIinProcessMixin, BasedirMixin, unittest.TestCase):

    def test_run(self):
        basedir = os.path.join(self.make_basedir(), "node1")
        d = self.cliMustSucceed("create-node", basedir)
        d.addCallback(lambda _: self.cliMustSucceed("start", basedir))
        d.addCallback(lambda _: self.cliMustSucceed("open", "-n", "-d",basedir))
        def _check_url(out):
            self.failUnlessSubstring("Node appears to be running, opening browser", out)
            self.failUnlessSubstring("Please open: http://localhost:", out)
            self.failUnlessSubstring("/open-control?opener-token=", out)
        d.addCallback(_check_url)
        d.addBoth(self.anyways, self.cliMustSucceed, "stop", basedir)
        return d

class CLI(CLIinThreadMixin, BasedirMixin, NodeRunnerMixin, unittest.TestCase):
    def test_create(self):
        basedir = os.path.join(self.make_basedir(), "node1")
        d = self.cliMustSucceed("create-node", basedir)
        def _check(out):
            self.failUnlessEqual(out, "node created in %s\n" % basedir)
            self.failUnless(os.path.exists(os.path.join(basedir, "petmail.db")))
        d.addCallback(_check)
        return d

    def test_api(self):
        basedir = os.path.join(self.make_basedir(), "node1")
        self.createNode(basedir)
        n = self.startNode(basedir)
        d = self.cliMustSucceed("open", "-n", "-d", basedir)
        d.addCallback(lambda _: self.cliMustSucceed("sample", "-d", basedir))
        d.addCallback(self.failUnlessEqual, "True\n", "one")
        d.addCallback(lambda _: self.failUnlessEqual(n.client._debug_sample,
                                                     "no data"))
        d.addCallback(lambda _: self.cliMustSucceed("sample", "-d", basedir,
                                                    "-o", "other data"))
        d.addCallback(self.failUnlessEqual, "sample ok object\n", "two")
        d.addCallback(lambda _: self.failUnlessEqual(n.client._debug_sample,
                                                     "other data"))
        d.addCallback(lambda _: self.cli("sample", "-d", basedir, "-e"))
        def _fail1((out,err,rc)):
            self.failIfEqual(rc, 0)
            self.failUnlessEqual(out, "")
            self.failUnlessEqual(err, "sample error text\n")
        d.addCallback(_fail1)
        return d
        # Also test --server-error . This isn't ready yet.
        d.addCallback(lambda _: self.cli("sample", "-d", basedir, "-s"))
        # that should raise a ValueError
        def _no_error(res):
            self.fail("expected a failure, not %s" % (res,))
        def _got_error(f):
            f.check(ValueError)
            print str(f)
        d.addCallbacks(_no_error, _got_error)
        return d

