import os, sys, json
from StringIO import StringIO
from twisted.trial import unittest
from twisted.python import failure
from twisted.internet import threads # CLI tests use deferToThread
from twisted.internet import defer
from twisted.internet.utils import getProcessOutputAndValue
from ..scripts import runner
from ..web import SampleError
from .common import BasedirMixin, NodeRunnerMixin

class Basic(unittest.TestCase):
    def test_one(self):
        self.assert_(True, "yay!")

# most tests will just do Node.startService and invoke CLI commands by
# talking directly to the web handler: no network, no other processes.

# To cover the HTTP interface, we need a few tests which run the CLI command
# with deferToThread (to handle the time.sleep and blocking IO). These use
# CLIinThreadMixin.

# And we need one or two tests that exercise the daemonization in 'petmail
# start', which requires a subprocess. Those use CLIinProcessMixin

class CLIinThreadMixin:
    def cli(self, *args, **kwargs):
        stdout, stderr = StringIO(), StringIO()
        d = threads.deferToThread(runner.run, list(args), stdout, stderr,
                                  kwargs.get("petmail"))
        def _done(rc):
            return stdout.getvalue(), stderr.getvalue(), rc
        d.addCallback(_done)
        return d
    def mustSucceed(self, (out, err, rc)):
        if rc != 0:
            self.fail("rc=%s out='%s' err='%s'" % (rc, out, err))
        self.stderr = err
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
        if isinstance(res, failure.Failure):
            # let the original failure passthrough
            d.addBoth(lambda _: res)
        # otherwise the original result was success, so just return the
        # cleanup result
        return d

class Run(CLIinProcessMixin, BasedirMixin, unittest.TestCase):

    def test_node(self):
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

    def test_node_with_relay(self):
        basedir = os.path.join(self.make_basedir(), "node1")
        d = self.cliMustSucceed("create-node",
                                "--relay-url", "http://localhost:1234/",
                                basedir)
        d.addCallback(lambda _: self.cliMustSucceed("start", basedir))
        d.addBoth(self.anyways, self.cliMustSucceed, "stop", basedir)
        return d

    def test_relay(self):
        basedir = os.path.join(self.make_basedir(), "node1")
        d = self.cliMustSucceed("create-relay", basedir)
        d.addCallback(lambda _: self.cliMustSucceed("start", basedir))
        d.addBoth(self.anyways, self.cliMustSucceed, "stop", basedir)
        return d

