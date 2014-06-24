import json, copy, base64, time
from twisted.trial import unittest
from twisted.web import http, client
from twisted.web.test.test_web import DummyRequest # not exactly stable
from twisted.internet import defer
from .common import TwoNodeMixin
from .. import rrid, eventsource
from ..database import Notice
from ..eventual import flushEventualQueue
from ..mailbox import delivery, retrieval
from .test_eventsource import parse_events

class Inbound(TwoNodeMixin, unittest.TestCase):
    def test_unknown_TTID(self):
        nA, nB, entA, entB = self.make_connected_nodes(transport="local")
        msgC = "msgC"
        trec = json.loads(entA["their_channel_record_json"])["transports"][0]
        bad_trec = copy.deepcopy(trec)
        TT_privkey, TT_pubkey = rrid.create_keypair()
        TTID, TT0 = rrid.create_token(TT_pubkey)
        bad_STT = rrid.randomize(TT0)
        bad_trec["STT"] = bad_STT.encode("hex")
        msgA = delivery.createMsgA(bad_trec, msgC)

        unknowns = []
        server = nB.agent.mailbox_server
        server.signal_unrecognized_TTID = unknowns.append
        server.handle_msgA(msgA)
        d = flushEventualQueue()
        def _then(res):
            self.failUnlessEqual(len(unknowns), 1)
            c = nB.db.execute("SELECT * FROM mailbox_server_messages")
            messages = c.fetchall()
            self.failUnlessEqual(len(messages), 0)
        d.addCallback(_then)
        return d

    def test_local_TTID(self):
        nA, nB, entA, entB = self.make_connected_nodes(transport="local")
        msgC = "msgC"
        trec = json.loads(entA["their_channel_record_json"])["transports"][0]
        msgA = delivery.createMsgA(trec, msgC)
        server = nB.agent.mailbox_server
        local_messages = []
        server.local_transport_handler = local_messages.append
        server.handle_msgA(msgA)
        d = flushEventualQueue()
        def _then(res):
            c = nB.db.execute("SELECT * FROM mailbox_server_messages")
            messages = c.fetchall()
            self.failUnlessEqual(len(messages), 0)
            self.failUnlessEqual(len(local_messages), 1)
            self.failUnlessEqual(local_messages[0], msgC)
        d.addCallback(_then)
        return d

    def test_nonlocal_TTID(self):
        n = self.make_nodes(transport="local")[1]
        msgC = "msgC"
        server = n.agent.mailbox_server

        tid, trec = self.add_recipient(n)
        msgA = delivery.createMsgA(trec, msgC)

        local_messages = []
        server.local_transport_handler = local_messages.append
        server.handle_msgA(msgA)

        d = flushEventualQueue()
        def _then(res):
            self.failUnlessEqual(len(local_messages), 0)
            c = n.db.execute("SELECT * FROM mailbox_server_messages")
            messages = c.fetchall()
            self.failUnlessEqual(len(messages), 1)
            self.failUnlessEqual(messages[0]["tid"], tid)
            self.failUnlessEqual(messages[0]["length"], len(msgC))
            self.failUnlessEqual(messages[0]["msgC"].decode("hex"), msgC)
        d.addCallback(_then)
        return d

    def test_two_nonlocal_TTID(self):
        # this errored, CannotListenError, EADDRINUSE
        n = self.make_nodes(transport="local")[1]
        tid1, trec1 = self.add_recipient(n)
        tid2, trec2 = self.add_recipient(n)

        msg1 = delivery.createMsgA(trec1, "msgC1")
        n.mailbox_server.handle_msgA(msg1)

        msg2 = delivery.createMsgA(trec2, "msgC2")
        n.mailbox_server.handle_msgA(msg2)

        d = flushEventualQueue()

        def _then(_):
            c = n.db.execute("SELECT * FROM mailbox_server_messages"
                             " WHERE tid=?", (tid1,))
            messages = c.fetchall()
            self.failUnlessEqual(len(messages), 1)
            self.failUnlessEqual(messages[0]["msgC"].decode("hex"), "msgC1")

            c = n.db.execute("SELECT * FROM mailbox_server_messages"
                             " WHERE tid=?", (tid2,))
            messages = c.fetchall()
            self.failUnlessEqual(len(messages), 1)
            self.failUnlessEqual(messages[0]["msgC"].decode("hex"), "msgC2")
        d.addCallback(_then)
        return d

