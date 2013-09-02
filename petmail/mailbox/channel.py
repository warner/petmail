import struct, json, os
from hashlib import sha256
from twisted.internet import defer
from ..errors import ReplayError, WrongVerfkeyError, UnknownChannelError
from ..util import split_into, verify_with_prefix
from ..hkdf import HKDF
from ..netstring import netstring, split_netstrings_and_trailer
from .transport import make_transport
from nacl.public import PrivateKey, PublicKey, Box
from nacl.signing import SigningKey, VerifyKey
from nacl.secret import SecretBox
from nacl.exceptions import CryptoError

# msgC:
#  c0:
#  CIDToken =HKDF(CIDKey+seqnum) [fixed length]
#  netstring(CIDBox) =secretbox(key=CIDKey, seqnum+H(msgD)+channel-current)
#  msgD
# msgD:
#  pubkey2 [fixed length]
#  enc(to=channel-current, from=key2, msgE)
# msgE:
#  seqnum [fixed length]
#  netstring(sign(by=sender-signkey, pubkey2))
#  encoded-payload

# receiving msgC: work inwards, getting hints on which channel to use

def parse_msgC(msgC):
    if not msgC.startswith("c0:"):
        raise ValueError("corrupt msgC")
    msgC = msgC[len("c0:"):]
    CIDToken = msgC[:32]
    (CIDBox,), msgD = split_netstrings_and_trailer(msgC[32:])
    return CIDToken, CIDBox, msgD

def find_channel_from_CIDToken(db, CIDToken):
    # XXX not implemented
    cid = None
    known_channel_pubkey = None # e.g. unknown
    return cid, known_channel_pubkey

def find_channel_from_CIDBox(db, CIDBox):
    c = db.cursor()
    c.execute("SELECT id, my_CID_key, highest_inbound_seqnum FROM addressbook")
    for row in c.fetchall():
        try:
            CIDKey = row["my_CID_key"].decode("hex")
            seqnum, HmsgD, channel_pubkey_s = decrypt_CIDBox(CIDKey, CIDBox)
            # if we get here, the CIDBox matches this channel. We're allowed
            # to reject the message if the seqnum shows it to be a replay.
            if seqnum <= row["highest_inbound_seqnum"]:
                raise ReplayError("seqnum in CIDBox is too old")
            return row["id"], channel_pubkey_s
        except CryptoError:
            pass
    return None, None

def build_channel_keylist(db, known_cid):
    # generates list of (PrivateKey, (cid, which, PublicKey))
    c = db.cursor()
    # TODO: limit this by the transport the message arrived on
    if known_cid:
        c.execute("SELECT id, my_old_channel_privkey, my_new_channel_privkey"
                  " FROM addressbook WHERE id=?", (known_cid,))
    else:
        c.execute("SELECT id, my_old_channel_privkey, my_new_channel_privkey"
                  " FROM addressbook")
    for row in c.fetchall():
        privkey = PrivateKey(row["my_old_channel_privkey"].decode("hex"))
        yield (privkey, (row["id"], "old", privkey.public_key))

        privkey = PrivateKey(row["my_new_channel_privkey"].decode("hex"))
        yield (privkey, (row["id"], "new", privkey.public_key))

def filter_on_known_channel_pubkey(keylist, known_channel_pubkey_s):
    assert known_channel_pubkey_s
    for (privkey, keyid) in keylist:
        if privkey.public_key.encode() == known_channel_pubkey_s:
            yield (privkey, keyid)

# this builds a list of candidates, filtered with any hints we got
def find_channel_list(db, CIDToken, CIDBox):
    cid, known_channel_pubkey_s = find_channel_from_CIDToken(db, CIDToken)
    if not cid:
        cid, known_channel_pubkey_s = find_channel_from_CIDBox(db, CIDBox)
    keylist = build_channel_keylist(db, cid)
    if known_channel_pubkey_s:
        keylist = filter_on_known_channel_pubkey(keylist,
                                                 known_channel_pubkey_s)
    return keylist

# then we trial-decrypt with all candidates
def decrypt_msgD(msgD, keylist):
    pubkey2_s, enc = split_into(msgD, [32], True)
    pubkey2 = PublicKey(pubkey2_s)
    for (privkey, keyid) in keylist:
        try:
            msgE = Box(privkey, pubkey2).decrypt(enc)
            return keyid, pubkey2_s, msgE
        except CryptoError:
            pass
    return None, None, None

def decrypt_CIDBox(CIDKey, CIDBox):
    sb = SecretBox(CIDKey)
    m = sb.decrypt(CIDBox) # may raise CryptoError
    seqnum_s,HmsgD,channel_pubkey_s = split_into(m, [8, 32, 32])
    seqnum = struct.unpack(">Q", seqnum_s)[0]
    return seqnum, HmsgD, channel_pubkey_s

# then validate on the way back out

def check_msgE(msgE, pubkey2_s, sender_verfkey_s, highest_seqnum):
    seqnum_s = msgE[:8]
    seqnum = struct.unpack(">Q", seqnum_s)[0]
    if seqnum <= highest_seqnum:
        raise ReplayError()
    (ns,), payload_s = split_netstrings_and_trailer(msgE[8:])
    m = verify_with_prefix(VerifyKey(sender_verfkey_s), ns, "ce0:")
    if m != pubkey2_s:
        print repr(m), pubkey2_s(m)
        raise WrongVerfkeyError()
    return seqnum, json.loads(payload_s)

