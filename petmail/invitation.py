import re, os, json
from twisted.application import service
from .hkdf import HKDF
from .errors import CommandError
from .eventual import eventually
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

class InvitationManager:
    """I manage all invitations."""
    def __init__(self, db):
        self.db = db

    def thaw_invitations(self):
        c = self.db.execute("SELECT * FROM invitations")
        ds = []
        for row in c.fetchall():
            yield Invitation(int(row["id"]), self.db)

    def create_invitation(self, channel_id, code, signed_payload):
        # "payload" goes to them
        iid = db.insert("INSERT INTO `invitations`"
                        " (channel_id, code, wormhole_data, payload_for_them)"
                        " VALUES (?,?,?,?)",
                        (channel_id, code, None, signed_payload.encode("hex")),
                        "invitations")
        return Invitation(iid, self.db)

class Invitation:
    # This object is created in manager.activate_one_invitation(), one tick
    # after the Invite button is pressed. It will also be created at the next
    # process startup, for any outstanding invites listed in the database
    # from before, in manager.activate_all_invitations(). It is destroyed
    # when the invitation process is complete, at which point the database
    # entry is removed.

    def __init__(self, iid, db):
        self.iid = iid
        self.db = db

    def activate(self):
        # fires with the peer's data, and an uncommitted DELETE
        c = self.db.execute("SELECT * FROM invitations WHERE id=?", (self.iid,))
        res = c.fetchone()
        if not res:
            raise KeyError("no pending Invitation for '%d'" % self.iid)
        self.channel_id = int(row["channel_id"])
        wormhole_data = res["wormhole"]
        payload_for_them = res["payload_for_them"].decode("hex")
        code = res["code"]
        if wormhole_data is None:
            self.w = SymmetricWormhole(appid, payload_for_them,
                                       wormhole.public_relay.RENDEZVOUS_RELAY)
            if code:
                self.w.set_code(str(code))
            d = self.w.get_code()
            d.addCallback(self._got_code) # saves to DB
        else:
            self.w = SymmetricWormhole.from_serialized(wormhole_data)
            d = defer.succeed(None)
        d.addCallback(lambda _: self.w.get_data())
        d.addCallback(self._got_data)
        return d

    def _got_code(self, code):
        wormhole_data = self.w.serialize()
        self.db.execute("UPDATE invitations SET"
                        " wormhole=?"
                        " WHERE id=?", (wormhole_data, self.iid),
                        "invitations", self.iid)
        self.db.execute("UPDATE addressbook SET"
                        " invitation_code=?"
                        " WHERE id=?", (code, self.channel_id),
                        "addressbook", self.channel_id)
        self.db.commit()
        return d

    def _got_data(self, data):
        self.db.execute("DELETE FROM invitations WHERE id=?", (self.iid,),
                        "invitations", self.iid)
        # let agent modify 'addressbook' and do the commit
        return data
