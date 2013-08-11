
import os, sys
from nacl.signing import VerifyKey

for channelID in os.listdir(sys.argv[1]):
    print "channel %s..:" % channelID[:5]
    vk = VerifyKey(channelID.decode("hex"))
    for msgid in os.listdir(os.path.join(sys.argv[1], channelID)):
        fn = os.path.join(sys.argv[1], channelID, msgid)
        sm = open(fn, "rb").read()
        assert sm.startswith("r0:")
        m = vk.verify(sm[len("r0:"):].decode("hex"))
        print " msg %s..: %s..." % (msgid[:10], repr(m[:12]))
