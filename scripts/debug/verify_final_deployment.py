import time
import urllib.request
import ssl

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None

opener = urllib.request.build_opener(NoRedirect)

print("Waiting 35s for Vercel deployment of commit 6ae9377...")
time.sleep(35)

test_urls = [
    'https://recetagenial.com/aperitivos',
    'https://recetagenial.com/helado-pistacho-siciliano',
    'https://recetagenial.com/cocido-madrileno-completo-tradicional',
    'https://recetagenial.com/tarta-de-queso-la-vina-receta-autentica',
    'https://recetagenial.com/quitar-verrugas-de-forma-natural',
    'https://recetagenial.com/test-slug-123456',
    'https://recetagenial.com/bizcocho-en-taza-mug-cake-de-zanahoria-test',
    'https://recetagenial.com/test-milanesa-genial',
    'https://recetagenial.com/pipeline-integration-test-tarta-de-limon-rapida-20260424134100',
    'https://recetagenial.com/helado-de-fresas-con-crema-la-receta-definitiva-y-cremosa',
    'https://recetagenial.com/ensalada-de-pasta-fria',
    'https://recetagenial.com/&',
]

print("\nTesting live deployed endpoints:")
for url in test_urls:
    try:
        resp = opener.open(url)
        loc = resp.headers.get("Location", "")
        print(f"{url} -> STATUS {resp.status} | Location: {loc}")
    except urllib.error.HTTPError as e:
        loc = e.headers.get("Location", "")
        print(f"{url} -> HTTP {e.code} | Location: {loc}")
    except Exception as e:
        print(f"{url} -> ERROR: {e}")
