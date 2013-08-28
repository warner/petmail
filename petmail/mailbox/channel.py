import re
from .. import rrid
from ..errors import SilentError
from ..util import split_into, equal
from nacl.public import PrivateKey, PublicKey, Box
from nacl.signing import VerifyKey
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

    I am associated with a specific transport, and will only use channels
    that are connected to that transport. This protects against correlation
    attacks that combine a transport descriptor from one peer with a channel
    descriptor from a different one, in the hopes of proving that the two
    peers are actually the same.
    """

    def __init__(self, db):
        self.db = db
        self.CID_privkey = "??"

    def msgC_received(self, msgC):
        PREFIX = "c0:"
        if not msgC.startswith(PREFIX):
            raise ValueError("msgC doesn't start with '%s'" % PREFIX)
        splitpoints = [len(PREFIX), rrid.TOKEN_LENGTH, 32]
        _, MCID, pubkey2, enc = split_into(msgC, splitpoints, plus_trailer=True)
        ichannel = self.lookup(MCID)
        ichannel.msgC2_received(pubkey2, enc)

    def lookup(self, MCID):
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

class InboundChannel:
    """I am given a msgC. I will decrypt it, update the channel database
    records as necessary, and finally dispatch the payload to a handler.
    """
    def __init__(self, db, their_verfkey_hex):
        self.db = db
        self.their_verfkey_hex = their_verfkey_hex
        # do a DB fetch, grab everything we need
        c = self.db.cursor()
        c.execute("SELECT"
                  " my_old_channel_privkey, my_new_channel_privkey,"
                  " their_verfkey"
                  " FROM addressbook WHERE their_verfkey=?",
                  (their_verfkey_hex,))
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
                      " WHERE their_verfkey=?",
                      (self.their_verfkey_hex,))
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

