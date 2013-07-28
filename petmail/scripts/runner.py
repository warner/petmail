
# only import stdlib at the top level. Do not import anything from our
# dependency set, or parts of petmail that require things from the dependency
# set, until runtime, inside a command that specifically needs it.

import os, sys

try:
    # do not import anything from Twisted that requires the reactor, to allow
    # 'petmail start' to choose a reactor itself
    from twisted.python import usage
except ImportError:
    print >>sys.stderr, "Unable to import Twisted."
    print >>sys.stderr, "Please run 'python setup.py build_deps'"
    raise
    sys.exit(1)

class NoNodeError(Exception):
    def __init__(self, basedir):
        self.basedir = basedir
    def __str__(self):
        return "NoNodeError: '%s' doesn't look like a Petmail basedir, quitting" % self.basedir

class BasedirParameterMixin:
    optParameters = [
        ("basedir", "d", os.path.expanduser("~/.petmail"), "Base directory"),
        ]
class BasedirArgument:
    def parseArgs(self, basedir=None):
        if basedir is not None:
            self["basedir"] = basedir

class StartArguments(BasedirArgument):
    def parseArgs(self, basedir=None, *twistd_args):
        # this can't handle e.g. 'petmail start --nodaemon', since then
        # --nodaemon looks like a basedir. Consider using (self, *all_args)
        # and searching for "--" to indicate the start of the twistd_args
        self.twistd_args = twistd_args
        BasedirArgument.parseArgs(self, basedir)

class CreateNodeOptions(BasedirParameterMixin, BasedirArgument, usage.Options):
    optParameters = [
        ("webport", "p", "tcp:0:interface=127.0.0.1",
         "TCP port for the node's HTTP interface."),
        ("relay", "r", "tcp:host=localhost:port=5773", "Relay location"),
        ]

class StartNodeOptions(BasedirParameterMixin, StartArguments, usage.Options):
    optFlags = [
        ("no-open", "n", "Do not automatically open the control panel"),
        ]
class StopNodeOptions(BasedirParameterMixin, BasedirArgument, usage.Options):
    pass
class RestartNodeOptions(BasedirParameterMixin, StartArguments, usage.Options):
    def postOptions(self):
        self["no-open"] = False
class OpenOptions(BasedirParameterMixin, BasedirArgument, usage.Options):
    optFlags = [
        ("no-open", "n", "Don't open webbrowser, just show URL"),
        ]

class SampleOptions(BasedirParameterMixin, usage.Options):
    optFlags = [
        ("success-object", "o", "Return a success object, not success string"),
        ("error", "e", "Cause a command error (400)"),
        ("server-error", "s", "Cause a server error (500)"),
        ]

class InviteOptions(BasedirParameterMixin, usage.Options):
    #("petname", "n", None, "Petname for the person being invited"),
    def parseArgs(self, petname):
        self["petname"] = petname

class AcceptOptions(BasedirParameterMixin, usage.Options):
    #("petname", "n", None, "Petname for the person making the invitation"),
    def parseArgs(self, petname, invitation_code):
        self["petname"] = petname
        self["invitation_code"] = invitation_code

class TestOptions(usage.Options):
    def parseArgs(self, *test_args):
        if not test_args:
            self.test_args = ["petmail"]
        else:
            self.test_args = list(test_args)

class Options(usage.Options):
    synopsis = "\nUsage: petmail <command>"
    subCommands = [("create-node", None, CreateNodeOptions, "Create a node"),
                   ("start", None, StartNodeOptions, "Start a node"),
                   ("stop", None, StopNodeOptions, "Stop a node"),
                   ("restart", None, RestartNodeOptions, "Restart a node"),
                   ("open", None, OpenOptions, "Open web control panel"),

                   ("sample", None, SampleOptions, "Sample Command"),
                   ("invite", None, InviteOptions, "Create an Invitation"),
                   ("accept", None, AcceptOptions, "Accept an Invitation"),

                   ("test", None, TestOptions, "Run unit tests"),
                   ]

    def opt_version(self):
        """Display version information"""
        from .. import __version__
        print "Petmail version: %s" % __version__
        import twisted.copyright
        print "Twisted version: %s" % twisted.copyright.version
        sys.exit(0)

    def opt_full_version(self):
        """Display detailed version information"""
        from .._version import get_versions
        v = get_versions()
        print "Petmail version: %s (%s)" % (v["version"], v["full"])
        import twisted.copyright
        print "Twisted version: %s" % twisted.copyright.version
        sys.exit(0)

    def getUsage(self, **kwargs):
        t = usage.Options.getUsage(self, **kwargs)
        return t + "\nPlease run 'petmail <command> --help' for more details on each command.\n"

    def postOptions(self):
        if not hasattr(self, 'subOptions'):
            raise usage.UsageError("must specify a command")

def create_node(*args):
    from .create_node import create_node
    return create_node(*args)

def start(*args):
    from .startstop import start
    return start(*args)

def stop(*args):
    from .startstop import stop
    return stop(*args)

def restart(*args):
    from .startstop import restart
    return restart(*args)

def open_control_panel(*args):
    from .open import open_control_panel
    return open_control_panel(*args)


def create_relay(*args):
    from .create_node import create_relay
    return create_relay(*args)

petmail_executable = []

def test(so, stdout, stderr):
    petmail = os.path.abspath(sys.argv[0])
    petmail_executable.append(petmail) # to run bin/petmail in a subprocess
    from twisted.scripts import trial as twisted_trial
    sys.argv = ["trial"] + so.test_args
    twisted_trial.run() # this does not return
    sys.exit(0) # just in case

def sample(*args):
    from .sample import sample
    return sample(*args)

def invite(*args):
    from .create_invitation import create_invitation
    return create_invitation(*args)

def accept(*args):
    from .accept_invitation import accept_invitation
    return accept_invitation(*args)

DISPATCH = {"create-node": create_node,
            "start": start,
            "stop": stop,
            "restart": restart,
            "open": open_control_panel,
            "create-relay": create_relay,
            "test": test,

            "sample": sample,
            "invite": invite,
            "accept": accept,
            }

def run(args, stdout, stderr):
    config = Options()
    try:
        config.parseOptions(args)
    except usage.error, e:
        c = config
        while hasattr(c, 'subOptions'):
            c = c.subOptions
        print >>stderr, str(c)
        print >>stderr, e.args[0]
        return 1
    command = config.subCommand
    so = config.subOptions
    try:
        rc = DISPATCH[command](so, stdout, stderr)
        return rc
    except ImportError, e:
        print >>stderr, "--- ImportError ---"
        print >>stderr, e
        print >>stderr, "Please run 'python setup.py build'"
        raise
        return 1
    except NoNodeError, e:
        print >>stderr, e
        return 1
