import base64

def b2a(binary):
    return base64.b32encode(binary).rstrip("=").lower()

def a2b(ascii):
    l = len(ascii)
    assert l%8 in (0,2,4,5,7), (l,ascii)
    ascii += "="*{0:0, 1:"?", 2:6, 3:"?",
                  4:4, 5:3, 6:"?", 7:1}[len(ascii)%8]
    return base64.b32decode(ascii.upper())
