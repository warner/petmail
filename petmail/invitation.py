import re, os, json
from twisted.application import service
from .hkdf import HKDF
from .errors import CommandError
#from nacl.signing import SigningKey, VerifyKey, BadSignatureError
from nacl.signing import SigningKey, VerifyKey
from nacl.exceptions import BadSignatureError
from nacl.public import PrivateKey, PublicKey, Box
from nacl.encoding import HexEncoder as Hex

assert Box.NONCE_SIZE == 24

# sk = SigningKey.generate() or SigningKey(seed)
# vk = sk.verify_key.encode() or .encode(Hex) or VerifyKey(bytes)
# sigmsg = sk.sign(msg)
# msg = vk.verify(sm) or nacl.signing.BadSignatureError

# privkey = PrivateKey.generate() or PrivateKey(bytes)
# pubkey = privkey.public_key or PublicKey(bytes)
# pubkey.encode()
# nonce+ct = Box(privkey, pubkey).encrypt(body, nonce)
#  or body=box.decrypt(ct, nonce)
#  or body=box.decrypt(ct+nonce)

# all messages are r0:hex(sigmsg(by-code, msg))
# A->B: i0:m1:tmpA
# B->A: i0:m1:tmpB
# B->A: i0:m2:enc(to=tmpA,from=tmpB, i0:m2a:verfB+sig(tmpA+tmpB+tportB))
# A->B: i0:m2:enc(to=tmpB,from=tmpA, i0:m2a:verfA+sig(tmpB+tmpA+tportA))
# A->B: i0:m3:ACK-nonce
# B->A: i0:m3:ACK-nonce
# B->A: i0:destroy:nonce  # (1-of-2)
# A->B: i0:destroy:nonce  # (2-of-2)

class CorruptChannelError(Exception):
    pass

VALID_INVITEID = re.compile(r'^[0-9a-f]+$')
VALID_MESSAGE = re.compile(r'^r0:[0-9a-f]+$')

def stretch(code):
    # TODO: spend some quality time with scrypt
    return HKDF("stretched-" + code, 32)

def splitMessages(s):
    if not s:
        return set()
    return set(str(s).split(","))

class InvitationManager(service.MultiService):
    """I manage all invitations, as well as connections to the rendezvous
    servers
    """
    def __init__(self, db, agent):
        service.MultiService.__init__(self)
        self.db = db
        self.agent = agent
        self._debug_invitations_completed = 0
        # all my service children are Rendezvous services

    def startService(self):
        service.MultiService.startService(self)
        self.ready_pending_invitations()

    def add_rendezvous_service(self, rs):
        rs.setServiceParent(self)

    def subscribe(self, inviteID):
        for rs in list(self):
            rs.subscribe(inviteID)

    def unsubscribe(self, inviteID):
        for rs in list(self):
            rs.unsubscribe(inviteID)

    def messages_received(self, inviteID, messages):
        rows = self.db.execute("SELECT id FROM invitations"
                               " WHERE inviteID=? LIMIT 1",
                               (inviteID,)).fetchall()
        if not rows:
            raise KeyError(inviteID)
        iid = rows[0][0]
        i = Invitation(iid, self.db, self, self.agent)
        i.process_messages(messages)

    def send_to_all(self, inviteID, msg):
        for rs in list(self):
            rs.send(inviteID, msg)

    def ready_pending_invitations(self):
        c = self.db.execute("SELECT inviteID FROM invitations")
        for (inviteID,) in c.fetchall():
            # this will fetch a batch of messages (possibly empty, if we
            # crashed before delivering our first one), which will trigger
            # resends or reactions to inbound messages
            self.subscribe(str(inviteID))

    def start_invitation(self, cid, code, generated, my_signkey, payload):
        # "payload" goes to them
        stretched = stretch(code)
        invite_key = SigningKey(stretched)
        inviteID = invite_key.verify_key.encode(Hex)
        my_temp_privkey = PrivateKey.generate()

        db = self.db
        c = db.execute("SELECT inviteID FROM invitations")
        if inviteID in [str(row[0]) for row in c.fetchall()]:
            raise CommandError("invitation code already in use")
        iid = db.insert("INSERT INTO `invitations`"
                        " (channel_id,"
                        "  code, generated,"
                        "  invite_key,"
                        "  inviteID,"
                        "  my_temp_privkey, my_signkey,"
                        "  payload_for_them_json,"
                        "  my_messages, their_messages, "
                        "  next_expected_message)"
                        " VALUES (?, ?,?, ?, ?, ?,?, ?, ?,?, ?)",
                        (cid,
                         code.encode("hex"), int(bool(generated)),
                         stretched.encode("hex"),
                         inviteID,
                         my_temp_privkey.encode(Hex), my_signkey.encode(Hex),
                         json.dumps(payload),
                         "", "",
                         1),
                        "invitations")
        self.subscribe(inviteID)
        i = Invitation(iid, self.db, self, self.agent)
        i.send_first_message()
        self.db.commit()
        return iid