def validate_msgC(CIDKey, channel_pubkey,
                  seqnum_from_msgE, CIDBox, CIDToken, msgD):
    # decrypt_CIDBox will fail if it wasn't encrypted with the right
    # channel_key
    (seqnum_from_CIDBox, HmsgD,
     channel_pubkey_s_from_CIDBox) = decrypt_CIDBox(CIDKey, CIDBox)
    if seqnum_from_CIDBox != seqnum_from_msgE:
        raise ValueError("CIDBox seqnum mismatch (vs msgE)")
    if channel_pubkey_s_from_CIDBox != channel_pubkey.encode():
        raise ValueError("CIDBox pubkey mismatch (vs msgD)")
    if HmsgD != sha256(msgD).digest():
        raise ValueError("CIDBox HmsgD mismatch")
    if build_CIDToken(CIDKey, seqnum_from_msgE) != CIDToken:
        raise ValueError("CIDToken was wrong")
    # ok, message is valid. Caller should update highest_seen_seqnum and
    # deliver the payload

def process_msgC(db, msgC):
    CIDToken, CIDBox, msgD = parse_msgC(msgC)
    keylist = find_channel_list(db, CIDToken, CIDBox)
    keyid, pubkey2_s, msgE = decrypt_msgD(msgD, keylist)
    if not keyid:
        raise UnknownChannelError()
    cid, which_key, channel_pubkey = keyid
    c = db.cursor()
    c.execute("SELECT my_CID_key, highest_inbound_seqnum, their_verfkey"
              " FROM addressbook WHERE id=?", (cid,))
    row = c.fetchone()
    seqnum, payload = check_msgE(msgE, pubkey2_s,
                                 row["their_verfkey"].decode("hex"),
                                 row["highest_inbound_seqnum"])
    # seqnum > highest_inbound_seqnum
    validate_msgC(row["my_CID_key"].decode("hex"), channel_pubkey,
                  seqnum, CIDBox, CIDToken, msgD)
    c.execute("UPDATE addressbook SET highest_inbound_seqnum=? WHERE id=?",
              (seqnum, cid))
    db.commit()
    return cid, payload

def build_CIDToken(CIDKey, seqnum):
    seqnum_s = struct.pack(">Q", seqnum)
    return HKDF(IKM=CIDKey+seqnum_s, dkLen=32, info=b"petmail.org/v1/CIDToken")

assert struct.calcsize(">Q")*8 == 64

class OutboundChannel:
    # I am created to send messages.
    def __init__(self, db, cid):
        self.db = db
        self.cid = cid

    def send(self, payload):
        # returns a Deferred that fires when the delivery is complete, so
        # tests can synchronize
        msgC = self.createMsgC(payload)
        dl = []
        for t in self.createTransports():
            # now wrap msgC into a msgA for each transport they're using
            dl.append(t.send(msgC))
        return defer.DeferredList(dl)

    def createMsgC(self, payload):
        c = self.db.cursor()
        c.execute("SELECT next_outbound_seqnum, my_signkey,"
                  " their_channel_record_json"
                  " FROM addressbook WHERE id=?", (self.cid,))
        res = c.fetchone()
        assert res, "missing cid"
        next_outbound_seqnum = res["next_outbound_seqnum"]
        c.execute("UPDATE addressbook SET next_outbound_seqnum=? WHERE id=?",
                  (next_outbound_seqnum+1, self.cid))
        self.db.commit()
        seqnum_s = struct.pack(">Q", next_outbound_seqnum)
        my_signkey = SigningKey(res["my_signkey"].decode("hex"))
        privkey2 = PrivateKey.generate()
        pubkey2 = privkey2.public_key.encode()
        assert len(pubkey2) == 32
        crec = json.loads(res["their_channel_record_json"])
        channel_pubkey = crec["channel_pubkey"].decode("hex")
        channel_box = Box(privkey2, PublicKey(channel_pubkey))
        CIDKey = crec["CID_key"].decode("hex")

        authenticator = b"ce0:"+pubkey2
        msgE = "".join([seqnum_s,
                        netstring(my_signkey.sign(authenticator)),
                        json.dumps(payload).encode("utf-8"),
                        ])
        msgD = pubkey2 + channel_box.encrypt(msgE, os.urandom(Box.NONCE_SIZE))

        HmsgD = sha256(msgD).digest()
        CIDToken = build_CIDToken(CIDKey, next_outbound_seqnum)
        sb = SecretBox(CIDKey)
        CIDBox = sb.encrypt(seqnum_s+HmsgD+channel_pubkey,
                            os.urandom(sb.NONCE_SIZE))

        msgC = "".join([b"c0:",
                        CIDToken,
                        netstring(CIDBox),
                        msgD])
        return msgC

    def createTransports(self):
        c = self.db.cursor()
        c.execute("SELECT their_channel_record_json"
                  " FROM addressbook WHERE id=?", (self.cid,))
        res = c.fetchone()
        assert res, "missing cid"
        crec = json.loads(res["their_channel_record_json"])
        return [make_transport(self.db, t) for t in crec["transports"]]
