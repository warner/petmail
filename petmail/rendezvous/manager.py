
from twisted.application import service

class RendezvousManager(service.MultiService):

    def addRendezvousService(self, rs):
        rs.setServiceParent(self)

    def subscribe(self, channelID):
        for rs in list(self):
            rs.subscribe(channelID)
    def messagesReceived(self, channelID, messages):
        self.parent.rendezvousMessagesReceived(channelID, messages)

    def send(self, channelID, msg):
        for rs in list(self):
            rs.send(channelID, msg)


