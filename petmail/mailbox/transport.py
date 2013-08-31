
"""
I know how to build a msgC into a msgA, and how to parse msgA into a msgC.
"""

import os
from .. import rrid
from .delivery.http import OutboundHTTPTransport
from nacl.public import PrivateKey, PublicKey, Box

def make_transport(db, trecord):
    assert trecord["type"] == "http"
    return OutboundHTTPTransport(db, trecord)

def createMsgA(desc, msgC):
    MSTID = rrid.rerandomize(desc["STID"])
    msgB = MSTID + msgC

    privkey1 = PrivateKey.generate()
    pubkey1 = privkey1.public_key.encode()
    assert len(pubkey1) == 32
    transport_pubkey = desc["transport_pubkey"].decode("hex")
    transport_box = Box(privkey1, PublicKey(transport_pubkey))

    msgA = pubkey1 + transport_box.encrypt(msgB, os.urandom(Box.NONCE_SIZE))
    return msgA
