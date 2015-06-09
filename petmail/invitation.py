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

    def actiavte_all(self):
        c = self.db.execute("SELECT id FROM invitations")
        for row in c.fetchall():
            self.activate_one_invitation(c["id"])

    def create_invitation(self, cid, code, signed_payload):
        # "payload" goes to them
        iid = db.insert("INSERT INTO `invitations`"
                        " (channel_id, wormhole_data, stage, payload_for_them)"
                        " VALUES (?,?,?,?)",
                        (cid, None, 0, signed_payload.encode("hex")),
                        "invitations")
        eventually(self.activate_one_invitation, iid)
        return iid

    def activate_one_invitation(self, iid):
        i = Invitation(iid, self.db, self, self.agent)
        d = i.activate()
        return d

class Invitation:
    # This object is created in manager.activate_one_invitation(), one tick
    # after the Invite button is pressed. It will also be created at the next
    # process startup, for any outstanding invites listed in the database
    # from before, in manager.activate_all_invitations(). It is destroyed
    # when the invitation process is complete, at which point the database
    # entry is removed.

    def __init__(self, iid, db, manager, agent):
        self.iid = iid
        self.db = db
        self.manager = manager
        self.agent = agent

    def activate(self):
        c = self.db.execute("SELECT channel_id, wormhole,"
                            " payload_for_them"
                            " FROM invitations WHERE id=?", (iid,))
        res = c.fetchone()
        if not res:
            raise KeyError("no pending Invitation for '%d'" % iid)
        self.channel_id = int(res["channel_id"])
        wormhole_data = str(res["wormhole"])
        self.payload_for_them = res["payload_for_them"].decode("hex")
        if wormhole_data is None:
            self.w = WormholeInitiator()
            d = self.w.get_code()
            d.addCallback(self._got_code)
        else:
            self.w = WormholeInitiator.deserialize(wormhole_data)
            d = self.w.get_data(self.payload_for_them)
            d.addCallback(self._got_data)

    def _got_code(self, code):
        wormhole_data = self.w.serialize()
        self.db.execute("UPDATE invitations SET"
                        " wormhole=?"
                        " WHERE id=?", (wormhole_data, self.iid),
                        "invitations", self.iid)
        self.db.commit()
        d = self.w.get_data(self.payload_for_them)
        d.addCallback(self._got_data)
        return d

    def _got_data(self, data):
        self.db.execute("DELETE FROM invitations WHERE id=?", (self.iid,),
                        "invitations", self.iid)
        # let agent do the commit
        self.agent.invitation_done(self.channel_id, data)