def do_request(resource, t=None, method="GET"):
    req = DummyRequest([])
    req.method = method
    req.args = {}
    if t:
        req.args["t"] = [t]
    req.render(resource)
    return "".join(req.written), req

class Retrieval(TwoNodeMixin, unittest.TestCase):
    def test_resource(self):
        n = self.make_nodes(transport="local")[1]
        ms = n.mailbox_server
        tid1, trec1 = self.add_recipient(n)
        tid2, trec2 = self.add_recipient(n)
        TTID_1, TT0_1, RT_1, symkey_1 = ms.get_tid_data(tid1)
        TTID_2, TT0_2, RT_2, symkey_2 = ms.get_tid_data(tid2)

        ms.queue_msgC(tid1, "msgC1_first")
        ms.queue_msgC(tid1, "msgC1_second")
        ms.queue_msgC(tid2, "msgC2")

        c = n.db.execute("SELECT * FROM mailbox_server_messages"
                         " WHERE tid=?", (tid1,))
        messages = c.fetchall()
        self.failUnlessEqual(len(messages), 2)
        bodies = set([m["msgC"].decode("hex") for m in messages])
        self.failUnlessEqual(bodies, set(["msgC1_first", "msgC1_second"]))

        listres = ms.listres

        retrieval_pubkey = trec1["retrieval_pubkey"].decode("hex")
        reqkey, tmppub = retrieval.encrypt_list_request(retrieval_pubkey, RT_1)

        # test 'list'
        out,req = do_request(listres, base64.urlsafe_b64encode(reqkey))
        # that created the tokens, so now we check the DB
        messages = n.db.execute("SELECT * FROM mailbox_server_messages"
                                " WHERE tid=? ORDER BY id",
                                (tid1,)).fetchall()
        self.failUnlessEqual(len(messages), 2)

        self.failUnless(out.startswith("data: "), out)
        self.failUnless(out.endswith("\n\n"), out)
        fields = parse_events(out)
        self.failUnlessEqual(len(fields), 1)
        self.failUnlessEqual(fields[0][0], "data")
        responses = fields[0][1].split()

        r1 = base64.b64decode(responses[0])
        (fetch_token1, delete_token1, length1) = \
                       retrieval.decrypt_list_entry(r1, symkey_1, tmppub)
        self.failUnlessEqual(length1, len("msgC1_first"))
        self.failUnlessEqual(str(messages[0]["fetch_token"]),
                             fetch_token1.encode("hex"))
        self.failUnlessEqual(str(messages[0]["delete_token"]),
                             delete_token1.encode("hex"))
        self.failUnlessEqual(messages[0]["length"], length1)

        r2 = base64.b64decode(responses[1])
        (fetch_token2, delete_token2,
         length2) = retrieval.decrypt_list_entry(r2, symkey_1, tmppub)
        self.failUnlessEqual(length2, len("msgC1_second"))
        self.failUnlessEqual(str(messages[1]["fetch_token"]),
                             fetch_token2.encode("hex"))
        self.failUnlessEqual(str(messages[1]["delete_token"]),
                             delete_token2.encode("hex"))
        self.failUnlessEqual(messages[1]["length"], length2)

        r = n.web.get_root().getStaticEntity("retrieval")
        fetchres = r.getStaticEntity("fetch")
        deleteres = r.getStaticEntity("delete")

        # test 'fetch' on the first message
        out, req = do_request(fetchres,
                              base64.urlsafe_b64encode(fetch_token1))
        encrypted_m1 = out
        m1 = retrieval.decrypt_fetch_response(symkey_1, fetch_token1,
                                              encrypted_m1)
        self.failUnlessEqual(m1, "msgC1_first")

        # fetch_token is single-use
        out, req = do_request(fetchres,
                              base64.urlsafe_b64encode(fetch_token1))
        self.failUnlessEqual(req.responseCode, http.NOT_FOUND)
        self.failUnlessEqual(req.responseMessage, "unknown fetch_token")
        self.failUnlessEqual(out, "")
        messages = n.db.execute("SELECT * FROM mailbox_server_messages"
                                " WHERE tid=? ORDER BY id",
                                (tid1,)).fetchall()
        self.failUnlessEqual(len(messages), 2)
        self.failUnlessEqual(messages[0]["fetch_token"], None)

        # test delete_token
        out, req = do_request(deleteres,
                              base64.urlsafe_b64encode(delete_token1),
                              method="POST")
        self.failUnlessEqual(req.responseCode, http.OK)
        self.failUnlessEqual(out, "")
        messages = n.db.execute("SELECT * FROM mailbox_server_messages"
                                " WHERE tid=? ORDER BY id",
                                (tid1,)).fetchall()
        self.failUnlessEqual(len(messages), 1)

        # replay should be rejected
        out,req = do_request(listres, base64.urlsafe_b64encode(reqkey))
        self.failUnlessEqual(req.responseCode, http.BAD_REQUEST)

        # test unknown tokens
        out,req = do_request(fetchres, base64.urlsafe_b64encode("wrong"))
        self.failUnlessEqual(req.responseCode, 404)
        self.failUnlessEqual(req.responseMessage, "unknown fetch_token")
        self.failUnlessEqual(out, "")

        # timestamp in past (old replay)
        now = time.time()
        past = now - 24*3600
        future = now + 24*3600
        reqkey, tmppub = retrieval.encrypt_list_request(retrieval_pubkey,
                                                        RT_1, now=past)
        out,req = do_request(listres, base64.urlsafe_b64encode(reqkey))
        self.failUnlessEqual(req.responseCode, http.BAD_REQUEST)
        self.failUnlessEqual(req.responseMessage, "too much clock skew")
        self.failUnlessEqual(out, "Too much clock skew")

        # timestamp in future
        reqkey, tmppub = retrieval.encrypt_list_request(retrieval_pubkey,
                                                        RT_1, now=future)
        out,req = do_request(listres, base64.urlsafe_b64encode(reqkey))
        self.failUnlessEqual(req.responseCode, http.BAD_REQUEST)
        self.failUnlessEqual(req.responseMessage, "too much clock skew")
        self.failUnlessEqual(out, "Too much clock skew")

        self.failUnlessEqual(len(listres.old_requests), 1)
        listres.prune_old_requests(now=future)
        self.failUnlessEqual(len(listres.old_requests), 0)

        # unrecognized RT, causing KeyError (or nicer)
        unknown_RT = "unknown0" # 8 bytes
        reqkey, tmppub = retrieval.encrypt_list_request(retrieval_pubkey,
                                                        unknown_RT)
        out,req = do_request(listres, base64.urlsafe_b64encode(reqkey))
        self.failUnlessEqual(req.responseCode, http.NOT_FOUND)
        self.failUnlessEqual(req.responseMessage, "no such RT")
        self.failUnlessEqual(out, "no such RT")

        # since none of those "list" requests were accepted, the fetch_token2
        # should still be valid. We don't spend it now, to test how a second
        # "list" should cancel it.
        messages = n.db.execute("SELECT * FROM mailbox_server_messages"
                                " WHERE tid=? ORDER BY id",
                                (tid1,)).fetchall()
        self.failUnlessEqual(len(messages), 1)
        self.failUnlessEqual(messages[0]["fetch_token"],
                             fetch_token2.encode("hex"))
        # a second 'list' should revoke tokens from the first
        reqkey, tmppub = retrieval.encrypt_list_request(retrieval_pubkey, RT_1)
        out,req = do_request(listres, base64.urlsafe_b64encode(reqkey))
        messages = n.db.execute("SELECT * FROM mailbox_server_messages"
                                " WHERE tid=? ORDER BY id",
                                (tid1,)).fetchall()
        self.failUnlessEqual(len(messages), 1)
        self.failIfEqual(messages[0]["fetch_token"],
                         fetch_token2.encode("hex"))

    def GET(self, url):
        return client.getPage(url, method="GET",
                              headers={"accept": "application/json"})
    def POST(self, url, data):
        return client.getPage(url, method="POST", postdata=data,
                              headers={"accept": "application/json",
                                       "content-type": "application/json"})

    def test_web_list(self):
        n = self.make_nodes(transport="local")[1]
        ms = n.mailbox_server
        tid1, trec1 = self.add_recipient(n)
        tid2, trec2 = self.add_recipient(n)
        TTID_1, TT0_1, RT_1, symkey_1 = ms.get_tid_data(tid1)
        #TTID_2, TT0_2, RT_2, symkey_2 = ms.get_tid_data(tid2)

        ms.queue_msgC(tid1, "msgC1_first")
        ms.queue_msgC(tid1, "msgC1_second")
        ms.queue_msgC(tid2, "msgC2")

        baseurl = n.baseurl + "retrieval/"

        retrieval_pubkey = trec1["retrieval_pubkey"].decode("hex")
        reqkey, tmppub = retrieval.encrypt_list_request(retrieval_pubkey, RT_1)
        d = self.GET(baseurl+"list?t="+base64.urlsafe_b64encode(reqkey))
        def _then1(res):
            fields = parse_events(res)
            self.failUnlessEqual(len(fields), 1)
            self.failUnlessEqual(fields[0][0], "data")
            responses = fields[0][1].split()
            r1 = base64.b64decode(responses[0])
            (fetch_token1, delete_token1, length1) = \
                           retrieval.decrypt_list_entry(r1, symkey_1, tmppub)
            self.failUnlessEqual(length1, len("msgC1_first"))
        d.addCallback(_then1)
        return d

    def test_web_events(self):
        n = self.make_nodes(transport="local")[1]
        ms = n.mailbox_server
        tid1, trec1 = self.add_recipient(n)
        tid2, trec2 = self.add_recipient(n)
        TTID_1, TT0_1, RT_1, symkey_1 = ms.get_tid_data(tid1)
        TTID_2, TT0_2, RT_2, symkey_2 = ms.get_tid_data(tid2)

        ms.queue_msgC(tid1, "msgC1_first")
        ms.queue_msgC(tid1, "msgC1_second")
        ms.queue_msgC(tid2, "msgC2")

        baseurl = n.baseurl + "retrieval/"

        retrieval_pubkey = trec1["retrieval_pubkey"].decode("hex")
        reqkey, tmppub = retrieval.encrypt_list_request(retrieval_pubkey, RT_1)
        # test streaming/EventSource: new messages should trigger events
        url = baseurl+"list?t="+base64.urlsafe_b64encode(reqkey)

        fields = []
        def handler(name, data):
            fields.append( (name,data) )
        def check_f(min_fields):
            if len(fields) < min_fields:
                return False
            return True

        es = eventsource.EventSource(url, handler)
        finished_d = es.start()
        d = self.poll(lambda: check_f(2))
        def _then1(_):
            self.failUnlessEqual(len(fields), 2)
            self.failUnlessEqual(fields[0][0], "") # comment
            self.failUnlessEqual(fields[1][0], "data")
            responses = fields[1][1].split()
            self.failUnlessEqual(len(responses), 2)
            r1 = base64.b64decode(responses[0])
            (fetch_token1, delete_token1, length1) = \
                           retrieval.decrypt_list_entry(r1, symkey_1, tmppub)
            self.failUnlessEqual(length1, len("msgC1_first"))

            # resource should ignore UPDATE and DELETE
            ms.listres.new_message(Notice("mailbox_server_messages",
                                          "delete", 15, None))
            # now trigger a third message
            ms.queue_msgC(tid1, "msgC1_third")
            return self.poll(lambda: check_f(3))
        d.addCallback(_then1)
        def _then2(_):
            self.failUnlessEqual(len(fields), 3)
            self.failUnlessEqual(fields[2][0], "data")
            responses = fields[2][1].split()
            self.failUnlessEqual(len(responses), 1)
            r3 = base64.b64decode(responses[0])
            (fetch_token3, delete_token3, length3) = \
                           retrieval.decrypt_list_entry(r3, symkey_1, tmppub)
            self.failUnlessEqual(length3, len("msgC1_third"))
        d.addCallback(_then2)
        def _shutdown(res):
            es.cancel()
            d2 = defer.Deferred()
            finished_d.addBoth(lambda _: d2.callback(res))
            return d2
        d.addBoth(_shutdown)
        return d

    def test_web_events_replacement(self):
        n = self.make_nodes(transport="local")[1]
        ms = n.mailbox_server
        tid1, trec1 = self.add_recipient(n)
        tid2, trec2 = self.add_recipient(n)
        TTID_1, TT0_1, RT_1, symkey_1 = ms.get_tid_data(tid1)
        TTID_2, TT0_2, RT_2, symkey_2 = ms.get_tid_data(tid2)

        ms.queue_msgC(tid1, "msgC1_first")
        ms.queue_msgC(tid1, "msgC1_second")
        ms.queue_msgC(tid2, "msgC2")

        baseurl = n.baseurl + "retrieval/"

        retrieval_pubkey = trec1["retrieval_pubkey"].decode("hex")
        reqkey1,tmppub1 = retrieval.encrypt_list_request(retrieval_pubkey, RT_1)
        url1 = baseurl+"list?t="+base64.urlsafe_b64encode(reqkey1)

        reqkey2,tmppub2 = retrieval.encrypt_list_request(retrieval_pubkey, RT_1)
        url2 = baseurl+"list?t="+base64.urlsafe_b64encode(reqkey2)

        fields1 = []
        def handler1(name, data):
            fields1.append( (name,data) )
        fields2 = []
        def handler2(name, data):
            fields2.append( (name,data) )

        def check_f(fields, min_fields):
            if len(fields) < min_fields:
                return False
            return True

        es1 = eventsource.EventSource(url1, handler1)
        es2 = eventsource.EventSource(url2, handler2)

        cleanup1_d = defer.Deferred()
        cleanup2_d = defer.Deferred()
        def fire_cleanup(res, cleanup_d):
            cleanup_d.callback(None)
            return res
        finished1_d = es1.start()
        finished1_d.addBoth(fire_cleanup, cleanup1_d)

        d = self.poll(lambda: check_f(fields1, 2))
        def _then1(_):
            self.failUnlessEqual(len(fields1), 2)
            self.failUnlessEqual(fields1[0][0], "") # comment
            self.failUnlessEqual(fields1[1][0], "data")
            responses = fields1[1][1].split()
            self.failUnlessEqual(len(responses), 2)
            r1 = base64.b64decode(responses[0])
            (fetch_token1, delete_token1, length1) = \
                           retrieval.decrypt_list_entry(r1, symkey_1, tmppub1)
            self.failUnlessEqual(length1, len("msgC1_first"))

            # starting a new request should cancel the existing one
            self.finished2_d = es2.start()
            self.finished2_d.addBoth(fire_cleanup, cleanup2_d)
            return finished1_d
        d.addCallback(_then1)
        d.addCallback(lambda _: self.poll(lambda: check_f(fields2, 2)))
        def _then2(_):
            self.failUnlessEqual(len(fields2), 2)
            self.failUnlessEqual(fields2[0][0], "") # comment
            self.failUnlessEqual(fields2[1][0], "data")
            responses = fields2[1][1].split()
            self.failUnlessEqual(len(responses), 2)
            r1 = base64.b64decode(responses[0])
            (fetch_token1, delete_token1, length1) = \
                           retrieval.decrypt_list_entry(r1, symkey_1, tmppub2)
            self.failUnlessEqual(length1, len("msgC1_first"))
        d.addCallback(_then2)

        def _shutdown(res):
            es1.cancel()
            es2.cancel()
            return res
        d.addBoth(_shutdown)
        d.addCallback(lambda _: cleanup1_d)
        d.addCallback(lambda _: cleanup2_d)
        return d