class Invitation:
    # This has a brief lifetime: one is created in response to the rendezvous
    # client discovering new messages for us, used for one reactor tick, then
    # dereferenced. It holds onto a few values during that tick (which may
    # process multiple messages for a single invitation, e.g. A's second poll
    # will receive both B-m1 and B-m2 together). But all persistent state
    # beyond that one tick is stored in the database.
    def __init__(self, iid, db, manager, agent):
        self.iid = iid
        self.db = db
        self.manager = manager
        self.agent = agent
        c = self.db.execute("SELECT inviteID, invite_key,"
                            " their_temp_pubkey,"
                            " next_expected_message,"
                            " my_messages,"
                            " their_messages"
                            " FROM invitations WHERE id = ?", (iid,))
        res = c.fetchone()
        if not res:
            raise KeyError("no pending Invitation for '%d'" % iid)
        self.inviteID = str(res["inviteID"])
        self.invite_key = SigningKey(res["invite_key"].decode("hex"))
        self.their_temp_pubkey = None
        if res["their_temp_pubkey"]:
            self.their_temp_pubkey = PublicKey(res["their_temp_pubkey"].decode("hex"))
        self.next_expected_message = int(res["next_expected_message"])
        self.my_messages = splitMessages(res["my_messages"])
        self.their_messages = splitMessages(res["their_messages"])

    def get_channel_id(self):
        c = self.db.execute("SELECT channel_id FROM invitations"
                            " WHERE id = ?", (self.iid,))
        return c.fetchone()[0]

    def get_my_temp_privkey(self):
        c = self.db.execute("SELECT my_temp_privkey FROM invitations"
                            " WHERE id = ?", (self.iid,))
        return PrivateKey(c.fetchone()[0].decode("hex"))

    def get_my_signkey(self):
        c = self.db.execute("SELECT my_signkey FROM invitations"
                            " WHERE id = ?", (self.iid,))
        return SigningKey(c.fetchone()[0].decode("hex"))

    def get_payload_for_them(self):
        c = self.db.execute("SELECT payload_for_them_json FROM invitations"
                            " WHERE id = ?", (self.iid,))
        return c.fetchone()[0]


    def send_first_message(self):
        pub = self.get_my_temp_privkey().public_key.encode()
        self.send("i0:m1:"+pub)
        self.db.update("UPDATE invitations SET my_messages=? WHERE id=?",
                       (",".join(self.my_messages), self.iid),
                       "invitations", self.iid)
        # that will be commited by our caller

    def process_messages(self, messages):
        # These messages are neither version-checked nor signature-checked.
        # Also, we may have already processed some of them.
        #print "process_messages", messages
        #print " my", self.my_messages
        #print " theirs", self.their_messages
        assert isinstance(messages, set), type(messages)
        assert None not in messages, messages
        assert None not in self.my_messages, self.my_messages
        assert None not in self.their_messages, self.their_messages
        # Send anything that didn't make it to the server. This covers the
        # case where we commit our outbound message in send() but crash
        # before finishing delivery.
        #for m in self.my_messages - messages:
        #    #print "resending", m
        #    self.manager.send_to_all(self.inviteID, m)

        newMessages = messages - self.my_messages - self.their_messages
        #print " %d new messages" % len(newMessages)
        if not newMessages:
            #print " huh, no new messages, stupid rendezvous client"
            pass

        # check signatures, extract bodies. invalid messages kill the channel
        # and the invitation. MAYBE TODO: lose the one channel, keep using
        # the others.
        messages_to_ignore = set()
        valid_bodies = {}
        for m in newMessages:
            try:
                if not m.startswith("r0:"):
                    print "unrecognized rendezvous message prefix"
                    messages_to_ignore.add(m) # ignore it next time
                    continue
                if not VALID_MESSAGE.search(m):
                    raise CorruptChannelError()
                decoded = m[len("r0:"):].decode("hex")
                body = self.invite_key.verify_key.verify(decoded)
                valid_bodies[body] = m
            except (BadSignatureError, CorruptChannelError) as e:
                print "channel %s is corrupt" % self.inviteID
                if isinstance(e, BadSignatureError):
                    print " (bad sig)"
                self.unsubscribe(self.inviteID)
                # TODO: mark invitation as failed, destroy it
                return

        # these handlers will update self.my_messages with sent messages, and
        # will increment self.next_expected_message. We can handle multiple
        # (sequential) messages in a single pass.
        def call_if_prefixed(prefix, handler):
            for b in valid_bodies:
                if b.startswith(prefix):
                    messages_to_ignore.add(valid_bodies[b])
                    handler(b[len(prefix):])
                    return

        if self.next_expected_message == 1:
            call_if_prefixed("i0:m1:", self.process_M1)
        # no elif here: self.next_expected_message may have incremented
        if self.next_expected_message == 2:
            call_if_prefixed("i0:m2:", self.process_M2)
        if self.next_expected_message == 3:
            call_if_prefixed("i0:m3:", self.process_M3)

        self.db.update("UPDATE invitations SET"
                       "  my_messages=?,"
                       "  their_messages=?,"
                       "  next_expected_message=?"
                       " WHERE id=?",
                       (",".join(self.my_messages),
                        ",".join(self.their_messages | messages_to_ignore),
                        self.next_expected_message,
                        self.iid),
                       "invitations", self.iid)
        #print " db.commit"
        self.db.commit()

    def send(self, msg, persist=True):
        #print "send", repr(msg[:10]), "..."
        signed = "r0:%s" % self.invite_key.sign(msg).encode("hex")
        if persist: # m4-destroy is not persistent
            self.my_messages.add(signed) # will be persisted by caller
            # This will be added to the DB, and committed, by our caller, to
            # get it into the same transaction as the update to which inbound
            # messages we've processed.
        assert VALID_MESSAGE.search(signed), signed
        self.manager.send_to_all(self.inviteID, signed)

    def process_M1(self, msg):
        self.their_temp_pubkey = PublicKey(msg)
        self.db.update("UPDATE invitations SET their_temp_pubkey=?"
                       " WHERE id=?",
                       (self.their_temp_pubkey.encode(Hex), self.iid),
                       "invitations", self.iid)
        # their_temp_pubkey will committed by our caller, in the same txn as
        # the message send

        my_privkey = self.get_my_temp_privkey()
        payload_for_them = self.get_payload_for_them()
        b = Box(my_privkey, self.their_temp_pubkey)
        signedBody = b"".join([self.their_temp_pubkey.encode(),
                               my_privkey.public_key.encode(),
                               payload_for_them.encode("utf-8")])
        my_sign = self.get_my_signkey()
        body = b"".join([b"i0:m2a:",
                         my_sign.verify_key.encode(),
                         my_sign.sign(signedBody)
                         ])
        nonce = os.urandom(Box.NONCE_SIZE)
        nonce_and_ciphertext = b.encrypt(body, nonce)
        #print "ENCRYPTED n+c", len(nonce_and_ciphertext), nonce_and_ciphertext.encode("hex")
        #print " nonce", nonce.encode("hex")
        msg2 = "i0:m2:"+nonce_and_ciphertext
        self.send(msg2)
        self.next_expected_message = 2

    def process_M2(self, msg):
        assert self.their_temp_pubkey
        nonce_and_ciphertext = msg
        my_privkey = self.get_my_temp_privkey()
        b = Box(my_privkey, self.their_temp_pubkey)
        #nonce = msg[:Box.NONCE_SIZE]
        #ciphertext = msg[Box.NONCE_SIZE:]
        #print "DECRYPTING n+ct", len(msg), msg.encode("hex")
        body = b.decrypt(nonce_and_ciphertext)
        if not body.startswith("i0:m2a:"):
            raise ValueError("expected i0:m2a:, got '%r'" % body[:20])
        verfkey_and_signedBody = body[len("i0:m2a:"):]
        their_verfkey = VerifyKey(verfkey_and_signedBody[:32])
        signedBody = verfkey_and_signedBody[32:]
        body = their_verfkey.verify(signedBody)
        check_my_temp_pubkey = body[:32]
        check_their_temp_pubkey = body[32:64]
        payload_for_us_json = body[64:].decode("utf-8")
        #print " binding checks:"
        #print " check_my_temp_pubkey", check_my_temp_pubkey.encode("hex")
        #print " my real tempPubkey", my_privkey.public_key.encode(Hex)
        #print " check_their_temp_pubkey", check_their_temp_pubkey.encode("hex")
        #print " first their_temp_pubkey", self.their_temp_pubkey.encode(Hex)
        if check_my_temp_pubkey != my_privkey.public_key.encode():
            raise ValueError("binding failure myTempPubkey")
        if check_their_temp_pubkey != self.their_temp_pubkey.encode():
            raise ValueError("binding failure their_temp_pubkey")

        cid = self.get_channel_id()
        them = json.loads(payload_for_us_json)
        self.agent.invitation_done(cid, them, their_verfkey)

        msg3 = "i0:m3:ACK-"+os.urandom(16)
        self.send(msg3)
        self.next_expected_message = 3

    def process_M3(self, msg):
        #print "processM3", repr(msg[:10]), "..."
        if not msg.startswith("ACK-"):
            raise ValueError("bad ACK")
        self.agent.invitation_acked(self.get_channel_id())
        self.db.delete("DELETE FROM invitations WHERE id=?", (self.iid,),
                       "invitations", self.iid)
        # we no longer care about the channel
        msg4 = "i0:destroy:"+os.urandom(16)
        self.send(msg4, persist=False)
        self.manager.unsubscribe(self.inviteID)
        self.manager._debug_invitations_completed += 1
