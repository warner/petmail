# Import everything, just to check early for syntax errors. These might
# otherwise show up pretty late, since our CLI tools avoid importing anything
# too soon (to allow twisted to set up a non-default reactor)

from twisted.trial import unittest

class Import(unittest.TestCase):
    def test_import_all(self):
        from .. import _version, agent, database, errors, eventual
        del _version, agent, database, errors, eventual
        from .. import hkdf, invitation, netstring, node, rrid, util, web
        del hkdf, invitation, netstring, node, rrid, util, web

        from ..rendezvous import localdir, web_client
        del localdir, web_client

        from ..scripts import create_node, messages, open, runner, startstop, webwait
        del create_node, messages, open, runner, startstop, webwait

        from ..mailbox import channel, delivery, retrieval, server
        del channel, delivery, retrieval, server
