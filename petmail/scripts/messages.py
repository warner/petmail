import json
from .webwait import follow_events

def render_message(msg):
    lines = []
    lines.append('== %d: from %s (cid=%d #%d):' % (
        msg["id"], msg["petname"], msg["cid"], msg["seqnum"]))
    payload = json.loads(msg["payload_json"])
    if "basic" in payload:
        lines.append(" basic: " + payload["basic"])
    else:
        lines.append(str(msg["payload_json"]))
    return "\n".join(lines)+"\n"

class EOFError(Exception):
    pass

def get_line(r):
    buf = ""
    while True:
        data = r.read(1)
        if not data:
            raise EOFError
        if data == "\n":
            return buf
        buf += data

def get_field(r):
    first_line = get_line(r)
    fieldname, data = first_line.split(": ", 1)
    lines = [data]
    while True:
        line = get_line(r)
        if not line:
            return fieldname, "\n".join(lines)
        lines.append(line)


def follow_messages(so, stdout, stderr):
    try:
        resp = follow_events(so["basedir"], "messages", catchup=True)
        if resp.status != 200:
            print >>stderr, "Error:", resp.status, resp.reason
            return 1
        # httplib is not really built to read a stream of lines
        while True:
            fieldname, value = get_field(resp)
            if fieldname == "data":
                data = json.loads(value)
                if data["type"] == "inbound-messages":
                    stdout.write(render_message(data["new_value"]))
                    stdout.flush()
    except (KeyboardInterrupt, EOFError):
        return 0
