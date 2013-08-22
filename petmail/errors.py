
class CommandError(Exception):
    def __init__(self, msg):
        self.msg = msg

class SilentError(Exception):
    # log and drop, don't reveal details to caller. The timing difference is
    # ok.
    pass
