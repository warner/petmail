
import sys
from nacl.signing import VerifyKey

for fn in sys.argv[1:]:
    vk = VerifyKey(fn.split("/")[-2].decode("hex"))
    sm = open(fn,"rb").read()
    assert sm.startswith("r0:")
    m = vk.verify(sm[len("r0:"):].decode("hex"))
    print fn.split("/")[-1][:10], ":", repr(m[:12]), "..."
