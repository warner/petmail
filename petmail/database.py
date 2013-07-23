
import os, sys
import sqlite3 as sqlite

class DBError(Exception):
    pass

def get_schema(version):
    schema_fn = os.path.join(os.path.dirname(__file__),
                             "db-schemas", "v%d.sql" % version)
    return open(schema_fn, "r").read()


def get_db(dbfile, stderr=sys.stderr):
    """Open or create the given db file. The parent directory must exist.
    Returns a (sqlite,db) tuple, or raises DBError.
    """

    must_create = not os.path.exists(dbfile)
    try:
        db = sqlite.connect(dbfile)
    except (EnvironmentError, sqlite.OperationalError), e:
        raise DBError("Unable to create/open db file %s: %s" % (dbfile, e))

    VERSION = 1
    c = db.cursor()
    if must_create:
        schema = get_schema(VERSION)
        c.executescript(schema)
        c.execute("INSERT INTO version (version) VALUES (?)", (VERSION,))
        db.commit()

    try:
        c.execute("SELECT version FROM version")
        version = c.fetchone()[0]
    except sqlite.DatabaseError, e:
        # this indicates that the file is not a compatible database format.
        # Perhaps it was created with an old version, or it might be junk.
        raise DBError("db file is unusable: %s" % e)

    if version != VERSION:
        raise DBError("Unable to handle db version %s" % version)

    return (sqlite, db)
