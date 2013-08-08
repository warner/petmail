
import sys
from .webwait import command

def invite(so, out=sys.stdout, err=sys.stderr):
    args = {"petname": so["petname"],
            "code": so["code"]}
    ok, result = command(so["basedir"], "invite", args, err)
    if ok:
        print >>out, result["text"]
        return 0
    else:
        print >>err, result["err"]
        return 1
