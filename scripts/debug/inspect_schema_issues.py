import os
import urllib.request
import json

def inspect_post(url, key, pid):
    req = urllib.request.Request(
        f'{url}/rest/v1/posts?id=eq.{pid}&select=id,slug,title,status,content,recipe_schema',
        headers={'apikey': key, 'Authorization': f'Bearer {key}'}
    )
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read().decode('utf-8'))

rg_url = 'https://hokcljsrrnjxzgdhjice.supabase.co'
rg_key = 'os.getenv('RECETAGENIAL_SUPABASE_KEY', '')'
rd_url = 'https://xjvmnmfczvwkjiasirsl.supabase.co'
rd_key = 'os.getenv('RECETADOLCE_SUPABASE_KEY', '')'

pids_rg = [
    '1c8ac684-51aa-4a87-bb04-cb400c1a09d8',
    '075897c0-bc8b-4db6-93c3-4b2d515acea4',
    'bd182762-a8cb-42c2-bf53-e91b6e10db7c',
    'b93382e6-3eec-4bcb-a926-e098108085e4',
    '27dcffa1-3872-406b-aad5-cc4234f8623c',
    '25ce3927-3f8b-4ea2-b360-a6382447f432',
    '43c02437-50b2-4310-8d24-8cc2dc359e28'
]

print("=== INSPECTING RECETAGENIAL SCHEMA ISSUES ===")
for pid in pids_rg:
    res = inspect_post(rg_url, rg_key, pid)
    if res:
        p = res[0]
        content_preview = (p.get('content') or '')[:300].replace('\n', ' ')
        print(f"ID: {p['id']} | Slug: {p['slug']} | Title: {p['title']} | Status: {p['status']} | Content len: {len(p.get('content') or '')}")
        print(f"   Schema: {p.get('recipe_schema')}")
        print(f"   Preview: {content_preview}\n")

pids_rd = [
    '8c27e664-777b-42c9-b332-32582c481a00',
    '328c0ee1-1106-4abe-ace4-ff7f8423e1c5',
    '4af1f398-0c22-447d-9ddc-7d58bd94d4c9',
    'f60d6438-7118-4fb3-add9-f5530ebedfe3'
]

print("=== INSPECTING RECETADOLCE SCHEMA ISSUES ===")
for pid in pids_rd:
    res = inspect_post(rd_url, rd_key, pid)
    if res:
        p = res[0]
        content_preview = (p.get('content') or '')[:300].replace('\n', ' ')
        print(f"ID: {p['id']} | Slug: {p['slug']} | Title: {p['title']} | Status: {p['status']} | Content len: {len(p.get('content') or '')}")
        print(f"   Schema: {p.get('recipe_schema')}")
        print(f"   Preview: {content_preview}\n")
