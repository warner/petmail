# Import everything, just to check early for syntax errors. These might
# otherwise show up pretty late, since our CLI tools avoid importing anything
# too soon (to allow twisted to set up a non-default reactor)

from twisted.trial import unittest

class Import(unittest.TestCase):
    def test_import_all(self):
        from .. import base32, client, database, errors, hkdf
        del base32, client, database, errors, hkdf
        from .. import invitation, node, rrid, util, web
        del invitation, node, rrid, util, web
        from ..mailbox import delivery, retrieval
        del delivery, retrieval
