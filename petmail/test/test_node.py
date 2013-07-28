import os, sys
from StringIO import StringIO
from twisted.trial import unittest
from twisted.internet import threads # CLI tests use deferToThread
from twisted.internet.utils import getProcessOutputAndValue
from ..scripts import runner

class Basic(unittest.TestCase):
    def test_one(self):
        self.assert_(True, "yay!")

class BasedirMixin:
    def make_basedir(self):
        # TestCase.mktemp() creates _trial_temp/MODULE/CLASS/TEST/RANDOM and
        # returns join(that,"temp"). We just want the part that ends with
        # TEST. So we rmdir the RANDOM and return .../TEST
        basedir = self.mktemp()
        random = os.path.dirname(basedir)
        os.rmdir(random)
        test = os.path.dirname(random)
        return test

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

class CLI(CLIinProcessMixin, BasedirMixin, unittest.TestCase):

    def test_create(self):
        basedir = os.path.join(self.make_basedir(), "node1")
        d = self.cliMustSucceed("create-node", basedir)
        def _check(out):
            self.failUnlessEqual(out, "node created in %s\n" % basedir)
            self.failUnless(os.path.exists(os.path.join(basedir, "petmail.db")))
        d.addCallback(_check)
        return d

    def test_run(self):
        basedir = os.path.join(self.make_basedir(), "node1")
        d = self.cliMustSucceed("create-node", basedir)
        d.addCallback(lambda _: self.cliMustSucceed("start", basedir))
        d.addCallback(lambda _: self.cliMustSucceed("open", "-n", "-d",basedir))
        d.addCallback(lambda _: self.cliMustSucceed("stop", basedir))
        return d

