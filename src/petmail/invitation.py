import weakref
from wormhole.twisted.transcribe import Wormhole
from twisted.internet import defer
from .eventual import eventually

INVITE_WAITING_FOR_CODE = 0
INVITE_WAITING_TO_COMPLETE = 1
INVITE_COMPLETE = 2

class InvitationManager:
    """I manage all invitations."""
    def __init__(self, db, relay):
        self.db = db
        self.relay = relay
        self.appid = "petmail"
        self._debug_invitations = weakref.WeakValueDictionary()

    def thaw_invitations(self):
        c = self.db.execute("SELECT * FROM addressbook"
                            " WHERE invitation_state != ?", (INVITE_COMPLETE,))
        for row in c.fetchall():
            channel_id = int(row["id"])
            i = Invitation(channel_id, self.db, self.appid, self.relay)
            self._debug_invitations[channel_id] = i
            yield i

    def create_invitation(self, channel_id):
        # "payload" goes to them
        i = Invitation(channel_id, self.db, self.appid, self.relay)
        self._debug_invitations[channel_id] = i
        return i

class Invitation:
    # This object is created in manager.activate_one_invitation(), one tick
    # after the Invite button is pressed. It will also be created at the next
    # process startup, for any outstanding invites listed in the database
    # from before, in manager.activate_all_invitations(). It is destroyed
    # when the invitation process is complete, at which point the database
    # entry is removed.

    def __init__(self, channel_id, db, appid, relay):
        self.channel_id = channel_id
        self.db = db
        self.appid = appid
        self.relay = relay
        self._debug_when_got_code = None

    def activate(self):
        # fires with peerdata
        c = self.db.execute("SELECT * FROM addressbook WHERE id=?",
                            (self.channel_id,))
        row = c.fetchone()
        if not row:
            raise KeyError("no pending Invitation for '%d'" % self.channel_id)
        wormhole_data = row["wormhole"]
        payload_for_them = row["wormhole_payload"].decode("hex")
        self.code = row["invitation_code"]
        if wormhole_data is None:
            self.w = Wormhole(self.appid, self.relay)
            if self.code:
                self.w.set_code(str(self.code))
                d = defer.succeed(str(self.code))
            else:
                d = self.w.get_code()
            d.addCallback(self._got_code) # saves to DB
        else:
            assert self.code is not None
            self.w = Wormhole.from_serialized(wormhole_data)
            d = defer.succeed(None)
        d.addCallback(lambda _: self.w.get_data(payload_for_them))
        return d

    def _got_code(self, code):
        self.code = code
        wormhole_data = self.w.serialize()
        self.db.update("UPDATE addressbook SET"
                       " invitation_state=?,"
                       " invitation_code=?, wormhole=?"
                       " WHERE id=?", (INVITE_WAITING_TO_COMPLETE,
                                       code, wormhole_data,
                                       self.channel_id),
                       "addressbook", self.channel_id)
        self.db.commit()
        if self._debug_when_got_code:
            eventually(self._debug_when_got_code.callback, code)
