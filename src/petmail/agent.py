import os.path, json, time
from twisted.application import service
from twisted.python import log
from nacl.public import PrivateKey
from nacl.signing import SigningKey, VerifyKey
from nacl.encoding import HexEncoder as Hex
from . import invitation, rrid
from .errors import CommandError, ContactNotReadyError
from .mailbox import channel, retrieval
from .eventual import eventually

class Agent(service.MultiService):
    def __init__(self, db, basedir, mailbox_server):
        service.MultiService.__init__(self)
        self.db = db
        self.mailbox_server = mailbox_server

        self.mailbox_retrievers = set()
        c = self.db.execute("SELECT * FROM agent_profile").fetchone()
        self.advertise_local_mailbox = bool(c["advertise_local_mailbox"])
        mboxes = {}
        if self.advertise_local_mailbox:
            local_tid = mailbox_server.get_local_transport()
            local_mbrec = mailbox_server.get_mailbox_record(local_tid)
            mboxes["local"] = local_mbrec["retrieval"]
        for row in self.db.execute("SELECT * FROM mailboxes").fetchall():
            mbrec = json.loads(row["mailbox_record_json"])
            mboxes[row["id"]] = mbrec["retrieval"]

        for mbid, rrec in mboxes.items():
            rc = self.build_retriever(mbid, rrec)
            self.subscribe_to_mailbox(rc)

        # the invitations are activated in startService
        row = self.db.execute("SELECT * FROM relay_servers").fetchone()
        relay_url = row["url"].encode("ascii")
        self.im = invitation.InvitationManager(db, relay_url)

    def startService(self):
        service.MultiService.startService(self)
        for i in self.im.thaw_invitations():
            self._activate_invitation(i)

    def build_retriever(self, mbid, rrec):
        # parse descriptor, import correct module and constructor
        def got_msgC(msgC):
            self.msgC_received(mbid, msgC)
        retrieval_type = rrec["type"]
        if retrieval_type == "http":
            return retrieval.HTTPRetriever(rrec, got_msgC)
        elif retrieval_type == "local":
            return retrieval.LocalRetriever(rrec, got_msgC, self.mailbox_server)
        else:
            raise CommandError("unrecognized mailbox-retrieval protocol '%s'"
                               % retrieval_type)

    def subscribe_to_mailbox(self, rc):
        self.mailbox_retrievers.add(rc)
        # the retrieval client gets to make network connections, etc, as soon
        # as it starts. If we are "running" when we add it as a service
        # child, that happens here.
        rc.setServiceParent(self)

    def msgC_received(self, tid, msgC):
        assert msgC.startswith("c0:")
        cid, seqnum, payload_json = channel.process_msgC(self.db, msgC)
        self.payload_received(cid, seqnum, payload_json)

    def payload_received(self, cid, seqnum, payload_json):
        self.db.insert("INSERT INTO inbound_messages"
                        " (cid, seqnum, when_received, payload_json)"
                        " VALUES (?,?,?,?)",
                        (cid, seqnum, time.time(), payload_json),
                       "inbound_messages")
        self.db.commit()
        #payload = json.loads(payload_json)
        #print "payload_received", cid, seqnum, payload
        #if payload.has_key("basic"):
        #    print "BASIC:", payload["basic"]

    def command_invite(self, petname, maybe_code=None, reqid=None,
                       override_transports=None, offer_mailbox=False,
                       accept_mailbox_offer=False,
                       _debug_when_done=None):
        #if offer_mailbox:
        #    code = "mailbox-" + code

        if maybe_code:
            count = self.db.execute("SELECT COUNT(*) FROM addressbook"
                                    " WHERE invitation_state != ?"
                                    "  AND invitation_code=?",
                                    (invitation.INVITE_COMPLETE, maybe_code)
                                    ).fetchone()[0]
            if count:
                raise CommandError("invitation code already in use")

        my_signkey = SigningKey.generate()
        channel_key = PrivateKey.generate()
        my_CID_key = os.urandom(32)

        base_transports = self.get_transports()
        if override_transports:
            base_transports = override_transports
        transports = self.individualize_transports(base_transports)

        channel = { "channel_pubkey": channel_key.public_key.encode(Hex),
                    "CID_key": my_CID_key.encode("hex"),
                    "transports": transports.values(),
                     }
        payload = { "channel": channel }

        if offer_mailbox:
            tid = self.mailbox_server.allocate_transport(remote=True)
            payload["mailbox"] = self.mailbox_server.get_mailbox_record(tid)

        encoded_payload = json.dumps(payload).encode("utf-8")
        sigkeypayload = (b"i0:" + my_signkey.verify_key.encode()
                         + my_signkey.sign(encoded_payload))

        cid = self.db.insert(
            "INSERT INTO addressbook"
            " (petname, accept_mailbox_offer,"
            "  invitation_state, when_invited, invitation_code,"
            "  wormhole_payload,"
            "  next_outbound_seqnum, my_signkey,"
            "  my_CID_key, next_CID_token,"
            "  highest_inbound_seqnum,"
            "  my_old_channel_privkey,"
            "  my_new_channel_privkey)"
            " VALUES (?,?, ?,?,?, ?, ?,?, ?,?, ?, ?, ?)",
            (petname, accept_mailbox_offer,
             invitation.INVITE_WAITING_FOR_CODE, time.time(), maybe_code,
             sigkeypayload.encode("hex"),
             1, my_signkey.encode(Hex),
             my_CID_key.encode("hex"), None,
             0,
             channel_key.encode(Hex),
             channel_key.encode(Hex), # at beginning, old=new
             ),
            "addressbook", {"reqid": reqid})

        i = self.im.create_invitation(cid)
        self.db.commit()
        self._activate_invitation(i, cid, _debug_when_done)

        return {"contact-id": cid, "petname": petname,
                "ok": "invitation for %s started: cid=%d" % (petname, cid)}

    def _activate_invitation(self, i, cid, _debug_when_done=None):
        d = i.activate()
        d.addCallbacks(self.invitation_success, self.invitation_failed,
                       callbackArgs=(cid,_debug_when_done),
                       errbackArgs=(cid,_debug_when_done))
        return d

    def petname_for_cid(self, cid):
        c = self.db.execute("SELECT petname FROM addressbook WHERE id=?",
                            (cid,))
        petname = c.fetchone()["petname"]
        return petname

    def invitation_success(self, sigkeypayload, cid, _debug_when_done):
        if not sigkeypayload.startswith("i0:"):
            raise ValueError("expected i0:, got '%r'" % sigkeypayload[:20])
        their_verfkey = VerifyKey(sigkeypayload[3:3+32])
        encoded_payload = their_verfkey.verify(sigkeypayload[3+32:])
        payload = json.loads(encoded_payload.decode("utf-8"))

        self.db.update(
            "UPDATE addressbook SET"
            " invitation_state=?, wormhole=?, wormhole_payload=?,"
            " when_accepted=?,"
            " acked=1,"  # TODO: faked. add a roundtrip?
            " latest_offered_mailbox_json=?,"
            " their_channel_record_json=?,"
            " they_used_new_channel_key=?, their_verfkey=?"
            " WHERE id=?",
            (invitation.INVITE_COMPLETE, None, None,
             time.time(),
             json.dumps(payload.get("mailbox")),
             json.dumps(payload["channel"]),
             0, their_verfkey.encode().encode("hex"),
             cid), "addressbook", cid)
        self.maybe_accept_mailbox(cid)
        self.db.commit()
        log.msg("addressbook entry added for petname=%r" %
                self.petname_for_cid(cid))
        if _debug_when_done:
            eventually(_debug_when_done.callback, cid)

    def invitation_failed(self, err, cid, _debug_when_done):
        log.msg("invitation failed for petname=%r: err=%r" %
                (self.petname_for_cid(cid), err))
        # TODO: find a better way to signal an error to the frontend
        self.db.delete("DELETE FROM addressbook WHERE id=?", (cid,),
                       "addressbook", cid)
        self.db.commit()
        if _debug_when_done:
            eventually(_debug_when_done.callback, err)

    def maybe_accept_mailbox(self, cid):
        c = self.db.execute("SELECT * FROM addressbook WHERE id=?", (cid,))
        row = c.fetchone()
        mailbox_json = row["latest_offered_mailbox_json"]
        accept_mailbox_offer = row["accept_mailbox_offer"]
        # TODO: make sure this only happens once
        if mailbox_json and accept_mailbox_offer:
            mailbox = json.loads(mailbox_json)
            mbid = self.db.insert("INSERT INTO mailboxes"
                                  " (cid, mailbox_record_json) VALUES (?,?)",
                                  (cid, json.dumps(mailbox),), "mailboxes")
            rc = self.build_retriever(mbid, mailbox["retrieval"])
            self.subscribe_to_mailbox(rc)

    def command_control_accept_mailbox_offer(self, cid, accept):
        c = self.db.execute("SELECT accept_mailbox_offer FROM addressbook WHERE id=?",
                            (cid,))
        old_accept = bool(c.fetchone()["accept_mailbox_offer"])
        if accept != old_accept:
            self.db.update("UPDATE addressbook SET accept_mailbox_offer=?"
                           " WHERE id=?", (accept, cid),
                           "addressbook", cid)
            # TODO: add or remove an existing mailbox
            self.db.commit()
        return "ok"

    def command_send_basic_message(self, cid, message):
        try:
            self.send_message(cid, {"basic": message}) # ignore Deferred
        except ContactNotReadyError:
            raise CommandError("cid %d is not ready for messages" % cid)
        return "maybe sent"

    def send_message(self, cid, payload):
        row = self.db.execute("SELECT acked, their_channel_record_json"
                              " FROM addressbook WHERE id=?", (cid,)).fetchone()
        if not row["acked"] or not row["their_channel_record_json"]:
            raise ContactNotReadyError("cid %d is not ready for messages" % cid)
        self.db.insert("INSERT INTO outbound_messages"
                       " (cid, when_sent, payload_json)"
                       " VALUES (?,?,?)",
                       (cid, time.time(), json.dumps(payload)),
                       "outbound_messages")
        self.db.commit() # XXX ?. Or wait for c.send() to commit?
        c = channel.OutboundChannel(self.db, cid)
        return c.send(payload)

    def get_transports(self):
        # returns dict of mbid->pubrecord . These will be individualized
        # before delivery to the peer.
        transports = {}
        if self.advertise_local_mailbox:
            local_tid = self.mailbox_server.get_local_transport()
            local_mbrec = self.mailbox_server.get_mailbox_record(local_tid)
            transports["local"] = local_mbrec
        for row in self.db.execute("SELECT * FROM mailboxes").fetchall():
            transports[row["id"]] = json.loads(row["mailbox_record_json"])
        return transports

    def individualize_transports(self, base_transports):
        transports = {}
        for mbid, base in base_transports.items():
            t = base["transport"]["generic"].copy()
            TT0 = base["transport"]["sender"]["TT0"].decode("hex")
            t["STT"] = rrid.randomize(TT0).encode("hex")
            transports[mbid] = t
        return transports

    def command_list_addressbook(self):
        resp = []
        # these entries might merely be incomplete invitations
        for row in self.db.execute("SELECT * FROM addressbook").fetchall():
            entry = {}
            # these properties are set right away
            entry["cid"] = row["id"]
            entry["petname"] = row["petname"]
            entry["acked"] = bool(row["acked"])
            entry["invitation_context"] = {
                "when_invited": row["when_invited"],
                "code": row["invitation_code"],
                }
            sk = SigningKey(row["my_signkey"].decode("hex"))
            entry["my_verfkey"] = sk.verify_key.encode(Hex)

            # these appear when the invitation process is complete
            if row["when_accepted"] is not None:
                entry["invitation_context"]["when_accepted"] = row["when_accepted"]
            if row["their_verfkey"] is not None:
                entry["their_verfkey"] = str(row["their_verfkey"])
            if row["their_channel_record_json"] is not None:
                entry["their_channel_record"] = json.loads(row["their_channel_record_json"])
            # TODO: filter out the long-term stuff
            resp.append(entry)
        return resp

    def command_set_petname(self, cid, petname):
        self.db.update("UPDATE addressbook SET petname=? WHERE id=?",
                       (petname, cid),
                       "addressbook", cid)
        self.db.commit()

    def command_fetch_all_messages(self):
        c = self.db.execute("SELECT inbound_messages.*,addressbook.petname"
                            " FROM inbound_messages,addressbook"
                            " WHERE inbound_messages.cid = addressbook.id")
        return [{ "id": row["id"],
                  "petname": row["petname"],
                  "cid": row["cid"],
                  "seqnum": row["seqnum"],
                  "payload": json.loads(row["payload_json"]),
                  }
                for row in c.fetchall()]
