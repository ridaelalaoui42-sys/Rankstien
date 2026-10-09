import urllib.request
import ssl
import json
import re

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

url = 'https://recetagenial.com/tarta-tres-chocolates-mercadona'
req = urllib.request.Request(url, headers={'User-Agent': 'Googlebot/2.1'})
with urllib.request.urlopen(req, context=ctx) as r:
    html = r.read().decode('utf-8', errors='ignore')

schemas = re.findall(r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', html, re.DOTALL)
print(f"Total ld+json scripts found: {len(schemas)}")
for i, s in enumerate(schemas):
    print(f"\n--- Schema {i+1} ---")
    try:
        data = json.loads(s.strip())
        print("Type:", data.get('@type'))
        if '@graph' in data:
            print("Graph types:", [item.get('@type') for item in data['@graph']])
        print("Content:")
        print(json.dumps(data, indent=2))
    except Exception as e:
        print("JSON parse error:", e)
        print(s[:300])
