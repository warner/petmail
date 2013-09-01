# Import everything, just to check early for syntax errors. These might
# otherwise show up pretty late, since our CLI tools avoid importing anything
# too soon (to allow twisted to set up a non-default reactor)

from twisted.trial import unittest

class Import(unittest.TestCase):
    def test_import_all(self):
        from .. import _version, base32, client, database, errors, eventual
        del _version, base32, client, database, errors, eventual
        from .. import hkdf, invitation, netstring, node, rrid, util, web
        del hkdf, invitation, netstring, node, rrid, util, web

        from ..rendezvous import localdir
        del localdir

        from ..scripts import create_node, open, runner, startstop, webwait
        del create_node, open, runner, startstop, webwait

        from ..mailbox import channel, server, transport
        del channel, server, transport

        from ..mailbox.delivery import common, http, test
        del common, http, test

        from ..mailbox.retrieval import local as local2, from_http_server
        del local2, from_http_server
