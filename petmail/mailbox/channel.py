import re, struct, json, os
from hashlib import sha256
from .. import rrid
from ..errors import SilentError, ReplayError, WrongVerfkeyError
from ..util import split_into, equal, verify_with_prefix
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

class ChannelManager:
    """I receive inbound messages from transports, figure out which channel
    they're directed to, then I will create a Channel instance and pass it
    the message for decryption and delivery.

    For each message, I am told which transport it arrived on. I will only
    use channels that are connected to that transport. This protects against
    correlation attacks that combine a transport descriptor from one peer
    with a channel descriptor from a different one, in the hopes of proving
    that the two peers are actually the same.
    """

    def __init__(self, db):
        self.db = db
        self.CID_privkey = "??"

    def msgC_received(self, transportID, msgC):
        PREFIX = "c0:"
        if not msgC.startswith(PREFIX):
            raise ValueError("msgC doesn't start with '%s'" % PREFIX)
        splitpoints = [len(PREFIX), rrid.TOKEN_LENGTH, 32]
        _, MCID, pubkey2, enc = split_into(msgC, splitpoints, plus_trailer=True)
        ichannel = self.lookup(transportID, MCID)
        ichannel.msgC2_received(pubkey2, enc)

    def lookup(self, transportID, MCID):
        CID = rrid.decrypt(self.CID_privkey, MCID)
        # look through DB for the addressbook entry
        c = self.db.cursor()
        c.execute("SELECT their_verfkey FROM addressbook"
                  " WHERE my_private_CID=?", (CID,))
        results = c.fetchall()
        if not results:
            raise SilentError("unknown CID")
        their_verfkey_hex = results[0][0]
        # return an InboundChannel object for it
        return InboundChannel(self.db, their_verfkey_hex)

def parse_msgC(msgC):
    if not msgC.startswith("c0:"):
        raise ValueError("corrupt msgC")
    msgC = msgC[len("c0:"):]
    CIDToken = msgC[:32]
    (CIDBox,), msgD = split_netstrings_and_trailer(msgC[32:])
    return CIDToken, CIDBox, msgD

def decrypt_CIDBox(CIDKey, CIDBox):
    sb = SecretBox(CIDKey)
    m = sb.decrypt(CIDBox) # may raise CryptoError
    seqnum_s,HmsgD,channel_pubkey = split_into(m, [8, 32, 32])
    seqnum = struct.unpack(">Q", seqnum_s)[0]
    return seqnum, HmsgD, channel_pubkey

def decrypt_msgD(msgD, privkeys):
    pubkey2_s, enc = split_into(msgD, [32], True)
    pubkey2 = PublicKey(pubkey2_s)
    for (privkey_hex, keyid) in privkeys:
        try:
            privkey = PrivateKey(privkey_hex.decode("hex"))
            msgE = Box(privkey, pubkey2).decrypt(enc)
            return msgE, keyid, pubkey2_s
        except CryptoError:
            pass

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

def find_channel_from_CIDToken(db, CIDToken):
    # XXX not implemented
    cid = None
    which_channel_key = None # e.g. unknown
    return cid, which_channel_key

def find_channel_from_CIDBox(db, CIDBox):
    c = db.cursor()
    c.execute("SELECT id, my_CID_key,"
              " my_old_channel_privkey, my_new_channel_privkey"
              " FROM addressbook")
    for row in c.fetchall():
        try:
            CIDKey = row["my_CID_key"].decode("hex")
            seqnum, HmsgD, channel_pubkey = decrypt_CIDBox(CIDKey, CIDBox)
            which_channel_key = None
            old_priv = PrivateKey(row["my_old_channel_privkey"].decode("hex"))
            if channel_pubkey == old_priv.public_key.encode():
                which_channel_key = "old"
            new_priv = PrivateKey(row["my_new_channel_privkey"].decode("hex"))
            if channel_pubkey == new_priv.public_key.encode():
                which_channel_key = "new"
            return row["id"], which_channel_key
        except CryptoError:
            pass
    return None, None

class InboundChannel:
    """I am given a msgC. I will decrypt it, update the channel database
    records as necessary, and finally dispatch the payload to a handler.
    """
    def __init__(self, db, channelID, channel_pubkey):
        self.db = db
        self.channelID = channelID # addressbook.id
        # do a DB fetch, grab everything we need
        c = self.db.cursor()
        c.execute("SELECT"
                  " my_old_channel_privkey, my_new_channel_privkey,"
                  " their_verfkey"
                  " FROM addressbook WHERE id=?", (channelID,))
        row = c.fetchone()
        self.my_new_channel_privkey = PrivateKey(row["my_old_channel_privkey"].decode("hex"))
        self.my_old_channel_privkey = PrivateKey(row["my_new_channel_privkey"].decode("hex"))
        self.their_verfkey = VerifyKey(row["their_verfkey"].decode("hex"))

    def msgC2_received(self, pubkey2, enc):
        # try both channel keys, new one first
        pub = PublicKey(pubkey2)
        b = Box(self.my_new_channel_privkey, pub)
        they_used_new_channel_key = False
        try:
            msgD = b.decrypt(enc)
            they_used_new_channel_key = True
        except CryptoError:
            # try the old key
            try:
                b = Box(self.my_old_channel_privkey, pub)
                msgD = b.decrypt(enc)
            except CryptoError:
                raise SilentError("neither channel key worked")
        if they_used_new_channel_key:
            c = self.db.cursor()
            c.execute("UPDATE addressbook SET they_used_new_channel_key=1"
                      " WHERE id=?", (self.channelID,))
            self.db.commit()

        # now parse and process msgD
        # msgD: sign(by=sender-signkey,pubkey2) + body
        # netstring plus trailer
        mo = re.search(r'^(\d+):', msgD)
        if not mo:
            raise SilentError("msgD lacks a netstring header")
        p1_len = int(mo.group(1))
        h,sm,comma,body = split_into([len(mo.group(1))+1, # netstring header
                                      p1_len, # signed message
                                      1, # netstring trailer comma
                                      ], plus_trailer=True)
        if comma != ",":
            raise SilentError("msgD has bad netstring trailer")
        m = self.their_verfkey.verify(sm)
        # 'm' is supposed to contain the ephemeral pubkey used in the
        # enclosing encrypted box. This confirms (to us) that the addressbook
        # peer really did want to send this message, without enabling us to
        # convince anyone else of this fact.
        if not equal(m, pubkey2):
            raise SilentError("msgD authentication check failed")

        # ok, body is good
        self.bodyReceived(body)

    def bodyReceived(self, body):
        pass

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
        t = self.createTransport()
        # now wrap msgC into a msgA for each transport they're using
        return t.send(msgC)

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
        CIDToken = HKDF(IKM=CIDKey+seqnum_s, dkLen=32,
                        info=b"petmail.org/v1/CIDToken")
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
