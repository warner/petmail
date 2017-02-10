
# I manage an HTTP mailbox server that can accept messages sent by
# petmail.mailbox.delivery.http . I define a ServerResource which accepts the
# POSTs and delivers their msgA to a Mailbox.

import os, struct, time, base64
from twisted.application import service, internet
from twisted.web import server, resource, http
from nacl.public import PrivateKey, PublicKey, Box
from nacl.secret import SecretBox
from .. import rrid
from ..eventual import eventually
from ..util import remove_prefix, split_into, hex_or_none, unhex_or_none
from ..netstring import split_netstrings_and_trailer
from ..web import EventsProtocol

def parseMsgA(msgA):
    key_and_boxed = remove_prefix(msgA, "a0:")
    pubkey1_s, boxed = split_into(key_and_boxed, [32], True)
    return pubkey1_s, boxed

def parseMsgB(msgB):
    (MSTT,),msgC = split_netstrings_and_trailer(msgB)
    return MSTT, msgC

# the Mailbox object decrypts msgA to get msgB, decrypts the TT to get a
# TTID, looks up a Transport, then dispatches msgB to the transport

# the Transport queues the message somewhere, maybe on disk.

# an HTTP "RetrievalResource" is used by remote agents to pull their
# messages from the Transport. It offers polling and subscription. The
# corresponding client code lives in mailbox.retrieval.from_http_server .

# when using mailbox.retrieval.direct_http, we don't use a RetrievalResource:
# the direct_http retriever subscribes directly to the Transport.

class ServerResource(resource.Resource):
    """I accept POSTs with msgA."""
    def __init__(self, message_handler):
        resource.Resource.__init__(self)
        self.message_handler = message_handler

    def render_POST(self, request):
        msgA = request.content.read()
        # the sender is allowed to observe the following failures:
        #  unrecognized version prefix ("a0:")
        #  message not boxed to our mailbox pubkey
        # but no others. self.messageReceived() will raise any observable
        # errors, and defer the rest of processing until later
        self.message_handler(msgA)
        return "ok"


class BaseServer(service.MultiService):
    """I am a base Petmail Mailbox Server. I accept messages from agents
    over some sort of transport (perhaps HTTP), identify which transport
    (e.g. recipient) they are aimed at, decrypt the outer msgA, and queue the
    inner msgB. Later, the recipient will come along and collect their
    messages.

    My persistent state includes: my TT private key, a list of registered
    transports (including a TTID for each, the message queue, and retrieval
    credential verifiers), and perhaps some replay-prevention state.
    """

    def __init__(self):
        service.MultiService.__init__(self)

