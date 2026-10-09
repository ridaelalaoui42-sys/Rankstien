import os
import zipfile
import csv
import io
import re
from urllib.parse import urlparse, unquote
from dotenv import load_dotenv
from supabase import create_client

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
    res = rg_sb.table('posts').select('id, slug, title, status, is_published, category').range(page*1000, (page+1)*1000-1).execute()
    data = res.data or []
    all_posts.extend(data)
    if len(data) < 1000:
        break
    page += 1

print(f"Total posts in DB: {len(all_posts)}")
db_posts_by_slug = {p['slug']: p for p in all_posts if p.get('slug')}

def words(s):
    return set(re.findall(r'[a-z0-9]+', s.lower())) - {'de', 'la', 'el', 'los', 'las', 'un', 'una', 'y', 'en', 'con', 'a', 'para', 'receta', 'facil', 'tradicional', 'paso', 'como', 'hacer'}

matches = []
for u in raw_urls:
    slug = unquote(urlparse(u).path.strip('/')).lower()
    
    # Check exact
    if slug in db_posts_by_slug:
        p = db_posts_by_slug[slug]
        matches.append({
            'url': u, 'slug': slug, 'type': 'EXACT_DB',
            'target': f"/{p['slug']}", 'target_title': p['title'], 'status': p['status']
        })
        continue
    
    # Check category
    if slug in ['aperitivos', 'arroces', 'carnes', 'pescados', 'ensaladas', 'postres']:
        matches.append({
            'url': u, 'slug': slug, 'type': 'CATEGORY_REDIRECT',
            'target': f"/categoria/{slug}", 'target_title': slug.capitalize(), 'status': 'valid'
        })
        continue
    
    if slug == 'pollo-al-ajillo-facil':
        matches.append({
            'url': u, 'slug': slug, 'type': 'STATIC_RECETA_REDIRECT',
            'target': '/recetas/pollo-al-ajillo-facil', 'target_title': 'Pollo al ajillo', 'status': 'valid'
        })
        continue
        
    if slug in ['$', '&'] or 'test' in slug or 'pipeline' in slug:
        matches.append({
            'url': u, 'slug': slug, 'type': 'GARBAGE_404',
            'target': None, 'target_title': None, 'status': '404'
        })
        continue
        
    if 'verrugas' in slug:
        matches.append({
            'url': u, 'slug': slug, 'type': 'OFF_NICHE_404',
            'target': None, 'target_title': None, 'status': '404'
        })
        continue

    # Keyword / Word overlap match with DB
    slug_words = words(slug)
    best_post = None
    best_score = 0
    for p in all_posts:
        if p.get('status') != 'published':
            continue
        p_words = words(p['slug']) | words(p.get('title') or '')
        overlap = len(slug_words & p_words)
        if overlap > best_score:
            best_score = overlap
            best_post = p
            
    # Require substantial overlap (at least 2 key culinary nouns/adjectives)
    if best_score >= 2 and best_post:
        matches.append({
            'url': u, 'slug': slug, 'type': 'SIMILAR_RECIPE_REDIRECT',
            'target': f"/{best_post['slug']}", 'target_title': best_post['title'], 'status': f"score_{best_score}"
        })
    else:
        matches.append({
            'url': u, 'slug': slug, 'type': 'ORPHAN_404',
            'target': None, 'target_title': None, 'status': '404'
        })

print(f"\n--- MATCH BREAKDOWN (Total: {len(matches)}) ---")
type_counts = {}
for m in matches:
    type_counts[m['type']] = type_counts.get(m['type'], 0) + 1

for t, c in type_counts.items():
    print(f"  {t}: {c}")

print("\n--- SAMPLE SIMILAR RECIPE REDIRECTS (first 20) ---")
for m in [m for m in matches if m['type'] == 'SIMILAR_RECIPE_REDIRECT'][:20]:
    print(f"  GSC: /{m['slug']} -> 301 Redirect -> {m['target']} ('{m['target_title']}')")

print("\n--- GARBAGE & OFF-NICHE (Will return clean 404/410) ---")
for m in [m for m in matches if m['type'] in ('GARBAGE_404', 'OFF_NICHE_404')]:
    print(f"  /{m['slug']} -> HTTP 404")
