import urllib.request
import ssl

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None

opener = urllib.request.build_opener(NoRedirect)

test_urls = [
    ('https://recetagenial.com/aperitivos', 'Expected 308/301 Redirect'),
    ('https://recetagenial.com/helado-pistacho-siciliano', 'Expected 308/301 Redirect to /categoria/postres'),
    ('https://recetagenial.com/cocido-madrileno-completo-tradicional', 'Expected 308/301 Redirect to canonical'),
    ('https://recetagenial.com/tarta-de-queso-la-vina-receta-autentica', 'Expected 308/301 Redirect to canonical'),
    ('https://recetagenial.com/test-slug-123456', 'Expected 410 Gone / 404'),
    ('https://recetagenial.com/quitar-verrugas-de-forma-natural', 'Expected 410 Gone / 404'),
    ('https://recetagenial.com/$', 'Expected 410 Gone / 404'),
    ('https://recetagenial.com/&', 'Expected 410 Gone / 404'),
    ('https://recetagenial.com/pipeline-integration-test-tarta-de-limon-rapida-20260424134100', 'Expected 410 Gone / 404'),
]

for url, expected in test_urls:
    try:
        resp = opener.open(url)
        loc = resp.headers.get('Location', '')
        print(f"{url} -> STATUS {resp.status} | Location: {loc} ({expected})")
    except urllib.error.HTTPError as e:
        loc = e.headers.get('Location', '')
        robots = e.headers.get('X-Robots-Tag', '')
        print(f"{url} -> HTTP {e.code} | Location: {loc} | Robots: {robots} ({expected})")
    except Exception as e:
        print(f"{url} -> ERROR: {e}")
