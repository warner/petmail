import json
from .webwait import follow_events

def render_message(msg):
    lines = []
    lines.append('== %d: from (cid=%d #%d):' % (
        msg["id"], msg["cid"], msg["seqnum"]))
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
    resp = follow_events(so["basedir"], "messages")
    if resp.status == 200:
        # httplib is not really built to read a stream of lines
        try:
            while True:
                fieldname, data = get_field(resp)
                if fieldname == "data":
                    stdout.write(render_message(json.loads(data)["new_value"]))
                    stdout.flush()
        except EOFError:
            return 0
    else:
        print >>stderr, "Error:", resp.status, resp.reason
        return 1
