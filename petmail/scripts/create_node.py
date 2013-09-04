import os, sys, json
from nacl.public import PrivateKey
from .. import rrid, database

def create_node(so, stdout=sys.stdout, stderr=sys.stderr):
    basedir = so["basedir"]
    if os.path.exists(basedir):
        print >>stderr, "basedir '%s' already exists, refusing to touch it" % basedir
        return 1
    os.mkdir(basedir)
    dbfile = os.path.join(basedir, "petmail.db")
    db = database.get_db(dbfile, stderr)
    db.execute("INSERT INTO node (webhost, webport) VALUES (?,?)",
               (so["webhost"], so["webport"]))
    db.execute("INSERT INTO services (name) VALUES (?)", ("client",))
    db.execute("INSERT INTO `client_profile`"
               " (`name`, `icon_data`) VALUES (?,?)",
               ("",""))
    privkey = PrivateKey.generate()
    TID_tokenid, TID_privkey, TID_token0 = rrid.create()
    server_desc = { "transport_privkey": privkey.encode().encode("hex"),
                    "TID_private_key": TID_privkey.encode("hex"),
                    "local_TID0": TID_token0.encode("hex"),
                    "local_TID_tokenid": TID_tokenid.encode("hex"),
                    }
    db.execute("INSERT INTO mailbox_server_config"
               " (private_descriptor_json, enable_retrieval)"
               " VALUES (?,?)",
               (json.dumps(server_desc), 0))
    db.commit()
    print >>stdout, "node created in %s" % basedir
    return 0
