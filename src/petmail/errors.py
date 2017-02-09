
class CommandError(Exception):
    def __init__(self, msg):
        self.msg = msg

class SilentError(Exception):
    # log and drop, don't reveal details to caller. The timing difference is
    # ok.
    pass

class ReplayError(Exception):
    pass

class WrongVerfkeyError(Exception):
    pass

class BadSignatureError(Exception):
    pass

class UnknownChannelError(Exception):
    """Message not decryptable by any of our channels."""

class ContactNotReadyError(Exception):
    pass
