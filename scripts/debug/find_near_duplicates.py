import os
import urllib.request
import json
import re
from collections import defaultdict

def get_posts(url, key):
    print(f"Fetching from {url}...", flush=True)
    req = urllib.request.Request(
        f'{url}/rest/v1/posts?select=id,slug,title,status,featured_image,recipe_schema,pinterest_pin_id,created_at&order=created_at.desc&limit=1000',
        headers={'apikey': key, 'Authorization': f'Bearer {key}'}
    )
    with urllib.request.urlopen(req) as r:
        data = json.loads(r.read().decode('utf-8'))
        print(f"Fetched {len(data)} posts.", flush=True)
        return data

def clean_tokens(text):
    t = re.sub(r'[^a-z0-9\s]', '', text.lower())
    stop = {'de', 'la', 'el', 'en', 'con', 'y', 'a', 'para', 'receta', 'facil', 'faciles', 'casera', 'casero', 'original', 'tradicional', 'paso', 'gourmet', 'deliciosa', 'deliciosas', 'delicioso', 'deliciosos', 'rapida', 'rapidas', 'rapido', 'rapidos', 'perfecta', 'perfecto', 'guia', 'completa', 'complete', 'guide', 'to'}
    tokens = [w for w in t.split() if w not in stop and len(w) > 2]
    return set(tokens)

for db_name, url, key in [
    ('recetagenial', 'https://hokcljsrrnjxzgdhjice.supabase.co', 'os.getenv('RECETAGENIAL_SUPABASE_KEY', '')'),
    ('recetadolce', 'https://xjvmnmfczvwkjiasirsl.supabase.co', 'os.getenv('RECETADOLCE_SUPABASE_KEY', '')')
]:
    posts = get_posts(url, key)
    print(f'=== {db_name.upper()} NEAR-DUPLICATES AUDIT ===')
    seen = set()
    clusters = []
    for i, p1 in enumerate(posts):
        if p1['id'] in seen:
            continue
        tok1 = clean_tokens(p1['title'] + ' ' + p1['slug'])
        if len(tok1) < 2:
            continue
        group = [p1]
        for j, p2 in enumerate(posts):
            if i != j and p2['id'] not in seen:
                tok2 = clean_tokens(p2['title'] + ' ' + p2['slug'])
                inter = tok1.intersection(tok2)
                union = tok1.union(tok2)
                sim = len(inter) / len(union) if union else 0
                if sim >= 0.65 or (len(inter) >= 3 and len(tok1 - inter) <= 1 and len(tok2 - inter) <= 1):
                    group.append(p2)
        if len(group) > 1:
            clusters.append(group)
            for p in group:
                seen.add(p['id'])
                
    for c in clusters:
        print(f"\nCluster ({len(c)} posts):")
        for p in c:
            pid = p.get('pinterest_pin_id') or 'None'
            img = (p.get('featured_image') or '')[:50]
            print(f"  - Slug: {p['slug']} | Title: {p['title']} | Pin: {pid} | Img: {img}")
