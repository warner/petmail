import os
from twisted.application import service
from StringIO import StringIO
from ..scripts import runner, startstop
from ..scripts.create_node import create_node

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

class NodeRunnerMixin:
    def setUp(self):
        self.sparent = service.MultiService()
        self.sparent.startService()

    def tearDown(self):
        return self.sparent.stopService()

    def createNode(self, basedir):
        so = runner.CreateNodeOptions()
        so.parseOptions([basedir])
        out,err = StringIO(), StringIO()
        rc = create_node(so, out, err)
        self.failUnlessEqual(rc, 0, (rc, out, err))
        return rc, out ,err

    def startNode(self, basedir, beforeStart=None):
        so = runner.StartNodeOptions()
        so.parseOptions([basedir])
        p = startstop.MyPlugin(basedir, os.path.join(basedir, "petmail.db"))
        n = p.makeService(so)
        if beforeStart:
            beforeStart(n)
        n.setServiceParent(self.sparent)
        return n

    def disable_polling(self, n):
        list(n.client.im)[0].enable_polling = False


class TwoNodeMixin(BasedirMixin, NodeRunnerMixin):
    def make_nodes(self):
        basedirA = os.path.join(self.make_basedir(), "nodeA")
        self.createNode(basedirA)
        nA = self.startNode(basedirA, beforeStart=self.disable_polling)

        basedirB = os.path.join(self.make_basedir(), "nodeB")
        self.createNode(basedirB)
        nB = self.startNode(basedirB, beforeStart=self.disable_polling)

        rclientA = list(nA.client.im)[0]
        rclientB = list(nB.client.im)[0]
        code = "code"
        nA.client.command_invite(u"petname-from-A", code)
        nB.client.command_invite(u"petname-from-B", code)

        rclientA.poll()
        rclientB.poll()

        rclientA.poll()
        rclientB.poll()

        rclientA.poll()
        rclientB.poll()

        cidAB = nA.client.command_list_addressbook()[0]["cid"]
        cidBA = nB.client.command_list_addressbook()[0]["cid"]
        return nA, nB, cidAB, cidBA
