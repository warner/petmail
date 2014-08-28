import os, re, json
from twisted.trial import unittest
from twisted.internet import defer
from twisted.web.client import getPage
from .common import BasedirMixin, NodeRunnerMixin, CLIinThreadMixin
from .pollmixin import PollMixin
from ..eventsource import EventSource

class Web(BasedirMixin, NodeRunnerMixin, CLIinThreadMixin, PollMixin,
          unittest.TestCase):
    def do_cli(self, command, *args):
        return self.cliMustSucceed("-d", self.basedir, command, *args)

    def test_opener(self):
        self.basedir = os.path.join(self.make_basedir(), "node")
        self.createNode(self.basedir)
        n = self.startNode(self.basedir)

        d = defer.succeed(None)

        d.addCallback(lambda _: self.do_cli("open", "--no-open"))
        def _stash_opener_url(res):
            mo = re.search(r'Please open: (.*)\n', res)
            opener_url = mo.group(1)
            token = (n.db.execute("SELECT * FROM webapi_opener_tokens")
                     .fetchone()["token"])
            expected = n.baseurl + "open-control?opener-token=" + token
            self.failUnlessEqual(opener_url, expected)
            self.opener_url = opener_url
            self.bad_opener_url = n.baseurl + "open-control?opener-token=BAD"
            self.lame_opener_url = n.baseurl + "open-control"
        d.addCallback(_stash_opener_url)

        d.addCallback(lambda _: getPage(self.lame_opener_url, method="GET"))
        def _check_lame_login_page(page):
            self.failUnlessIn("Please use 'petmail open' to get to the control panel", page)
        d.addCallback(_check_lame_login_page)

        d.addCallback(lambda _: getPage(self.bad_opener_url, method="GET"))
        def _check_bad_login_page(page):
            self.failUnlessIn("Sorry, that opener-token is expired or invalid, please run 'petmail open' again", page)
        d.addCallback(_check_bad_login_page)

        d.addCallback(lambda _: getPage(self.opener_url, method="GET"))
        def _check_login_page(page):
            self.failUnlessIn('<form id="login" ', page)
            token = (n.db.execute("SELECT * FROM webapi_access_tokens")
                     .fetchone()["token"])
            self.failUnlessIn('<input type="hidden" name="token" value="%s">'
                              % token, page)
            tokens = (n.db.execute("SELECT * FROM webapi_opener_tokens")
                      .fetchall())
            self.failUnlessEqual(len(tokens), 0)
        d.addCallback(_check_login_page)

        return d

    def POST_control(self, url, token):
        postdata = "token=%s" % token
        return getPage(url, method="POST", postdata=postdata,
                       headers={"accept": "text/html",
                                "content-type": "application/x-www-form-urlencoded"})

    def test_control(self):
        self.basedir = os.path.join(self.make_basedir(), "node")
        self.createNode(self.basedir)
        n = self.startNode(self.basedir)
        token = n.web.access_token
        control_url = n.baseurl + "control"

        d = defer.succeed(None)

        d.addCallback(lambda _: self.POST_control(control_url, "BAD"))
        def _check_bad_token(page):
            self.failUnlessIn("Sorry, this access token is expired, please run 'petmail open' again", page)
        d.addCallback(_check_bad_token)

        d.addCallback(lambda _: self.POST_control(control_url, token))
        def _check_good_token(page):
            self.failUnlessIn("<html>", page)
            self.failUnlessIn("<title>Petmail Control Panel</title>", page)
            self.failUnlessIn('var token = "%s";' % token, page)
        d.addCallback(_check_good_token)

        return d

    def POST(self, url, args):
        d = getPage(url, method="POST", postdata=json.dumps(args),
                    headers={"accept": "application/json",
                             "content-type": "application/json"})
        d.addCallback(json.loads)
        return d

    def test_api(self):
        self.basedir = os.path.join(self.make_basedir(), "node")
        self.createNode(self.basedir)
        n = self.startNode(self.basedir)
        token = n.web.access_token
        api_url = n.baseurl + "api"

        d = defer.succeed(None)

        d.addCallback(lambda _: self.POST(api_url+"/list-addressbook",
                                          {"token": token,
                                           "args": {}}))
        def _got_response(res):
            self.failUnlessEqual(res["ok"], "ok")
            self.failUnlessEqual(res["addressbook"], [])
        d.addCallback(_got_response)

        return d

    def test_events(self):
        self.basedir = os.path.join(self.make_basedir(), "node")
        self.createNode(self.basedir)
        n = self.startNode(self.basedir)
        token = n.web.access_token
        api_url = n.baseurl + "api"

        events = []
        def handler(name, data):
            events.append( (name, json.loads(data)) )

        d = defer.succeed(None)

        d.addCallback(lambda _: self.POST(api_url+"/eventchannel-create",
                                          {"token": token, "args": {}}))
        def _got_esid(res):
            self.failUnlessEqual(res["ok"], "ok")
            self.esid = str(res["esid"])
            self.es = EventSource(api_url+"/events/"+self.esid, handler)
            self.es_finished_d = self.es.start()
        d.addCallback(_got_esid)
        # the first event will be type="ready"
        d.addCallback(lambda _: self.poll(lambda: events))
        def _ready(_):
            self.failUnlessEqual(len(events), 1)
            self.failUnlessEqual(events[0][1]["type"], "ready")
            events.pop()
            return self.POST(api_url+"/eventchannel-subscribe",
                             {"token": token,
                              "args": {"esid": self.esid,
                                       "topic": "messages",
                                       "catchup": True}})
        d.addCallback(_ready)

        def _new_message(_):
            n.db.insert("INSERT INTO addressbook"
                        " (id, petname)"
                        " VALUES (?,?)",
                        (1, "alice"),
                        "addressbook")
            n.db.insert("INSERT INTO outbound_messages"
                        " (cid, when_sent, payload_json)"
                        " VALUES (?,?,?)",
                        (1, 1234, json.dumps({"basic": "message"})),
                        "outbound_messages")
            n.db.commit()
        d.addCallback(_new_message)
        d.addCallback(lambda _: self.poll(lambda: events))

        def _got_message(_):
            self.failUnlessEqual(len(events), 1)
            data = events[0][1]
            self.failUnlessEqual(data["action"], "insert")
            self.failUnlessEqual(data["type"], "outbound-messages")
            row = data["new_value"]
            self.failUnlessEqual(row["petname"], "alice")
            self.failUnlessEqual(row["cid"], 1)
            self.failUnlessEqual(row["when_sent"], 1234)
            self.failUnlessEqual(json.loads(row["payload_json"]),
                                 {"basic": "message"})
            events.pop()
            return self.POST(api_url+"/eventchannel-unsubscribe",
                             {"token": token,
                              "args": {"esid": self.esid,
                                       "topic": "messages"}})
        d.addCallback(_got_message)


        def _shutdown(res):
            self.es.cancel()
            d2 = defer.Deferred()
            self.es_finished_d.addBoth(lambda _: d2.callback(res))
            return d2
        d.addCallback(_shutdown)

        return d
