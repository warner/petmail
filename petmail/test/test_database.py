import os.path
from twisted.trial import unittest
from common import BasedirMixin
from ..eventual import flushEventualQueue
from ..database import get_db, make_observable_db

class Database(BasedirMixin, unittest.TestCase):
    def test_create(self):
        basedir = self.make_basedir()
        dbfile = os.path.join(basedir, "test.db")
        db = get_db(dbfile)

        row = db.execute("SELECT * FROM version").fetchone()
        self.failUnlessEqual(row["version"], 1)

    def test_observable(self):
        basedir = self.make_basedir()
        dbfile = os.path.join(basedir, "test.db")
        db = make_observable_db(dbfile)

        n = []
        db.subscribe("inbound_messages", n.append)

        # nobody is watching this table
        mid = db.insert("INSERT INTO mailboxes (mailbox_record_json)"
                        " VALUES (?)", ("desc",),
                        "mailboxes")
        self.failUnlessEqual(mid, 1)
        # and this one doesn't even have an 'id' column
        db.insert("INSERT INTO services (name) VALUES (?)", ("name",))
        # but this one is observed
        imid = db.insert("INSERT INTO inbound_messages"
                         " (cid, seqnum, payload_json)"
                         " VALUES (?,?,?)", (4, 9, "payload"),
                         "inbound_messages")
        self.failUnlessEqual(n, [])
        db.commit()
        self.failUnlessEqual(n, [])
        d = flushEventualQueue()
        def _then(_):
            self.failUnlessEqual(len(n), 1)
            n0 = n.pop(0)
            self.failUnlessEqual(n0.table, "inbound_messages")
            self.failUnlessEqual(n0.action, "insert")
            self.failUnlessEqual(n0.id, imid)
            self.failUnlessEqual(n0.new_value["seqnum"], 9)

            db.update("UPDATE inbound_messages SET seqnum=10"
                      " WHERE id=?", (imid,),
                      "inbound_messages", imid)
            db.delete("DELETE FROM inbound_messages WHERE id=?", (imid,),
                      "inbound_messages", imid)
            self.failUnlessEqual(len(n), 0)
            db.commit()
            self.failUnlessEqual(len(n), 0)
            return flushEventualQueue()
        d.addCallback(_then)
        def _then2(_):
            self.failUnlessEqual(len(n), 2)
            n1 = n.pop(0)
            self.failUnlessEqual(n1.table, "inbound_messages")
            self.failUnlessEqual(n1.action, "update")
            self.failUnlessEqual(n1.id, imid)
            self.failUnlessEqual(n1.new_value["seqnum"], 10)
            n2 = n.pop(0)
            self.failUnlessEqual(n2.table, "inbound_messages")
            self.failUnlessEqual(n2.action, "delete")
            self.failUnlessEqual(n2.id, imid)
            self.failUnlessEqual(n2.new_value, None)
            db.unsubscribe("inbound_messages", n.append)
            db.insert("INSERT INTO inbound_messages"
                      " (cid, seqnum, payload_json)"
                      " VALUES (?,?,?)", (6, 2, "ignoreme"),
                      "inbound_messages")
            db.commit()
            return flushEventualQueue()
        d.addCallback(_then2)
        def _then3(_):
            self.failUnlessEqual(len(n), 0)
        d.addCallback(_then3)
        
        return d
    
            
        
