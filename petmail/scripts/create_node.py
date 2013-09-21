import os, json
from nacl.public import PrivateKey
from .. import rrid, database, util

def create_node(so, stdout, stderr, services):
    basedir = so["basedir"]
    if os.path.exists(basedir):
        print >>stderr, "basedir '%s' already exists, refusing to touch it" % basedir
        return 1
    os.mkdir(basedir)
    dbfile = os.path.join(basedir, "petmail.db")
    db = database.get_db(dbfile, stderr)
    listenport = so["listen"]
    if not listenport:
        # pick a free local port. If you want the node to be reachable from
        # outside, choose the port at node-creation time.
        listenport = "tcp:%d:interface=127.0.0.1" % util.allocate_port()
    hostname = so["hostname"]
    port = so["port"]
    if not port:
        assert listenport.startswith("tcp:"), listenport
        port = listenport.split(":")[1]
    port = int(port)
    baseurl = "http://%s:%d/" % (hostname, port)

    db.execute("INSERT INTO node (listenport, baseurl) VALUES (?,?)",
               (listenport, baseurl))
    if "relay" in services:
        db.execute("INSERT INTO services (name) VALUES (?)", ("relay",))
    if "agent" in services:
        if so["relay-url"]:
            relay_url = so["relay-url"]
            if not relay_url.endswith("/"):
                relay_url += "/"
            desc = json.dumps({"type": "http", "url": relay_url})
            db.execute("INSERT INTO relay_servers (descriptor_json) VALUES (?)",
                       (desc,))
        else:
            db.execute("INSERT INTO relay_servers (descriptor_json) VALUES (?)",
                       (json.dumps({"type": "localdir"}),))
        db.execute("INSERT INTO services (name) VALUES (?)", ("agent",))
        db.execute("INSERT INTO `agent_profile`"
                   " (`name`, `icon_data`) VALUES (?,?)",
                   ("",""))
        transport_privkey = PrivateKey.generate().encode()
        retrieval_privkey = PrivateKey.generate().encode()
        TT_privkey,TT_pubkey = rrid.create_keypair()
        server_desc = { "transport_privkey": transport_privkey.encode("hex"),
                        "retrieval_privkey": retrieval_privkey.encode("hex"),
                        "TT_private_key": TT_privkey.encode("hex"),
                        "TT_public_key": TT_pubkey.encode("hex"),
                        }
        db.execute("INSERT INTO mailbox_server_config"
                   " (mailbox_config_json)"
                   " VALUES (?)",
                   (json.dumps(server_desc),))
    db.commit()
    print >>stdout, "node created in %s, URL is %s" % (basedir, baseurl)

    petmail = so.get("petmail-executable")
    if petmail:
        pe_fn = os.path.join(basedir, "petmail")
        pe = open(pe_fn, "w")
        pe.write("#!/bin/sh\n")
        pe.write("%s -d %s $*\n" % (os.path.abspath(petmail),
                                    os.path.abspath(basedir)))
        pe.close()
        os.chmod(pe_fn, 0755)

    return 0

def print_baseurl(so, stdout, stderr):
    basedir = so["basedir"]
    dbfile = os.path.join(basedir, "petmail.db")
    if not (os.path.isdir(basedir) and os.path.exists(dbfile)):
        print >>stderr, "'%s' doesn't look like a Petmail basedir, quitting" % basedir
        return 1
    db = database.get_db(dbfile, stderr)
    row = db.execute("SELECT * FROM node").fetchone()
    baseurl = str(row["baseurl"])
    print >>stdout, baseurl
    return 0
