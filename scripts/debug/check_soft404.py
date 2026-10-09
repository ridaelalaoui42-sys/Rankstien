import os
import zipfile
import csv
import io
from urllib.parse import urlparse
from dotenv import load_dotenv

load_dotenv('.env')
url = os.environ.get('RECETAGENIAL_SUPABASE_URL')
key = os.environ.get('RECETAGENIAL_SUPABASE_KEY')

from supabase import create_client
sb = create_client(url, key)

z = zipfile.ZipFile(r'c:\Users\REDX420\Downloads\recetagenial.com-Coverage-Drilldown-2026-10-09.zip')
content = z.read('Table.csv').decode('utf-8', errors='ignore')
reader = csv.reader(io.StringIO(content))
next(reader)  # skip header
urls = [r[0].strip() for r in reader if r]

slugs = []
for u in urls:
    path = urlparse(u).path.strip('/')
    slugs.append((u, path))

print(f"Total URLs in GSC report: {len(slugs)}")

# Query Supabase for all posts (paginated or in chunks if needed)
all_posts = []
page = 0
page_size = 1000
while True:
    res = sb.table('posts').select('id, slug, title, status, is_published, content').range(page * page_size, (page + 1) * page_size - 1).execute()
    data = res.data or []
    all_posts.extend(data)
    if len(data) < page_size:
        break
    page += 1

print(f"Total posts in Supabase: {len(all_posts)}")
db_slug_map = {p['slug']: p for p in all_posts if p.get('slug')}

matched_in_db = []
not_in_db = []

for u, slug in slugs:
    if slug in db_slug_map:
        matched_in_db.append((u, slug, db_slug_map[slug]))
    else:
        not_in_db.append((u, slug))

print(f"Matched in Supabase DB: {len(matched_in_db)}")
print(f"NOT found in Supabase DB: {len(not_in_db)}")

print("\n--- SAMPLE MATCHED IN DB (first 25) ---")
for u, slug, post in matched_in_db[:25]:
    content_len = len(post.get('content') or '')
    print(f"ID: {post['id']} | Slug: {slug} | Status: {post['status']} | is_published: {post['is_published']} | ContentLen: {content_len} | Title: {post['title'][:40]}")

print("\n--- NOT FOUND IN DB ---")
for u, slug in not_in_db:
    print(f"URL: {u} | Slug: {slug}")
