
# wait for the node to start up, by polling the web port

# TODO: handle 'restart' correctly by writing something into the DB to
# distinguish between the old node and the new one. Maybe.

import os, sys
import urllib, time
from .. import database

def get_url(basedir, err):
    basedir = os.path.abspath(basedir)
    dbfile = os.path.join(basedir, "petmail.db")
    if not (os.path.isdir(basedir) and os.path.exists(dbfile)):
        print >>err, "'%s' doesn't look like a Petmail basedir, quitting" % basedir
        return 1
    sqlite, db = database.get_db(dbfile, err)
    c = db.cursor()
    c.execute("SELECT webport FROM node LIMIT 1")
    (webport,) = c.fetchone()
    parts = webport.split(":")
    assert parts[0] == "tcp"
    portnum = int(parts[1])
    if portnum == 0:
        return None
    return "http://localhost:%d/" % portnum

def wait(basedir, err=sys.stderr):
    # returns the baseurl once it's ready
    MAX_TRIES = 1000
    tries = 0
    while tries < MAX_TRIES:
        baseurl = get_url(basedir, err)
        try:
            if baseurl:
                urllib.urlopen(baseurl)
                return baseurl
        except IOError:
            pass
        time.sleep(0.1)
        tries += 1
        if tries % 30 == 0:
            if baseurl:
                print "still waiting for %s to respond" % baseurl
            else:
                print "still waiting for %s to decide on a URL" % basedir

    raise RuntimeError("gave up after 100s")