class HTTPMailboxServer(BaseServer):
    """I am a local HTTP-based server, attached to our webapi port. I don't
    persist anything myself, but expect my creator to provide me with our
    persistent state. I can deliver messages to a local transport (endpoints
    inside our same process), or write messages to disk for later retrieval
    by remote agents.
    """

    def __init__(self, db, web, baseurl, desc):
        BaseServer.__init__(self)
        self.db = db
        assert baseurl.endswith("/")
        self.baseurl = baseurl
        self.transport_privkey = PrivateKey(desc["transport_privkey"].decode("hex"))
        self.TT_privkey = desc["TT_private_key"].decode("hex")
        self.TT_pubkey = desc["TT_public_key"].decode("hex")
        self.retrieval_privkey = PrivateKey(desc["retrieval_privkey"].decode("hex"))

        # this is how we get messages from senders
        web.get_root().putChild("mailbox", ServerResource(self.handle_msgA))

        # add a second resource for agents to retrieve messages
        r = resource.Resource()
        # TODO: retrieval should use a different key than delivery
        self.listres = RetrievalListResource(self.db, self.retrieval_privkey)
        r.putChild("list", self.listres)
        ts = internet.TimerService(self.listres.CLOCK_WINDOW*3,
                                   self.prune_old_requests)
        ts.setServiceParent(self)
        r.putChild("fetch", RetrievalFetchResource(self.db))
        r.putChild("delete", RetrievalDeleteResource(self.db))
        web.get_root().putChild("retrieval", r)

    def allocate_transport(self, remote=True):
        # return a MailboxRecord, which includes retrieval information, and
        # data which can be turned into a TransportRecord for senders
        symkey = None
        if remote:
            symkey = os.urandom(32)
        RT = os.urandom(8) # retrieval token
        TTID, TT0 = rrid.create_token(self.TT_pubkey)
        return self.add_transport(TTID, TT0, RT, symkey)

    def add_transport(self, TTID, TT0, RT, symkey):
        tid = self.db.insert("INSERT INTO mailbox_server_transports"
                             " (TTID, TT0, RT, symkey) VALUES (?,?,?,?)",
                             (TTID.encode("hex"), TT0.encode("hex"),
                              hex_or_none(RT), hex_or_none(symkey)),
                             "mailbox_server_transports")
        self.db.commit()
        return tid

    def get_local_transport(self):
        row = self.db.execute("SELECT * FROM mailbox_server_transports"
                              " WHERE symkey is NULL").fetchone()
        if not row:
            return self.allocate_transport(False)
        return row["id"]

    def get_tid_data(self, tid):
        c = self.db.execute("SELECT * FROM mailbox_server_transports"
                             " WHERE id=?", (tid,))
        row = c.fetchone()
        return (row["TTID"].decode("hex"), row["TT0"].decode("hex"),
                unhex_or_none(row["RT"]), unhex_or_none(row["symkey"]))

    def get_mailbox_record(self, tid):
        # The mailbox record goes to the recipient who owns this transport.
        # It contains both retrieval information (to collect their queued
        # messages) and data to generate transport records (to give to
        # senders).
        (TTID, TT0, RT, symkey) = self.get_tid_data(tid)
        if symkey:
            rpubkey = self.retrieval_privkey.public_key.encode()
            retrieval = {"type": "http",
                         "baseurl": self.baseurl+"retrieval/",
                         "retrieval_pubkey": rpubkey.encode("hex"),
                         "RT": RT.encode("hex"),
                         "retrieval_symkey": symkey.encode("hex"),
                         }
        else:
            retrieval = {"type": "local",
                         "RT": RT.encode("hex")}
        tpubkey = self.transport_privkey.public_key.encode()
        transport_generic = {"type": "http",
                             "url": self.baseurl+"mailbox",
                             "transport_pubkey": tpubkey.encode("hex")
                             }
        transport_sender = {"TT0": TT0.encode("hex")}
        return {"retrieval": retrieval,
                "transport": {"generic": transport_generic,
                              "sender": transport_sender}}


    def prune_old_requests(self):
        self.listres.prune_old_requests()

    def register_local_transport_handler(self, handler):
        self.local_transport_handler = handler

    def handle_msgA(self, msgA):
        pubkey1_s, boxed = parseMsgA(msgA)
        msgB = Box(self.transport_privkey, PublicKey(pubkey1_s)).decrypt(boxed)
        # this ends the sender-observable errors
        eventually(self.handle_msgB, msgB)

    def handle_msgB(self, msgB):
        MSTT, msgC = parseMsgB(msgB)
        TTID = rrid.decrypt(self.TT_privkey, MSTT)
        # look up registered transports, queue message or deliver locally
        c = self.db.execute("SELECT * FROM mailbox_server_transports"
                            " WHERE TTID=?", (TTID.encode("hex"),))
        row = c.fetchone()
        if row:
            if row["symkey"] is None:
                return self.local_transport_handler(msgC)
            else:
                return self.queue_msgC(row["id"], msgC)
        # unknown
        self.signal_unrecognized_TTID(TTID)

    def queue_msgC(self, tid, msgC):
        self.db.insert("INSERT INTO mailbox_server_messages"
                       " (tid, length, msgC) VALUES (?,?,?)",
                       (tid, len(msgC), msgC.encode("hex")),
                       "mailbox_server_messages")
        self.db.commit()

    def signal_unrecognized_TTID(self, TTID):
        # this can be overridden by unit tests
        raise KeyError("unrecognized transport identifier")

