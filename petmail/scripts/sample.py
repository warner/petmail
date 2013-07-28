
import sys
from .webwait import command

def sample(so, out=sys.stdout, err=sys.stderr):
    args = {}
    if so["success-object"]:
        args["success-object"] = True
    if so["error"]:
        args["error"] = True
    if so["server-error"]:
        args["server-error"] = True
    ok, result = command(so["basedir"], "sample", args, err)
    if ok:
        print >>out, result["ok"]
        return 0
    else:
        print >>err, result["err"]
        return 1
