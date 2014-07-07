import sys, base64

with open(sys.argv[1], "rb") as f:
    raw = f.read()
print "data:image/png;base64,%s" % base64.b64encode(raw)
