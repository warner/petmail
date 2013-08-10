import os.path, re
from twisted.application import service, internet

class LocalDirectoryRendezvousClient(service.MultiService):
    """I manage a rendezvous server which is really just a local directory.
    This allows multiple nodes, all running in sibling basedirs on a shared
    machine, to talk to each other without a network. I add files into the
    directory for 'writes', and poll the directory for reads.
    """

    def __init__(self, basedir):
        service.MultiService.__init__(self)
        self.basedir = basedir
        if not os.path.isdir(basedir):
            os.mkdir(basedir)
        self.subscriptions = {}

    def subscribe(self, channelID):
        assert re.search(r'^\w+$', channelID)
        sdir = os.path.join(self.basedir, channelID)
        if not os.path.isdir(sdir):
            os.mkdir(sdir)
        self.subscriptions[channelID] = set()
        if len(self.subscriptions) == 1:
            self.ts = internet.TimerService(01.1, self.poll)
            self.ts.setServiceParent(self)

    def unsubscribe(self, channelID):
        del self.subscriptions[channelID]
        if not self.subscriptions:
            self.ts.disownServiceParent()
            del self.ts

    def poll(self):
        print "poll"
        new_messages = set()
        for channelID in self.subscriptions:
            sdir = os.path.join(self.basedir, channelID)
            files = set([fn for fn in os.listdir(sdir)
                         if not fn.endswith(".tmp")])
            if not (files - self.subscriptions[channelID]):
                continue
            messages = set()
            for fn in files:
                f = open(os.path.join(sdir,fn), "rb")
                messages.add(f.read())
                f.close()
            self.subscriptions[channelID] = messages
            new_messages.add(channelID)
            print "poll", channelID, new_messages
        for channelID in new_messages:
            messages = self.subscriptions[channelID]
            self.parent.messagesReceived(channelID, messages)

    def send(self, channelID, msg):
        assert re.search(r'^\w+$', channelID)
        assert re.search(r'^r0:[0-9a-f]+$', msg)
        sdir = os.path.join(self.basedir, channelID)
        if not os.path.isdir(sdir):
            os.mkdir(sdir)
        msgID = os.urandom(4).encode("hex")
        fn = os.path.join(sdir, msgID)
        f = open(fn+".tmp", "wb")
        f.write(msg)
        f.close()
        os.rename(fn+".tmp", fn)
        print "wrote %s-%s %s" % (channelID, msgID, msg)
