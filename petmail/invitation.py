import weakref
from wormhole.twisted.transcribe import SymmetricWormhole
from twisted.internet import defer
from .eventual import eventually

class InvitationManager:
    """I manage all invitations."""
    def __init__(self, db, relay):
        self.db = db
        self.relay = relay
        self.appid = "petmail"
        self._debug_invitations = weakref.WeakValueDictionary()

    def thaw_invitations(self):
        c = self.db.execute("SELECT * FROM invitations")
        for row in c.fetchall():
            iid = int(row["id"])
            i = Invitation(iid, self.db, self.appid, self.relay)
            self._debug_invitations[iid] = i
            yield i

    def create_invitation(self, channel_id, maybe_code, signed_payload):
        # "payload" goes to them
        iid = self.db.insert("INSERT INTO `invitations`"
                             " (channel_id, code, wormhole, payload_for_them)"
                             " VALUES (?,?,?,?)",
                             (channel_id, maybe_code, None,
                              signed_payload.encode("hex")),
                             "invitations")
        i = Invitation(iid, self.db, self.appid, self.relay)
        self._debug_invitations[iid] = i
        return i

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
        self._debug_when_got_code = None

    def activate(self):
        # fires with (code, peerdata), and an uncommitted DELETE
        c = self.db.execute("SELECT * FROM invitations WHERE id=?", (self.iid,))
        row = c.fetchone()
        if not row:
            raise KeyError("no pending Invitation for '%d'" % self.iid)
        self.channel_id = int(row["channel_id"])
        wormhole_data = row["wormhole"]
        payload_for_them = row["payload_for_them"].decode("hex")
        self.code = row["code"]
        if wormhole_data is None:
            self.w = SymmetricWormhole(self.appid, self.relay)
            if self.code:
                self.w.set_code(str(self.code))
                d = defer.succeed(str(self.code))
            else:
                d = self.w.get_code()
            d.addCallback(self._got_code) # saves to DB
        else:
            assert self.code is not None
            self.w = SymmetricWormhole.from_serialized(wormhole_data)
            d = defer.succeed(None)
        d.addCallback(lambda _: self.w.get_data(payload_for_them))
        d.addCallback(self._got_data)
        d.addBoth(self._remove_invitation)
        return d

    def _got_code(self, code):
        self.code = code
        wormhole_data = self.w.serialize()
        self.db.update("UPDATE invitations SET"
                       " code=?, wormhole=?"
                       " WHERE id=?", (code, wormhole_data, self.iid),
                       "invitations", self.iid)
        self.db.commit()
        if self._debug_when_got_code:
            eventually(self._debug_when_got_code.callback, code)

    def _got_data(self, data):
        return (self.code, data)

    def _remove_invitation(self, res):
        self.db.delete("DELETE FROM invitations WHERE id=?", (self.iid,),
                       "invitations", self.iid)
        # let agent add the record to 'addressbook' and do the commit
        return res
