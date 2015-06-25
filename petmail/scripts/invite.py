import json
from .webwait import command, follow_events, get_field, EOFError

def invite(so, stdout, stderr, offer_mailbox=False, accept_mailbox=False):
    args = {"petname": so.get("petname"),
            "code": so.get("code")}
    if offer_mailbox:
        args["offer_mailbox"] = True
    if accept_mailbox:
        args["accept_mailbox"] = True
    ok, result = command(so["basedir"], "invite", args, stderr)
    if not ok:
        print >>stderr, result["err"]
        return 1
    cid = result["contact-id"]
    if so.get("code") is not None:
        stdout.write("Invitation code: %s\n" % so["code"])
        stdout.flush()
        return 0
    # now follow the new addressbook entry until a code is allocated
    try:
        resp = follow_events(so["basedir"], "addressbook", catchup=True)
        if resp.status != 200:
            print >>stderr, "Error:", resp.status, resp.reason
            return 1
        # httplib is not really built to read a stream of lines
        while True:
            fieldname, value = get_field(resp)
            if fieldname == "data":
                data = json.loads(value)
                #print "D", data
                if (data["type"] == "addressbook"
                    and data["new_value"]["id"] == cid):
                    code = data["new_value"]["invitation_code"]
                    stdout.write("Invitation code: %s\n" % code)
                    stdout.flush()
                    return 0
    except (KeyboardInterrupt, EOFError):
        return 0
