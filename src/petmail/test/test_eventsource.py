from twisted.trial import unittest
from ..eventsource import EventSourceParser

class FakeTransport:
    disconnecting = False

def parse_events(s):
    fields = []
    p = EventSourceParser(lambda name, data: fields.append((name,data)))
    p.makeConnection(FakeTransport())
    p.dataReceived(s)
    return fields

class EventSource(unittest.TestCase):
    def test_parse(self):
        fields = []
        p = EventSourceParser(lambda name, data: fields.append((name,data)))
        p.makeConnection(FakeTransport())
        self.failUnlessEqual(fields, [])
        p.dataReceived(": comment")
        self.failUnlessEqual(fields, [])
        p.dataReceived("\n")
        self.failUnlessEqual(fields, [])
        p.dataReceived("\n")
        self.failUnlessEqual(fields, [("", "comment")])

        p.dataReceived("data: one line\n\n")
        self.failUnlessEqual(fields, [("", "comment"),
                                      ("data", "one line")])

        p.dataReceived("data: two\n")
        self.failUnlessEqual(fields, [("", "comment"),
                                      ("data", "one line")])
        p.dataReceived("lines\n")
        self.failUnlessEqual(fields, [("", "comment"),
                                      ("data", "one line")])
        p.dataReceived("\n")
        self.failUnlessEqual(fields, [("", "comment"),
                                      ("data", "one line"),
                                      ("data", "two\nlines"),
                                      ])
