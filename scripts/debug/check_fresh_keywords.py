import sys
from pathlib import Path
import re

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from rankstein.domain import get_registry
from rankstein.keyword_roadmap import read_keyword_rows
from rankstein_mcp_server import _supabase_request_headers, get_supabase_session

session = get_supabase_session()
for handle in ['recetadolce', 'recetagenial']:
    domain = get_registry().get(handle)
    url = domain.supabase_url
    key = domain.supabase_service_role_key.get_secret_value()
    headers = _supabase_request_headers(key)
    rows = read_keyword_rows(domain.keywords_file)
    pending = [r for r in rows if r.status == 'Pending']
    print(f'=== {handle}: {len(pending)} pending keywords ===')
    fresh = []
    for r in pending:
        raw_slug = r.keyword.lower().strip()
        for c, rep in [('á', 'a'), ('é', 'e'), ('í', 'i'), ('ó', 'o'), ('ú', 'u'), ('ñ', 'n'), (' ', '-')]:
            raw_slug = raw_slug.replace(c, rep)
        slug = re.sub(r'[^a-z0-9\-]', '', raw_slug)
        try:
            resp = session.get(f'{url}/rest/v1/posts?slug=eq.{slug}&select=id', headers=headers, timeout=5)
            if resp.status_code == 200 and not resp.json():
                fresh.append((r.keyword, r.cluster, slug))
                if len(fresh) >= 4:
                    break
        except Exception as e:
            print('Error checking', slug, e)
            break
    for k, c, s in fresh:
        print(f'  Fresh candidate: "{k}" (cluster: {c}, slug: {s})')
