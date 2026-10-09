import urllib.request
import ssl

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

urls = [
    'https://recetagenial.com/test-slug-123456',
    'https://recetagenial.com/quitar-verrugas-de-forma-natural',
    'https://recetagenial.com/aperitivos',
    'https://recetagenial.com/$',
    'https://recetagenial.com/ensalada-de-pasta-fria',
    'https://recetagenial.com/this-page-definitely-does-not-exist-xyz'
]

for u in urls:
    try:
        req = urllib.request.Request(u, headers={'User-Agent': 'Googlebot/2.1 (+http://www.google.com/bot.html)'})
        with urllib.request.urlopen(req, context=ctx, timeout=10) as resp:
            content = resp.read().decode('utf-8', errors='ignore')
            title_start = content.find('<title>')
            title_end = content.find('</title>')
            title = content[title_start:title_end+8] if title_start != -1 else 'No title'
            print(f"{u} -> HTTP {resp.status} | len {len(content)} | title: {title}")
    except urllib.error.HTTPError as e:
        print(f"{u} -> HTTP ERROR {e.code}")
    except Exception as e:
        print(f"{u} -> ERROR {e}")
