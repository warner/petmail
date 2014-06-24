import os, base64, hashlib
from twisted.internet import tcp, protocol
from .errors import BadSignatureError

class BadPrefixError(Exception):
    pass

def remove_prefix(s_bytes, prefix, errortype=None):
    if not s_bytes.startswith(prefix):
        errortype = errortype or BadPrefixError
        raise errortype("did not see expected '%s' prefix" % (prefix,))
    return s_bytes[len(prefix):]

def to_ascii(s_bytes, prefix="", encoding="base64"):
    """Return a version-prefixed ASCII representation of the given binary
    string. 'encoding' indicates how to do the encoding, and can be one of:
     * base64
     * base32
     * base16 (or hex)

    This function handles bytes, not bits, so it does not append any trailing
    '=' (unlike standard base64.b64encode). It also lowercases the base32
    output.

    'prefix' will be prepended to the encoded form, and is useful for
    distinguishing the purpose and version of the binary string. E.g. you
    could prepend 'pub0-' to a VerifyingKey string to allow the receiving
    code to raise a useful error if someone pasted in a signature string by
    mistake.
    """
    if encoding == "base64":
        s_ascii = base64.b64encode(s_bytes).rstrip("=")
    elif encoding == "base32":
        s_ascii = base64.b32encode(s_bytes).rstrip("=").lower()
    elif encoding in ("base16", "hex"):
        s_ascii = base64.b16encode(s_bytes).lower()
    else:
        raise NotImplementedError
    return prefix+s_ascii

def from_ascii(s_ascii, prefix="", encoding="base64"):
    """This is the opposite of to_ascii. It will throw BadPrefixError if
    the prefix is not found.
    """
    s_ascii = remove_prefix(s_ascii.strip(), prefix)
    if encoding == "base64":
        s_ascii += "="*((4 - len(s_ascii)%4)%4)
        s_bytes = base64.b64decode(s_ascii)
    elif encoding == "base32":
        s_ascii += "="*((8 - len(s_ascii)%8)%8)
        s_bytes = base64.b32decode(s_ascii.upper())
    elif encoding in ("base16", "hex"):
        s_bytes = base64.b16decode(s_ascii.upper())
    else:
        raise NotImplementedError
    return s_bytes

def make_nonce():
    return base64.b32encode(os.urandom(32)).strip("=").lower()

def equal(a, b):
    # not vulnerable to timing attack
    return hashlib.sha256(a).digest() == hashlib.sha256(b).digest()

def split_into(s, piece_sizes, plus_trailer=False):
    assert type(s) == type(b"")
    pieces = []
    piece_start = 0
    for size in piece_sizes:
        piece_end = piece_start+size
        pieces.append(s[piece_start:piece_end])
        piece_start = piece_end
    if plus_trailer:
        pieces.append(s[piece_start:])
    else:
        if piece_start != len(s):
            raise ValueError("split did not consume entire string")
    return pieces

def verify_with_prefix(vk, sm, prefix):
    m = vk.verify(sm)
    if not m.startswith(prefix):
        raise BadSignatureError("missing expected prefix")
    return m[len(prefix):]

# fake Reactor (at least the clock portion), used by allocate_port()
class FakeClock:
    def callLater(self, delay, callback, *args):
        callback(*args)
    def addReader(self, _):
        pass
    def removeReader(self, _):
        pass
    def removeWriter(self, _):
        pass

def allocate_port(extra_deferreds=None):
    p = tcp.Port(0, protocol.Factory(), reactor=FakeClock())
    p.startListening()
    port = p.getHost().port
    from twisted.python import log
    log.msg("allocate_port got %d" % port)
    # stopListening() schedules a cleanup function to run on a later reactor
    # turn, and doesn't actually close the socket until then. I want this to
    # be synchronous, so it uses the FakeClock that runs that turn right
    # away. I believe this is safe (since we aren't actually connecting
    # anything to this port, or sending any data), but I could be wrong.
    d = p.stopListening()
    if extra_deferreds:
        extra_deferreds.append(d)
    # else ignore the Deferred
    return port

def hex_or_none(s):
    if s:
        return s.encode("hex")
    return s

def unhex_or_none(hex):
    if hex:
        return hex.decode("hex")
    return hex
