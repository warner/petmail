
"""
I know how to build a msgC into a msgA, and how to parse msgA into a msgC.
"""

from ..util import remove_prefix, split_into
from ..netstring import split_netstrings_and_trailer
from .delivery.http import OutboundHTTPTransport
from .delivery.loopback import LoopbackTransport

def make_transport(db, trecord):
    if trecord["type"] == "loopback":
        return LoopbackTransport(db, trecord)
    elif trecord["type"] == "http":
        return OutboundHTTPTransport(db, trecord)
    else:
        raise ValueError("unknown transport '%s'" % trecord["type"])

def parseMsgA(msgA):
    key_and_boxed = remove_prefix(msgA, "a0:")
    pubkey1_s, boxed = split_into(key_and_boxed, [32], True)
    return pubkey1_s, boxed

def parseMsgB(msgB):
    (MSTID,),msgC = split_netstrings_and_trailer(msgB)
    return MSTID, msgC
