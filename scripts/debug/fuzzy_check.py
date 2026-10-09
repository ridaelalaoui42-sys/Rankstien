import os
import zipfile
import csv
import io
from urllib.parse import urlparse, unquote
from dotenv import load_dotenv
from supabase import create_client

load_dotenv('.env')

z = zipfile.ZipFile(r'c:\Users\REDX420\Downloads\recetagenial.com-Coverage-Drilldown-2026-10-09.zip')
content = z.read('Table.csv').decode('utf-8', errors='ignore')
reader = csv.reader(io.StringIO(content))
next(reader)
raw_slugs = [unquote(urlparse(r[0].strip()).path.strip('/')).lower() for r in reader if r]

rg_url = os.environ.get('RECETAGENIAL_SUPABASE_URL')
rg_key = os.environ.get('RECETAGENIAL_SUPABASE_KEY')
rg_sb = create_client(rg_url, rg_key)

all_posts = []
page = 0
while True:
    res = rg_sb.table('posts').select('id, slug, title, status, is_published, content').range(page*1000, (page+1)*1000-1).execute()
    data = res.data or []
    all_posts.extend(data)
    if len(data) < 1000:
        break
    page += 1

print(f"Total DB posts: {len(all_posts)}")
db_by_slug = {p['slug'].lower(): p for p in all_posts if p.get('slug')}

exact_matches = []
partial_matches = []
unmatched = []

for s in raw_slugs:
    if s in db_by_slug:
        exact_matches.append((s, db_by_slug[s]))
    else:
        found = False
        for db_s, p in db_by_slug.items():
            if s and len(s) > 5 and (s in db_s or db_s in s):
                partial_matches.append((s, db_s, p))
                found = True
                break
        if not found:
            unmatched.append(s)

print(f"Exact matches: {len(exact_matches)}")
print(f"Partial matches: {len(partial_matches)}")
print(f"Completely unmatched: {len(unmatched)}")

print("\n--- Exact matches ---")
for s, p in exact_matches:
    print(f"Exact: {s} -> ID: {p['id']} | Status: {p['status']} | is_published: {p['is_published']} | ContentLen: {len(p.get('content') or '')}")

print("\n--- Partial matches ---")
for s, db_s, p in partial_matches:
    print(f"GSC: {s} <-> DB: {db_s} | Status: {p['status']} | is_published: {p['is_published']}")

print("\n--- Sample Unmatched ---")
for s in unmatched[:20]:
    print(f"Unmatched: {s}")
