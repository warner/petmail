
import os
import webbrowser
from . import webwait
from .. import database, util

def open_control_panel(so, out, err):
    basedir = os.path.abspath(so["basedir"])
    baseurl = webwait.wait(basedir, err) # also checks for the database
    print >>out, "Node appears to be running, opening browser"

    dbfile = os.path.join(basedir, "petmail.db")
    db = database.get_db(dbfile, err)

    token = util.make_nonce()
    db.execute("INSERT INTO webapi_opener_tokens VALUES (?)", (token,))
    db.commit()
    url = baseurl+"open-control?opener-token=%s" % token
    if so["no-open"]:
        print >>out, "Please open: %s" % url
    else:
        webbrowser.open(url)
    return 0
