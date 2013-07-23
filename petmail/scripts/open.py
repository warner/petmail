
import os
import webbrowser
from . import webwait
from .. import database, util

def open_control_panel(so, out, err):
    basedir = os.path.abspath(so["basedir"])
    dbfile = os.path.join(basedir, "petmail.db")
    if not (os.path.isdir(basedir) and os.path.exists(dbfile)):
        print >>err, "'%s' doesn't look like a Petmail basedir, quitting" % basedir
        return 1
    sqlite, db = database.get_db(dbfile, err)
    c = db.cursor()
    baseurl = webwait.wait(basedir, err)
    print "Node appears to be running, opening browser"
    c.execute("SELECT name FROM services")
    services = set([str(row[0]) for row in c.fetchall()])
    if "relay" in services:
        url = baseurl+"relay"
    else:
        n = util.make_nonce()
        c.execute("INSERT INTO webui_initial_nonces VALUES (?)", (n,))
        db.commit()
        url = baseurl+"control?nonce=%s" % n
    if so["no-open"]:
        print >>out, "Please open: %s" % url
    else:
        webbrowser.open(url)
