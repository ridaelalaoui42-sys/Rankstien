import urllib.request
import ssl
import re

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

req = urllib.request.Request('https://recetagenial.com/test-slug-123456')
with urllib.request.urlopen(req, context=ctx) as r:
    html = r.read().decode('utf-8', errors='ignore')
    meta_robots = re.findall(r'<meta[^>]*name=["\'](?:robots|googlebot)["\'][^>]*>', html)
    print("Meta robots tags:", meta_robots)
