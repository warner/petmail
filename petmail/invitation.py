import json
import wormhole.public_relay
from wormhole.twisted.transcribe import SymmetricWormhole
from twisted.internet import defer

class InvitationManager:
    """I manage all invitations."""
    def __init__(self, db, relay=wormhole.public_relay.RENDEZVOUS_RELAY):
        self.db = db
        self.relay = relay
        self.appid = "petmail"

    def thaw_invitations(self):
        c = self.db.execute("SELECT * FROM invitations")
        for row in c.fetchall():
            yield Invitation(int(row["id"]), self.db, self.appid, self.relay)

    def create_invitation(self, channel_id, maybe_code, signed_payload):
        # "payload" goes to them
        iid = self.db.insert("INSERT INTO `invitations`"
                             " (channel_id, code, wormhole_data, payload_for_them)"
                             " VALUES (?,?,?,?)",
                             (channel_id, maybe_code, None,
                              signed_payload.encode("hex")),
                             "invitations")
        return Invitation(iid, self.db, self.appid, self.relay)

class Invitation:
    # This object is created in manager.activate_one_invitation(), one tick
    # after the Invite button is pressed. It will also be created at the next
    # process startup, for any outstanding invites listed in the database
    # from before, in manager.activate_all_invitations(). It is destroyed
    # when the invitation process is complete, at which point the database
    # entry is removed.

    def __init__(self, iid, db, appid, relay):
        self.iid = iid
        self.db = db
        self.appid = appid
        self.relay = relay

    def activate(self):
        # fires with the peer's data, and an uncommitted DELETE
        c = self.db.execute("SELECT * FROM invitations WHERE id=?", (self.iid,))
        row = c.fetchone()
        if not row:
            raise KeyError("no pending Invitation for '%d'" % self.iid)
        self.channel_id = int(row["channel_id"])
        wormhole_data = row["wormhole"]
        payload_for_them = row["payload_for_them"].decode("hex")
        code = row["code"]
        if wormhole_data is None:
            self.w = SymmetricWormhole(self.appid, self.relay)
            if code:
                self.w.set_code(str(code))
                d = defer.succeed(str(code))
            else:
                d = self.w.get_code()
            d.addCallback(self._got_code) # saves to DB
        else:
            self.w = SymmetricWormhole.from_serialized(wormhole_data)
            d = defer.succeed(None)
        d.addCallback(lambda _: self.w.get_data(payload_for_them))
        d.addCallback(self._got_data)
        d.addBoth(self._remove_invitation)
        return d

    def _got_code(self, code):
        wormhole_data = self.w.serialize()
        self.db.update("UPDATE invitations SET"
                       " code=?, wormhole=?"
                       " WHERE id=?", (wormhole_data, code, self.iid),
                       "invitations", self.iid)
        self.db.update("UPDATE addressbook SET"
                       " invitation_code=?"
                       " WHERE id=?", (code, self.channel_id),
                       "addressbook", self.channel_id)
        self.db.commit()

    def _got_data(self, data):
        return json.loads(data.decode("utf-8"))

    def _remove_invitation(self, data):
        self.db.delete("DELETE FROM invitations WHERE id=?", (self.iid,),
                       "invitations", self.iid)
        self.db.update("UPDATE addressbook"
                       " SET invitation_id=NULL"
                       " WHERE id=?", (self.channel_id,),
                       "addressbook", self.channel_id)
        # let agent add the record to 'addressbook' and do the commit
        return data
