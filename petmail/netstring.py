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

def split_netstrings(s, include_trailer=False):
    p = _NetstringParser()
    p.messages = messages = []
    p.makeConnection(_EmptyTransport())
    p.dataReceived(s)
    if p._remainingData:
        if include_trailer:
            messages.append(p._remainingData)
        else:
            raise ValueError("leftover data: %d bytes" % len(p._remainingData))
    return messages
