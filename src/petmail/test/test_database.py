import os.path
from twisted.trial import unittest
from common import BasedirMixin
from ..eventual import flushEventualQueue
from ..database import get_db, make_observable_db, DBError

class Database(BasedirMixin, unittest.TestCase):
    def test_create(self):
        basedir = self.make_basedir()
        dbfile = os.path.join(basedir, "test.db")
        db = get_db(dbfile)

        row = db.execute("SELECT * FROM version").fetchone()
        self.failUnlessEqual(row["version"], 1)

    def test_create_failure(self):
        bad_dbfile = "missing/directory/test.db"
        err = self.failUnlessRaises(DBError, get_db, bad_dbfile)
        self.failUnlessIn("Unable to create/open db file", str(err))
        self.failUnlessIn("unable to open database file", str(err))

    def test_versions(self):
        basedir = self.make_basedir()
        dbfile = os.path.join(basedir, "test.db")
        db = get_db(dbfile)

        db.execute("UPDATE version SET version=2")
        db.commit()
        err = self.failUnlessRaises(DBError, get_db, dbfile)
        self.failUnlessEqual("Unable to handle db version 2",
                             str(err))

        db.execute("DROP TABLE version")
        db.commit()
        err = self.failUnlessRaises(DBError, get_db, dbfile)
        self.failUnlessEqual("db file is unusable: no such table: version",
                             str(err))

    def test_coercion(self):
        # if sqlite doesn't recognize a column type in the schema, it
        # defaults to some curious value which attempts to automatically
        # determine the item's type. If you store a string like "0123" into
        # such a row, it will come back out as an int or a long like 123,
        # which is kind of horrible. "STRING" is not recognized, but "BLOB"
        # or "VARCHAR" or "VARCHAR(100)" avoid the coercion.

        basedir = self.make_basedir()
        dbfile = os.path.join(basedir, "test.db")
        db = get_db(dbfile)

        db.execute("INSERT INTO services (name) VALUES (?)", ("0123",))
        db.commit()
        row = db.execute("SELECT * FROM services").fetchone()
        v = row["name"]
        self.failUnlessEqual(type(v), unicode, repr((v, type(v))))

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
                         "inbound_messages", {"tag1": "v1"})
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
            self.failUnlessEqual(n0.tags, {"tag1": "v1"})

            db.update("UPDATE inbound_messages SET seqnum=10"
                      " WHERE id=?", (imid,),
                      "inbound_messages", imid, {"tag2": "v2"})
            db.delete("DELETE FROM inbound_messages WHERE id=?", (imid,),
                      "inbound_messages", imid, {"tag3": "v3"})
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
            self.failUnlessEqual(n1.tags, {"tag2": "v2"})
            n2 = n.pop(0)
            self.failUnlessEqual(n2.table, "inbound_messages")
            self.failUnlessEqual(n2.action, "delete")
            self.failUnlessEqual(n2.id, imid)
            self.failUnlessEqual(n2.new_value, None)
            self.failUnlessEqual(n2.tags, {"tag3": "v3"})
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
