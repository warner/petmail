
"""
I know how to build a msgC into a msgA, and how to parse msgA into a msgC.
"""

import os
from .. import rrid
from ..util import remove_prefix, split_into
from ..netstring import netstring, split_netstrings_and_trailer
from .delivery.http import OutboundHTTPTransport
from nacl.public import PrivateKey, PublicKey, Box

def make_transport(db, trecord):
    assert trecord["type"] == "http"
    return OutboundHTTPTransport(db, trecord)

# msgA:
#  a0:
#  pubkey1 [fixed-length]
#  enc(to=transport, from=key1, msgB)
# msgB:
#  netstring(MSTID)
#  msgC

def createMsgA(trec, msgC):
    MSTID = rrid.randomize(trec["STID"].decode("hex"))
    msgB = netstring(MSTID) + msgC

    privkey1 = PrivateKey.generate()
    pubkey1 = privkey1.public_key.encode()
    assert len(pubkey1) == 32
    transport_pubkey = trec["transport_pubkey"].decode("hex")
    transport_box = Box(privkey1, PublicKey(transport_pubkey))

    msgA = b"".join([b"a0:",
                     pubkey1,
                     transport_box.encrypt(msgB, os.urandom(Box.NONCE_SIZE))])
    return msgA

def parseMsgA(msgA):
    key_and_boxed = remove_prefix(msgA, "a0:")
    pubkey1_s, boxed = split_into(key_and_boxed, [32], True)
    return pubkey1_s, boxed

def parseMsgB(msgB):
    (MSTID,),msgC = split_netstrings_and_trailer(msgB)
    return MSTID, msgC
