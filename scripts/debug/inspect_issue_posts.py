import os
import urllib.request
import json

def inspect_posts(domain_name, url, key, slugs):
    headers = {'apikey': key, 'Authorization': f'Bearer {key}'}
    for slug in slugs:
        req = urllib.request.Request(f'{url}/rest/v1/posts?select=slug,title,status,recipe_schema,content&slug=eq.{slug}', headers=headers)
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            if data:
                p = data[0]
                print(f"\n================ {domain_name}: {slug} ================")
                print(f"Title: {p.get('title')}")
                print(f"recipe_schema: {p.get('recipe_schema')}")
                content = p.get('content') or ''
                print(f"Content length: {len(content)}")
                # Show first 500 chars and lines with headers
                headers_found = [line for line in content.split('\n') if line.strip().startswith('#')]
                print("Markdown headers found:", headers_found[:8])

# RecetaGenial issue slugs
genial_slugs = [
    'ensalada-de-garbanzos-con-queso-feta',
    'aperitivos-salados-faciles-deliciosos',
    'gambas-al-ajillo-clasicas',
    'aperitivos-deliciosos-y-faciles-para-tus-cenas-con-amigos',
    'aperitivos-salados-faciles-originales',
    'tarta-de-queso-vasca-codex-test',
    'ensalada-cesar-tradicional-receta-autentica',
    'tapas-espanolas-para-reuniones-con-amigos'
]

inspect_posts('recetagenial', 'https://hokcljsrrnjxzgdhjice.supabase.co', 'os.getenv('RECETAGENIAL_SUPABASE_KEY', '')', genial_slugs)

# RecetaDolce issue slugs
dolce_slugs = [
    'aperitivos-frios-faciles',
    'pasteles-de-cumplea-os-bonitos',
    'comida-sencilla-recetas-rapidas',
    'bizcocho-chocolate-blanco-receta-artesanal',
    'pasteles-de-cumplea-os'
]

inspect_posts('recetadolce', 'https://xjvmnmfczvwkjiasirsl.supabase.co', 'os.getenv('RECETADOLCE_SUPABASE_KEY', '')', dolce_slugs)