def decrypt_list_request_1(req):
    tmppub, boxed0 = req[:32], req[32:]
    return tmppub, boxed0

def decrypt_list_request_2(tmppub, boxed0, retrieval_privkey):
    nonce = "\x00"*24
    m = Box(retrieval_privkey, PublicKey(tmppub)).decrypt(boxed0, nonce)
    timestamp, RT = struct.unpack(">Q8s", m)
    return timestamp, RT

assert struct.calcsize(">Q") == 8

def create_list_entry(symkey, tmppub, length,
                      nonce=None, fetch_token=None, delete_token=None):
    assert len(tmppub) == 32
    fetch_token = fetch_token or os.urandom(32)
    delete_token = delete_token or os.urandom(32)
    msg = "list:" + struct.pack(">32s32s32sQ",
                                tmppub, fetch_token, delete_token, length)
    nonce = nonce or os.urandom(24)
    sbox = SecretBox(symkey)
    return sbox.encrypt(msg, nonce), fetch_token, delete_token

def encrypt_fetch_response(symkey, fetch_token, msgC, nonce=None):
    assert len(fetch_token) == 32
    msg = "fetch:" + fetch_token + msgC
    nonce = nonce or os.urandom(24)
    return SecretBox(symkey).encrypt(msg, nonce)

