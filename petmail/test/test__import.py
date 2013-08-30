# Import everything, just to check early for syntax errors. These might
# otherwise show up pretty late, since our CLI tools avoid importing anything
# too soon (to allow twisted to set up a non-default reactor)

from twisted.trial import unittest

class Import(unittest.TestCase):
    def test_import_all(self):
        from .. import _version, base32, client, database, errors, hkdf
        del _version, base32, client, database, errors, hkdf
        from .. import invitation, node, rrid, util, web
        del invitation, node, rrid, util, web

        from ..rendezvous import localdir
        del localdir

        from ..scripts import create_node, open, runner, startstop, webwait
        del create_node, open, runner, startstop, webwait

        from ..mailbox import channel, server
        del channel, server

        from ..mailbox.delivery import http, transport
        del http, transport

        from ..mailbox.retrieval import direct, direct_http, from_http_server
        del direct, direct_http, from_http_server
