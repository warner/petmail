import os
from twisted.trial import unittest
from nacl.public import PrivateKey
from nacl.secret import SecretBox
from nacl.exceptions import CryptoError
from ..mailbox import server, retrieval
from .common import flip_bit

class Roundtrip(unittest.TestCase):
    def test_list_request(self):
        serverkey = PrivateKey.generate()
        TID = "01234567" # 8 bytes
        req, tmppub = retrieval.encrypt_list_request(serverkey.public_key.encode(), TID)
        ts, got_tmppub, boxed0 = server.decrypt_list_request_1(req)
        got_TID = server.decrypt_list_request_2(got_tmppub, boxed0, serverkey)
        self.failUnlessEqual(TID, got_TID)

    def test_list_entry(self):
        symkey = os.urandom(32)
        tmppriv = PrivateKey.generate()
        tmppub = tmppriv.public_key.encode()
        entry, fetch_token, delete_token = server.create_list_entry(symkey, tmppub, 1234)
        got_fetch_token, got_delete_token, length = retrieval.decrypt_list_entry(entry, symkey, tmppub)
        self.failUnlessEqual(fetch_token, got_fetch_token)
        self.failUnlessEqual(delete_token, got_delete_token)
        self.failUnlessEqual(length, 1234)

    def test_fetch_response(self):
        symkey = os.urandom(32)
        fetch_token = os.urandom(32)
        msg = server.encrypt_fetch_response(symkey, fetch_token, "message C")
        got_msgC = retrieval.decrypt_fetch_response(symkey, fetch_token, msg)
        self.failUnlessEqual(got_msgC, "message C")

class More(unittest.TestCase):
    def test_list_request(self):
        now = 1379304213
        serverkey = PrivateKey("\x11"*32)
        serverpub = serverkey.public_key.encode()
        tmppriv = PrivateKey("\x22"*32)
        TID = "01234567" # 8 bytes
        req, tmppub = retrieval.encrypt_list_request(serverpub, TID,
                                                     now=now, tmppriv=tmppriv)
        self.failUnlessEqual(req.encode("hex"),
                             "523683150faa684ed28867b97f4a6a2dee5df8ce974e76b7018e3f22a1c4cf2678570f20eb8ba0e3826a6fa8c91fad9460cd297a4415545153679f5c")

        ts, got_tmppub, boxed0 = server.decrypt_list_request_1(req)
        self.failUnlessEqual(ts, now)
        self.failUnlessEqual(got_tmppub, tmppub)
        self.failUnlessEqual(got_tmppub, tmppriv.public_key.encode())
        self.failUnlessEqual(boxed0.encode("hex"),
                             "eb8ba0e3826a6fa8c91fad9460cd297a4415545153679f5c")
        got_TID = server.decrypt_list_request_2(got_tmppub, boxed0, serverkey)
        self.failUnlessEqual(TID, got_TID)

        self.failUnlessRaises(CryptoError,
                              server.decrypt_list_request_2,
                              got_tmppub, flip_bit(boxed0), serverkey)

    def test_list_entry(self):
        symkey = "\x33"*32
        tmppriv = PrivateKey("\x22"*32)
        tmppub = tmppriv.public_key.encode()
        nonce = "\x44"*24
        fetch_token = "\x55"*32
        delete_token = "\x66"*32
        entry, _, _ = server.create_list_entry(symkey, tmppub, 1234,
                                               nonce=nonce,
                                               fetch_token=fetch_token,
                                               delete_token=delete_token)
        self.failUnlessEqual(entry.encode("hex"),
                             "44444444444444444444444444444444444444444444444493bfe7ca844892fd16591ae4b33f7456de7e8c325b574bd3358cf86b79487b78c80e1d69dcd6324386821875ec8a60d9d3955d3fed0ab66882d0b7e956fe740b3f0329da39b19c0ca1cd9e38aa54be499bb36217ea7afba1d808c5afb85ddcd9e1f2193f32fc08e6f9fec1557403ba18c42ae6f4d18ba608ceb4e485de")

        # wrong message type
        msg2 = server.encrypt_fetch_response(symkey, fetch_token, "message C")
        self.failUnlessRaises(retrieval.NotListResponseError,
                              retrieval.decrypt_list_entry,
                              msg2, symkey, tmppub)

        # wrong tmppub
        self.failUnlessRaises(retrieval.WrongPubkeyError,
                              retrieval.decrypt_list_entry,
                              entry, symkey, flip_bit(tmppub))
        # corrupt message
        self.failUnlessRaises(CryptoError,
                              retrieval.decrypt_list_entry,
                              flip_bit(entry), symkey, tmppub)

    def test_fetch_response(self):
        symkey = "\x33"*32
        fetch_token = "\x55"*32
        nonce = "\x66"*24
        msg = server.encrypt_fetch_response(symkey, fetch_token, "message C",
                                            nonce=nonce)
        self.failUnlessEqual(msg.encode("hex"),
                             "6666666666666666666666666666666666666666666666668dbd5b1ba011ff2d84abfe2aae76c9e9a339a4c8668bd09c5d0c559ed0bd17276996b0293735e17c3e8e78d4ca529101e4f2f604cfd37f0fef4f89c2dea2ed")

        got_msgC = retrieval.decrypt_fetch_response(symkey, fetch_token, msg)
        self.failUnlessEqual(got_msgC, "message C")

        # wrong prefix
        list_entry = "44444444444444444444444444444444444444444444444493bfe7ca844892fd16591ae4b33f7456de7e8c325b574bd3358cf86b79487b78c80e1d69dcd6324386821875ec8a60d9d3955d3fed0ab66882d0b7e956fe740b3f0329da39b19c0ca1cd9e38aa54be499bb36217ea7afba1d808c5afb85ddcd9e1f2193f32fc08e6f9fec1557403ba18c42ae6f4d18ba608ceb4e485de"
        self.failUnlessRaises(retrieval.NotFetchResponseError,
                              retrieval.decrypt_fetch_response,
                              symkey, fetch_token, list_entry.decode("hex"))

        list_entry2 = SecretBox(symkey).encrypt("list:stuff", nonce)
        self.failUnlessRaises(retrieval.NotFetchResponseError,
                              retrieval.decrypt_fetch_response,
                              symkey, fetch_token, list_entry2)

        # wrong fetch_token
        self.failUnlessRaises(retrieval.WrongFetchTokenError,
                              retrieval.decrypt_fetch_response,
                              symkey, flip_bit(fetch_token), msg)
        # corrupt
        self.failUnlessRaises(CryptoError,
                              retrieval.decrypt_fetch_response,
                              symkey, fetch_token, flip_bit(msg))
