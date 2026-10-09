import zipfile
import csv
import io
import urllib.request
import ssl
from urllib.parse import urlparse

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None

opener = urllib.request.build_opener(NoRedirect)

z = zipfile.ZipFile(r'c:\Users\REDX420\Downloads\recetagenial.com-Coverage-Drilldown-2026-10-09.zip')
content = z.read('Table.csv').decode('utf-8', errors='ignore')
reader = csv.reader(io.StringIO(content))
next(reader)
urls = [r[0].strip() for r in reader if r]

print(f"Auditing all {len(urls)} URLs from Google Search Console report against live site...\n")

results = {'redirect_308': 0, 'redirect_301': 0, 'success_200': 0, 'error_404_410': 0, 'soft_404': 0, 'other': 0}
details = []

for u in urls:
    try:
        resp = opener.open(u)
        code = resp.status
        loc = resp.headers.get("Location", "")
        # If it returned 200, check whether it's an article or a soft 404
        if code == 200:
            html = resp.read().decode('utf-8', errors='ignore')
            if '<h1 id="not-found-title">' in html:
                results['soft_404'] += 1
                details.append((u, 'SOFT_404_DETECTED', 'Returned 200 with 404 body'))
            else:
                results['success_200'] += 1
                details.append((u, 'SUCCESS_200', 'Live valid recipe'))
        elif code in (301, 308):
            key = f'redirect_{code}'
            results[key] = results.get(key, 0) + 1
            details.append((u, f'REDIRECT_{code}', loc))
        else:
            results['other'] += 1
            details.append((u, f'STATUS_{code}', loc))
    except urllib.error.HTTPError as e:
        if e.code in (301, 308):
            key = f'redirect_{e.code}'
            results[key] = results.get(key, 0) + 1
            loc = e.headers.get("Location", "")
            details.append((u, f'REDIRECT_{e.code}', loc))
        elif e.code in (404, 410):
            results['error_404_410'] += 1
            details.append((u, f'HTTP_{e.code}', 'Clean 404/410 status'))
        else:
            results['other'] += 1
            details.append((u, f'HTTP_{e.code}', ''))
    except Exception as e:
        details.append((u, 'ERROR', str(e)))

print("=== FINAL LIVE AUDIT RESULTS ===")
for k, v in results.items():
    print(f"  {k}: {v}")

print(f"\nTotal verified: {len(details)}")
print(f"Remaining Soft 404s: {results['soft_404']}")

# Save report
with open(r'c:\Users\REDX420\Desktop\Rankstein\data\reports\soft404_remediation_report.json', 'w', encoding='utf-8') as f:
    import json
    json.dump({'summary': results, 'details': details}, f, indent=2)
print("Saved report to data/reports/soft404_remediation_report.json")
