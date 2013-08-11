import os.path, shutil
from collections import defaultdict
from twisted.application import service, internet
from ..invitation import VALID_CHANNELID, VALID_MESSAGE
from nacl.signing import VerifyKey

# this is allowed to do seen-message-stripping as an optimization, but is not
# required to do so. It is not required to check version numbers ("r0:") or
# signatures.

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
        self.subscriptions = {} # channelID -> processed messages
        # destroyRequestsSeen maps channelID -> set(destroy messages)
        self.destroyRequestsSeen = defaultdict(set)
        self.verfkeys = {}
        self.enable_polling = True # disabled by some unit tests

    def subscribe(self, channelID):
        assert VALID_CHANNELID.search(channelID), channelID
        self.verfkeys[channelID] = VerifyKey(channelID.decode("hex"))
        sdir = os.path.join(self.basedir, channelID)
        if not os.path.isdir(sdir):
            os.mkdir(sdir)
        self.subscriptions[channelID] = set()
        if len(self.subscriptions) == 1 and self.enable_polling:
            self.ts = internet.TimerService(01.1, self.poll)
            self.ts.setServiceParent(self)

    def unsubscribe(self, channelID):
        del self.subscriptions[channelID]
        del self.verfkeys[channelID]
        self.destroyRequestsSeen.pop(channelID, None)
        if not self.subscriptions and self.enable_polling:
            self.ts.disownServiceParent()
            del self.ts

    def poll(self):
        print "entering poll"
        channels_with_new_messages = set()
        for channelID in self.subscriptions:
            sdir = os.path.join(self.basedir, channelID)
            if not os.path.exists(sdir):
                print "warning: polling non-existent channel", channelID
                continue
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
            channels_with_new_messages.add(channelID)
            print "poll got new messages for", channelID
        for channelID in channels_with_new_messages:
            messages = self.subscriptions[channelID]
            assert channelID in self.verfkeys, (self.subscriptions.keys(), self.verfkeys.keys())
            # Before giving the messages to the Invitation (which may
            # unsubscribe us), update our 'destroy' message counts. Since the
            # localdir scheme doesn't have a central server, we must do this
            # on each client. This is where Alice discovers Bob's destroy
            # message.
            for rawmsg in messages:
                assert rawmsg.startswith("r0:")
                sm = rawmsg[len("r0:"):].decode("hex")
                m = self.verfkeys[channelID].verify(sm)
                if m.startswith("i0:destroy:"):
                    self.destroyRequestsSeen[channelID].add(m)
            # The two-destroy-message condition should only occur just after
            # Alice's localdir client writes the second one, and won't be
            # observed by poll(). So it's sufficient to merely add the
            # messages here, and count them in send() instead.

            self.parent.messagesReceived(channelID, messages)

    def send(self, channelID, msg):
        assert channelID in self.subscriptions
        assert VALID_CHANNELID.search(channelID), channelID
        assert VALID_MESSAGE.search(msg), msg
        sdir = os.path.join(self.basedir, channelID)
        if not os.path.isdir(sdir):
            os.mkdir(sdir)
        msgID = os.urandom(4).encode("hex")
        fn = os.path.join(sdir, msgID)
        f = open(fn+".tmp", "wb")
        f.write(msg)
        f.close()
        os.rename(fn+".tmp", fn)
        print " localdir wrote %s-%s %s" % (channelID, msgID, msg)

        # was it a destroy? Alice writes the second destroy message, then
        # stops polling, so we can't rely on self.poll() to notice it. We
        # have to act when she writes that destroy message.
        assert msg.startswith("r0:")
        sm = msg[len("r0:"):].decode("hex")
        m = self.verfkeys[channelID].verify(sm)
        if m.startswith("i0:destroy:"):
            self.destroyRequestsSeen[channelID].add(m)
        if len(self.destroyRequestsSeen[channelID]) >= 2:
            print "DESTROY CHANNEL", channelID
            shutil.rmtree(sdir)
            del self.destroyRequestsSeen[channelID]