class CLI(CLIinThreadMixin, BasedirMixin, NodeRunnerMixin, unittest.TestCase):
    def test_create_node(self):
        basedir = os.path.join(self.make_basedir(), "node1")
        d = self.cliMustSucceed("create-node", basedir)
        def _check(out):
            self.failUnless(out.startswith("node created in %s, URL is http://localhost:" % basedir), out)
            self.failUnless(os.path.exists(os.path.join(basedir, "petmail.db")))
        d.addCallback(_check)
        return d

    def test_print_baseurl(self):
        basedir = os.path.join(self.make_basedir(), "node1")
        not_basedir = basedir+"-NOT"
        d = self.cliMustSucceed("create-node", basedir)
        def _check(out):
            self.failUnless(out.startswith("node created in %s, URL is http://localhost:" % basedir), out)
        d.addCallback(_check)
        d.addCallback(lambda _: self.cliMustSucceed("print-baseurl", basedir))
        def _check_baseurl(out):
            self.failUnless(out.startswith("http://localhost:"), out)
        d.addCallback(_check_baseurl)
        d.addCallback(lambda _: self.cli("print-baseurl", not_basedir))
        def _check_not_baseurl((out, err, rc)):
            self.failUnlessEqual(rc, 1)
            self.failUnlessEqual(err.strip(), "'%s' doesn't look like a Petmail basedir, quitting" % not_basedir)
        d.addCallback(_check_not_baseurl)
        return d

    def test_create_node_with_local_petmail(self):
        basedir = os.path.join(self.make_basedir(), "node1")
        d = self.cliMustSucceed("create-node", basedir,
                                petmail="path-to-real-petmail")
        def _check(out):
            self.failUnless(out.startswith("node created in %s, URL is http://localhost:" % basedir), out)
            local_petmail = os.path.join(basedir, "petmail")
            self.failUnless(os.path.exists(local_petmail))
            with open(local_petmail, "r") as f:
                contents = f.readlines()
            self.failUnlessEqual(contents[0].strip(), "#!/bin/sh")
            pieces = contents[1].split()
            self.failUnlessEqual(pieces[0], os.path.abspath("path-to-real-petmail"))
            self.failUnlessEqual(pieces[1], "-d")
            self.failUnlessEqual(pieces[2], os.path.abspath(basedir))
            self.failUnlessEqual(pieces[3], '"$@"')
        d.addCallback(_check)
        return d

    def test_create_unreachable_node(self):
        basedir = os.path.join(self.make_basedir(), "node1")
        d = self.cliMustSucceed("create-node", "--hostname", "not-localhost",
                                basedir)
        def _check(out):
            self.failUnless(out.startswith("node created in %s, URL is http://not-localhost:" % basedir), out)
            self.failUnless(os.path.exists(os.path.join(basedir, "petmail.db")))
            self.failUnlessEqual(self.stderr.strip(),
                                 "WARNING: if you set --hostname, you probably want to set --listen too")
        d.addCallback(_check)
        return d

    def test_create_node_bad_listener(self):
        basedir = os.path.join(self.make_basedir(), "node1")
        d = self.cli("create-node", "--listen", "666", basedir)
        def _check((out, err, rc)):
            self.failUnlessEqual(rc, 1)
            self.failUnlessEqual(err.strip(), "--listen currently must start with tcp:")
            self.failIf(os.path.exists(os.path.join(basedir, "petmail.db")))
        d.addCallback(_check)
        return d

    def test_create_node_existing_basedir(self):
        basedir = os.path.join(self.make_basedir(), "node1")
        d = self.cliMustSucceed("create-node", basedir)
        d.addCallback(lambda _: self.cli("create-node", basedir))
        def _check((out, err, rc)):
            self.failUnlessEqual(rc, 1)
            self.failUnlessEqual(err.strip(), "basedir '%s' already exists, refusing to touch it" % basedir)
        d.addCallback(_check)
        return d

    def test_create_advertise_localhost(self):
        basedir = os.path.join(self.make_basedir(), "node1")
        d = self.cliMustSucceed("create-node", "--local-mailbox", basedir)
        def _check(out):
            self.failUnless(out.startswith("node created in %s, URL is http://localhost:" % basedir), out)
            self.failUnless(os.path.exists(os.path.join(basedir, "petmail.db")))
            self.failUnlessEqual(self.stderr.strip(),
                                 "WARNING: --local-mailbox and --hostname=localhost is probably wrong")
        d.addCallback(_check)
        return d

    def test_create_node_with_relay(self):
        basedir = os.path.join(self.make_basedir(), "node1")
        d = self.cliMustSucceed("create-node",
                                "--relay-url", "http://localhost:1234/",
                                basedir)
        def _check(out):
            n = self.buildNode(basedir)
            rows = n.db.execute("SELECT * FROM relay_servers").fetchall()
            self.failUnlessEqual(len(rows), 1)
            desc = json.loads(rows[0]["descriptor_json"])
            self.failUnlessEqual(str(desc["type"]), "http")
            self.failUnlessEqual(str(desc["url"]), "http://localhost:1234/")
        d.addCallback(_check)
        return d

    def test_create_node_with_relay_no_slash(self):
        basedir = os.path.join(self.make_basedir(), "node1")
        d = self.cliMustSucceed("create-node",
                                "--relay-url", "http://localhost:1234",
                                basedir)
        def _check(out):
            n = self.buildNode(basedir)
            rows = n.db.execute("SELECT * FROM relay_servers").fetchall()
            self.failUnlessEqual(len(rows), 1)
            desc = json.loads(rows[0]["descriptor_json"])
            self.failUnlessEqual(str(desc["type"]), "http")
            # create-node should add the missing slash
            self.failUnlessEqual(str(desc["url"]), "http://localhost:1234/")
        d.addCallback(_check)
        return d

    def test_create_relay(self):
        basedir = os.path.join(self.make_basedir(), "node1")
        d = self.cliMustSucceed("create-relay", basedir)
        def _check(out):
            self.failUnless(out.startswith("node created in %s, URL is http://localhost:" % basedir), out)
            self.failUnless(os.path.exists(os.path.join(basedir, "petmail.db")))
            n = self.startNode(basedir)
            url = str(n.db.execute("SELECT * from node").fetchone()["baseurl"])
            self.failUnless(url.startswith("http://localhost:"), url)
        d.addCallback(_check)
        return d

    def test_create_relay_urls(self):
        b = self.make_basedir()
        def create(*args):
            return self.cliMustSucceed("create-relay", *args)
        def check(out, basedir, hostport):
            exp = "node created in %s, URL is http://%s/\n"
            self.failUnlessEqual(out, exp % (basedir, hostport))
        d = defer.succeed(None)
        b1 = os.path.join(b, "node1")
        d.addCallback(lambda out: create("--listen", "tcp:1234", b1))
        d.addCallback(lambda out: check(out, b1, "localhost:1234"))
        b2 = os.path.join(b, "node2")
        d.addCallback(lambda out: create("--listen", "tcp:1234",
                                         "--hostname", "example.org", b2))
        d.addCallback(lambda out: check(out, b2, "example.org:1234"))
        b3 = os.path.join(b, "node3")
        d.addCallback(lambda out: create("--listen", "tcp:1234",
                                         "--hostname", "example.org",
                                         "--port", "3456", b3))
        d.addCallback(lambda out: check(out, b3, "example.org:3456"))
        b4 = os.path.join(b, "node4")
        d.addCallback(lambda out: create("--hostname", "example.org",
                                         "--port", "3457", b4))
        d.addCallback(lambda out: check(out, b4, "example.org:3457"))
        b5 = os.path.join(b, "node5")
        d.addCallback(lambda out: create("--port", "3458", b5))
        d.addCallback(lambda out: check(out, b5, "localhost:3458"))
        b6 = os.path.join(b, "node6")
        d.addCallback(lambda out: create("--listen", "tcp:1234",
                                         "--port", "3459", b6))
        d.addCallback(lambda out: check(out, b6, "localhost:3459"))
        return d

    def test_sample(self):
        basedir = os.path.join(self.make_basedir(), "node1")
        self.createNode(basedir)
        n = self.startNode(basedir)
        d = self.cliMustSucceed("open", "-n", "-d", basedir)
        # test "petmail sample -d BASEDIR"
        d.addCallback(lambda _: self.cliMustSucceed("sample", "-d", basedir))
        d.addCallback(lambda res: self.failUnlessEqual(res, "sample ok\n"))
        d.addCallback(lambda _: self.failUnlessEqual(n.agent._debug_sample,
                                                     "no data"))
        d.addCallback(lambda _: self.cliMustSucceed("sample", "-d", basedir,
                                                    "-o", "other data"))
        d.addCallback(lambda res: self.failUnlessEqual(res, "sample ok object\n"))
        d.addCallback(lambda _: self.failUnlessEqual(n.agent._debug_sample,
                                                     "other data"))
        d.addCallback(lambda _: self.cli("sample", "-d", basedir, "--error"))
        def _fail1((out,err,rc)):
            self.failIfEqual(rc, 0)
            self.failUnlessEqual(out, "")
            self.failUnlessEqual(err,
                                 "HTTP status: 400 command error\n"+
                                 "sample error text\n")
        d.addCallback(_fail1)

        # Also test --server-error . This raises a ValueError inside the
        # server, which we must eat to keep the test framework from thinking
        # an error went unhandled.
        d.addCallback(lambda _: self.cli("sample", "-d", basedir,
                                         "--server-error"))
        def _fail2((out,err,rc)):
            self.failIfEqual(rc, 0)
            self.failUnlessEqual(out, "")
            self.failUnlessEqual(err,
                                 "HTTP status: 500 Internal Server Error\n"+
                                 "Please see node logs for details\n")
            self.flushLoggedErrors(SampleError)
        d.addCallback(_fail2)

        # test "petmail -d BASEDIR sample" too
        d.addCallback(lambda _: self.cliMustSucceed("-d", basedir, "sample"))
        d.addCallback(lambda res: self.failUnlessEqual(res, "sample ok\n"))

        return d

