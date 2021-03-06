
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
    db = database.get_db(dbfile, err)
    url = str(db.execute("SELECT baseurl FROM node LIMIT 1").fetchone()[0])
    assert url.endswith("/")
    # TODO: consider a separate localhost:listenport URL for CLI use
    c = db.execute("SELECT token FROM webapi_access_tokens LIMIT 1")
    row = c.fetchone()
    if not row:
        # Node has assigned a port, but not created a token. Wait longer.
        return None, None
    token = str(row["token"])
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

def do_http(method, url, body="", event_stream=False):
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
    if event_stream:
        c.putheader("Accept", "text/event-stream")
    else:
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
    if not url:
        return False, {"err": "Error, node is not yet running"}
    body = json.dumps({"token": token,
                       "args": args,
                       }).encode("utf-8")
    resp = do_http("POST", url+"api/%s" % command, body)
    # The web API can return three things:
    #  200 (success) with a JSON body, including ["ok"] for the CLI user
    #  400 (error) with a string body (no trailing newline)
    #  anything else (worse error) with a string body
    #
    # This CLI helper always returns the same thing: (errp,json), where
    # json["err"] is the error string (with trailing newline). Since 500s
    # usually have messy (HTML-formatted) tracebacks, we hide the body and
    # refer the user to the node logs instead. On 400s we present the whole
    # thing, since it's presumably been nicely formatted by the node already.

    http_status = "HTTP status: %d %s\n" % (resp.status, resp.reason)
    if resp.status == 200:
        return True, json.loads(resp.read().decode("utf-8"))
    elif resp.status == 400:
        return False, {"err": http_status+resp.read()+"\n"}
    else:
        return False, {"err": http_status+"Please see node logs for details\n"}

def follow_events(basedir, topic, catchup=False, err=sys.stderr):
    if _debug_no_http:
        raise RuntimeError("unit-test support not implemented yet")
    baseurl, token = get_url_and_token(basedir, err)
    if not baseurl:
        return False, {"err": "Error, node is not yet running"}
    # first, create the event channel
    resp = do_http("POST", baseurl + "api/eventchannel-create",
                   json.dumps({"token": token}))
    if resp.status != 200:
        raise RuntimeError("unable to create event channel: %s %s"
                           % (resp.status, resp.reason))
    r = json.loads(resp.read().decode("utf-8"))
    esid = r["esid"]
    # we'll listen on this one
    event_resp = do_http("GET", baseurl + "api/events/%s" % esid,
                         event_stream=True)
    # and then subscribe to hear about events. I'm not 100% sure this won't
    # race (the web frontend specifically waits until a "ready" event is
    # delivered, to make sure the browser has established the EventSource
    # channel, before subscribing to anything. We're ok as long as do_http()
    # doesn't return until after it's seen the HTTP headers.
    resp = do_http("POST", baseurl + "api/eventchannel-subscribe",
                   json.dumps({"token": token,
                               "args": {"esid": esid,
                                        "topic": topic,
                                        "catchup": catchup}}))
    if resp.status != 200:
        raise RuntimeError("unable to subscribe to event channel: %s %s"
                           % (resp.status, resp.reason))

    return event_resp

class EOFError(Exception):
    pass

def get_line(r):
    buf = ""
    while True:
        data = r.read(1)
        if not data:
            raise EOFError
        if data == "\n":
            return buf
        buf += data

def get_field(r):
    first_line = get_line(r)
    fieldname, data = first_line.split(": ", 1)
    lines = [data]
    while True:
        line = get_line(r)
        if not line:
            return fieldname, "\n".join(lines)
        lines.append(line)
