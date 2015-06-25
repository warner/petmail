import os
from twisted.trial import unittest
from ..web import SampleError
from .common import (BasedirMixin, NodeRunnerMixin,
                     CLIinThreadMixin, CLIinProcessMixin)

# most tests will just do Node.startService and invoke CLI commands by
# talking directly to the web handler: no network, no other processes.

# To cover the HTTP interface, we need a few tests which run the CLI command
# with deferToThread (to handle the time.sleep and blocking IO). These use
# CLIinThreadMixin.

# And we need one or two tests that exercise the daemonization in 'petmail
# start', which requires a subprocess. Those use CLIinProcessMixin

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

