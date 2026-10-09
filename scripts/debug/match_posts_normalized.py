import os
import zipfile
import csv
import io
from urllib.parse import urlparse, unquote
from dotenv import load_dotenv
from supabase import create_client
import re

load_dotenv('.env')

z = zipfile.ZipFile(r'c:\Users\REDX420\Downloads\recetagenial.com-Coverage-Drilldown-2026-10-09.zip')
content = z.read('Table.csv').decode('utf-8', errors='ignore')
reader = csv.reader(io.StringIO(content))
next(reader)
raw_urls = [r[0].strip() for r in reader if r]

rg_url = os.environ.get('RECETAGENIAL_SUPABASE_URL')
rg_key = os.environ.get('RECETAGENIAL_SUPABASE_KEY')
rg_sb = create_client(rg_url, rg_key)

all_posts = []
page = 0
while True:
    res = rg_sb.table('posts').select('id, slug, title, status, is_published').range(page*1000, (page+1)*1000-1).execute()
    data = res.data or []
    all_posts.extend(data)
    if len(data) < 1000:
        break
    page += 1

print(f"Fetched {len(all_posts)} posts from Supabase.")

def norm(t):
    if not t:
        return ''
    t = t.lower()
    t = re.sub(r'[^a-z0-9]', '', t)
    return t

gsc_slugs = [unquote(urlparse(u).path.strip('/')).lower() for u in raw_urls]

found_posts = []
for p in all_posts:
    p_norm_slug = norm(p.get('slug'))
    p_norm_title = norm(p.get('title'))
    matched_gsc = []
    for u, s in zip(raw_urls, gsc_slugs):
        s_norm = norm(s)
        if not s_norm:
            continue
        if s_norm == p_norm_slug or s_norm == p_norm_title:
            matched_gsc.append(u)
    if matched_gsc:
        found_posts.append((p, matched_gsc))

print(f"Posts with matching slug or title: {len(found_posts)}")
for p, u_list in found_posts:
    print(f"Post ID: {p['id']} | Slug: {p['slug']} | Title: {p['title']} | Status: {p['status']} | Matched GSC: {u_list}")