class RetrievalListResource(resource.Resource):
    CLOCK_WINDOW = 5*60 # the window is "now" plus/minus this value
    MAX_MESSAGES_PER_ENTRY = 10
    ENABLE_EVENTSOURCE = True

    def __init__(self, db, retrieval_privkey):
        resource.Resource.__init__(self)
        self.db = db
        self.retrieval_privkey = retrieval_privkey
        self.old_requests = {} # maps tmppub to timestamp
        self.db.subscribe("mailbox_server_messages", self.new_message)
        # tid -> (EventsProtocol,symkey,tmppub) . only one per tid.
        self.subscribers = {}

    def new_message(self, notice):
        if notice.action != "insert":
            return
        v = notice.new_value
        if v["tid"] not in self.subscribers:
            return
        (p, symkey, tmppub) = self.subscribers[v["tid"]]
        entry = self.prepare_entry(symkey, tmppub, v)
        p.sendEvent(base64.b64encode(entry))

    def prune_old_requests(self, now=None):
        old = (now or time.time()) - self.CLOCK_WINDOW
        old_tmppubs = []
        for tmppub, ts in self.old_requests.items():
            if ts < old:
                old_tmppubs.append(tmppub)
        for tmppub in old_tmppubs:
            del self.old_requests[tmppub]

    def render_GET(self, request):
        msg = base64.urlsafe_b64decode(request.args["t"][0])
        tmppub, boxed0 = decrypt_list_request_1(msg)
        if tmppub in self.old_requests:
            request.setResponseCode(http.BAD_REQUEST, "Replay")
            return "Replay"
        ts, RT = decrypt_list_request_2(tmppub, boxed0, self.retrieval_privkey)
        now = time.time()
        if ts < now-self.CLOCK_WINDOW or ts > now+self.CLOCK_WINDOW:
            request.setResponseCode(http.BAD_REQUEST, "too much clock skew")
            return "Too much clock skew"
        try:
            tid, symkey = self.check_RT(RT)
        except KeyError:
            request.setResponseCode(http.NOT_FOUND, "no such RT")
            return "no such RT"
        # If check_RT() didn't throw KeyError, this is a new request, for a
        # known RT. It's worth preventing a replay.
        self.old_requests[tmppub] = ts

        all_messages = self.prepare_message_list(tid, symkey, tmppub)
        groups = [all_messages[i:i+self.MAX_MESSAGES_PER_ENTRY]
                  for i in range(0, len(all_messages),
                                 self.MAX_MESSAGES_PER_ENTRY)]
        entries = [" ".join([base64.b64encode(e) for e in group])
                   for group in groups]
        if ("text/event-stream" in (request.getHeader("accept") or "")
            and self.ENABLE_EVENTSOURCE):
            # EventSource protocol
            if tid in self.subscribers:
                # close the EventsProtocol when a new GET occurs (since
                # that will reset the tokens anyways)
                self.subscribers[tid][0].stop()
            request.setHeader("content-type", "text/event-stream")
            p = EventsProtocol(request)
            p.sendComment("beginning Message List event stream")
            for e in entries:
                p.sendEvent(e)
            self.subscribers[tid] = (p, symkey, tmppub)
            # unsubscribe when the EventsProtocol is closed
            def _done(_):
                if tid in self.subscribers and self.subscribers[tid][0] is p:
                    del self.subscribers[tid]
            request.notifyFinish().addErrback(_done)
            return server.NOT_DONE_YET
        for e in entries:
            request.write("data: %s\n\n" % e)
        return ""

    def check_RT(self, RT):
        c = self.db.execute("SELECT * FROM mailbox_server_transports"
                            " WHERE RT=?", (RT.encode("hex"),))
        row = c.fetchone()
        if row:
            return (row["id"], row["symkey"].decode("hex"))
        raise KeyError("no such RT")

    def prepare_message_list(self, tid, symkey, tmppub):
        entries = []
        c = self.db.execute("SELECT id,length FROM mailbox_server_messages"
                            " WHERE tid=?", (tid,))
        for row in c.fetchall():
            entry = self.prepare_entry(symkey, tmppub, row)
            entries.append(entry)
        self.db.commit()
        return entries

    def prepare_entry(self, symkey, tmppub, c):
        entry, fetch_token, delete_token = create_list_entry(symkey, tmppub,
                                                             c["length"])
        self.db.execute("UPDATE mailbox_server_messages"
                        " SET fetch_token=?, delete_token=?"
                        " WHERE id=?",
                        (fetch_token.encode("hex"),
                         delete_token.encode("hex"),
                         c["id"]))
        return entry

class RetrievalFetchResource(resource.Resource):
    def __init__(self, db):
        resource.Resource.__init__(self)
        self.db = db

    def render_GET(self, request):
        fetch_token = base64.urlsafe_b64decode(request.args["t"][0])
        c = self.db.execute("SELECT * FROM mailbox_server_messages"
                            " WHERE fetch_token=?",
                            (fetch_token.encode("hex"),))
        row = c.fetchone()
        if row:
            c2 = self.db.execute("SELECT symkey"
                                 " FROM mailbox_server_transports"
                                 " WHERE id=?", (row["tid"],))
            symkey = c2.fetchone()["symkey"].decode("hex")
            self.db.execute("UPDATE mailbox_server_messages"
                            " SET fetch_token=NULL"
                            " WHERE id=?",
                            (row["id"],))
            self.db.commit()
            resp = encrypt_fetch_response(symkey, fetch_token,
                                          row["msgC"].decode("hex"))
            return resp
        request.setResponseCode(http.NOT_FOUND, "unknown fetch_token")
        return ""

class RetrievalDeleteResource(resource.Resource):
    def __init__(self, db):
        resource.Resource.__init__(self)
        self.db = db

    def render_POST(self, request):
        delete_token = base64.urlsafe_b64decode(request.args["t"][0])
        self.db.execute("DELETE FROM mailbox_server_messages"
                        " WHERE delete_token=?",
                        (delete_token.encode("hex"),))
        self.db.commit()
        request.setResponseCode(http.OK, "deleted")
        return ""
