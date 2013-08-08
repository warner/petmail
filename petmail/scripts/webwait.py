
# Tools to interact with the web port:
#  * wait for the node to start up, by polling the web port
#  * send a command and get a response

# TODO: handle 'restart' correctly by writing something into the DB to
# distinguish between the old node and the new one. Maybe.

import os, sys, time
import urllib, urlparse, httplib, json
from socket import error as socket_error
from StringIO import StringIO
from .. import database
from .runner import NoNodeError

def get_url_and_token(basedir, err):
    basedir = os.path.abspath(basedir)
    dbfile = os.path.join(basedir, "petmail.db")
    if not (os.path.isdir(basedir) and os.path.exists(dbfile)):
        raise NoNodeError(basedir)
    sqlite, db = database.get_db(dbfile, err)
    c = db.cursor()
    c.execute("SELECT webport FROM node LIMIT 1")
    (webport,) = c.fetchone()
    parts = webport.split(":")
    assert parts[0] == "tcp"
    portnum = int(parts[1])
    if portnum == 0:
        # Node has not yet chosen a port number. It needs to be started.
        return None, None
    url = "http://localhost:%d/" % portnum
    c.execute("SELECT token FROM webapi_access_tokens LIMIT 1")
    (token,) = c.fetchone()
    if not token:
        # Node has assigned a port, but not created a token. Wait longer.
        return None, None
    return url, token

def wait(basedir, err=sys.stderr):
    # returns the baseurl once it's ready
    MAX_TRIES = 1000
    tries = 0
    while tries < MAX_TRIES:
        baseurl, token = get_url_and_token(basedir, err)
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
                print >>err, "still waiting for %s to respond" % baseurl
            else:
                print >>err, "still waiting for %s to decide on a URL" % basedir

    raise RuntimeError("gave up after 100s")

# copied from twisted/web/client.py
def parse_url(url, defaultPort=None):
    url = url.strip()
    parsed = urlparse.urlparse(url)
    scheme = parsed[0]
    path = urlparse.urlunparse(('','')+parsed[2:])
    if defaultPort is None:
        if scheme == 'https':
            defaultPort = 443
        else:
            defaultPort = 80
    host, port = parsed[1], defaultPort
    if ':' in host:
        host, port = host.split(':')
        port = int(port)
    if path == "":
        path = "/"
    return scheme, host, port, path

# copied from tahoe

class BadResponse(object):
    def __init__(self, url, err):
        self.status = -1
        self.reason = "Error trying to connect to %s: %s" % (url, err)
    def read(self):
        return ""

def do_http(method, url, body=""):
    assert isinstance(body, str)
    body = StringIO(body)

    scheme, host, port, path = parse_url(url)
    if scheme == "http":
        c = httplib.HTTPConnection(host, port)
    elif scheme == "https":
        c = httplib.HTTPSConnection(host, port)
    else:
        raise ValueError("unknown scheme '%s', need http or https" % scheme)
    c.putrequest(method, path)
    c.putheader("Hostname", host)
    c.putheader("User-Agent", "petmail client")
    c.putheader("Accept", "text/plain, application/octet-stream")
    c.putheader("Connection", "close")

    old = body.tell()
    body.seek(0, os.SEEK_END)
    length = body.tell()
    body.seek(old)
    c.putheader("Content-Length", str(length))

    try:
        c.endheaders()
    except socket_error, err:
        return BadResponse(url, err)

    while True:
        data = body.read(8192)
        if not data:
            break
        c.send(data)

    return c.getresponse()

_debug_no_http = None

def command(basedir, command, args, err=sys.stderr):
    if _debug_no_http:
        return _debug_no_http(command, args)
    url, token = get_url_and_token(basedir, err)
    body = json.dumps({"token": token,
                       "method": command,
                       "args": args,
                       }).encode("utf-8")
    resp = do_http("POST", url+"api/v1/%s" % command, body)
    # the web API can return three things:
    #  200 (success) with a JSON body, including ["ok"]
    #  400 (error) with a JSON body, including ["err"]
    #  anything else (worse error) with a string body
    if resp.status == 200:
        return True, json.loads(resp.read().decode("utf-8"))
    elif resp.status == 400:
        return False, json.loads(resp.read().decode("utf-8"))
    else:
        return False, {"err": resp.read()}
