from twisted.protocols.basic import NetstringReceiver

class _EmptyTransport:
    def loseConnection(self):
        pass
class _NetstringParser(NetstringReceiver):
    def stringReceived(self, msg):
        self.messages.append(msg)

def netstring(msg):
    assert isinstance(msg, str)
    return "%d:%s," % (len(msg), msg)

def split_netstrings(s):
    p = _NetstringParser()
    p.messages = messages = []
    p.makeConnection(_EmptyTransport())
    p.dataReceived(s)
    if p._remainingData:
        raise ValueError("leftover data: %d bytes" % len(p._remainingData))
    return messages

def split_netstrings_and_trailer(s):
    p = _NetstringParser()
    p.messages = messages = []
    p.makeConnection(_EmptyTransport())
    p.dataReceived(s)
    return (messages, p._remainingData)
