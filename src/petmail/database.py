
import os, sys
from collections import defaultdict, namedtuple
import sqlite3
from .eventual import eventually

Notice = namedtuple("Notice", ["table", "action", "id", "new_value", "tags"])

class DBError(Exception):
    pass

def get_schema(version):
    schema_fn = os.path.join(os.path.dirname(__file__),
                             "db-schemas", "v%d.sql" % version)
    return open(schema_fn, "r").read()

def serialize(row):
    if row is None:
        return None
    out = {}
    for k in row.keys():
        out[k] = row[k]
    return out

class ObservableDatabase:
    def __init__(self, connection):
        self.conn = connection
        self.observers = defaultdict(list)
        self.pending_notifications = []

    def subscribe(self, table, observer):
        self.observers[table].append(observer)

    def unsubscribe(self, table, observer):
        self.observers[table].remove(observer)

    # database methods

    def execute(self, sql, values=None):
        if values:
            return self.conn.execute(sql, values)
        return self.conn.execute(sql)

    def insert(self, sql, values, table=None, tags={}):
        new_id = self.conn.execute(sql, values).lastrowid
        if table:
            c = self.conn.execute("SELECT * FROM `%s` WHERE id=?" % table,
                                  (new_id,))
            self.pending_notifications.append(Notice(table, "insert", new_id,
                                                     serialize(c.fetchone()),
                                                     tags))
        return new_id

    def update(self, sql, values, table=None, id=None, tags={}):
        self.conn.execute(sql, values)
        if table:
            c = self.conn.execute("SELECT * FROM `%s` WHERE id=?" % table,
                                  (id,))
            new_value = serialize(c.fetchone())
            if new_value:
                self.pending_notifications.append(Notice(table, "update", id,
                                                         new_value, tags))

    def delete(self, sql, values, table, id, tags={}):
        self.conn.execute(sql, values)
        self.pending_notifications.append(Notice(table, "delete", id,
                                                 None, tags))

    def commit(self):
        self.conn.commit()
        for event in self.pending_notifications:
            for o in self.observers[event.table]:
                eventually(o, event)
        self.pending_notifications[:] = []

def get_db(dbfile, stderr=sys.stderr):
    """Open or create the given db file. The parent directory must exist.
    Returns the db connection object, or raises DBError.
    """

    must_create = not os.path.exists(dbfile)
    try:
        db = sqlite3.connect(dbfile)
    except (EnvironmentError, sqlite3.OperationalError), e:
        raise DBError("Unable to create/open db file %s: %s" % (dbfile, e))
    db.row_factory = sqlite3.Row

    VERSION = 1
    if must_create:
        schema = get_schema(VERSION)
        db.executescript(schema)
        db.execute("INSERT INTO version (version) VALUES (?)", (VERSION,))
        db.commit()

    try:
        version = db.execute("SELECT version FROM version").fetchone()[0]
    except sqlite3.DatabaseError, e:
        # this indicates that the file is not a compatible database format.
        # Perhaps it was created with an old version, or it might be junk.
        raise DBError("db file is unusable: %s" % e)

    if version != VERSION:
        raise DBError("Unable to handle db version %s" % version)

    return db

def make_observable_db(dbfile, stderr=sys.stderr):
    return ObservableDatabase(get_db(dbfile, stderr))
