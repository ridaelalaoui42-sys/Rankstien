import os
import urllib.request
import json
from collections import defaultdict
import re

def audit_database(domain_name, url, key):
    headers = {
        'apikey': key,
        'Authorization': f'Bearer {key}',
        'Content-Type': 'application/json'
    }
    
    # Fetch all posts (published and draft)
    req = urllib.request.Request(
        f'{url}/rest/v1/posts?select=id,slug,title,status,featured_image,pinterest_pin_id,keywords,recipe_schema,created_at&order=created_at.desc&limit=1000',
        headers=headers
    )
    with urllib.request.urlopen(req) as resp:
        posts = json.loads(resp.read().decode('utf-8'))
        
    print(f"\n=======================================================")
    print(f" AUDIT FOR: {domain_name.upper()} ({len(posts)} total posts)")
    print(f"=======================================================")
    
    # 1. Duplicates check (by normalized title & slug & keywords)
    title_groups = defaultdict(list)
    slug_groups = defaultdict(list)
    keyword_groups = defaultdict(list)
    
    for p in posts:
        # Normalize title
        norm_title = re.sub(r'[^\w\s]', '', (p.get('title') or '').lower()).strip()
        norm_title = re.sub(r'\s+', ' ', norm_title)
        if norm_title:
            title_groups[norm_title].append(p)
            
        slug = (p.get('slug') or '').lower().strip()
        if slug:
            slug_groups[slug].append(p)
            
        kws = p.get('keywords')
        if isinstance(kws, list):
            for k in kws:
                nk = k.lower().strip()
                if len(nk) > 3:
                    keyword_groups[nk].append(p)
        elif isinstance(kws, str) and kws:
            nk = kws.lower().strip()
            if len(nk) > 3:
                keyword_groups[nk].append(p)
                
    duplicate_titles = {k: v for k, v in title_groups.items() if len(v) > 1}
    duplicate_slugs = {k: v for k, v in slug_groups.items() if len(v) > 1}
    
    print(f"\n--- 1. DUPLICATE CONTENT ---")
    print(f"Duplicate title clusters: {len(duplicate_titles)}")
    for title, group in duplicate_titles.items():
        print(f"  * Duplicate Title: '{title}' ({len(group)} posts):")
        for p in group:
            print(f"      - ID: {p['id']} | Slug: {p['slug']} | Status: {p['status']} | PinID: {p.get('pinterest_pin_id')} | Created: {p['created_at']}")
            
    print(f"Duplicate slug clusters: {len(duplicate_slugs)}")
    
    # 2. Image Audit: Pollinations, repeated images, missing images
    image_counts = defaultdict(list)
    pollinations_posts = []
    missing_image_posts = []
    placeholder_image_posts = []
    
    for p in posts:
        img = p.get('featured_image') or ''
        if not img or img.strip() == '':
            missing_image_posts.append(p)
            continue
            
        if 'logo.png' in img or 'placeholder' in img or 'hero_spanish_feast_premium' in img:
            placeholder_image_posts.append(p)
            
        if 'pollinations' in img.lower():
            pollinations_posts.append(p)
            
        image_counts[img].append(p)
        
    repeated_images = {img: group for img, group in image_counts.items() if len(group) > 1}
    
    print(f"\n--- 2. IMAGE AUDIT ---")
    print(f"Pollinations images: {len(pollinations_posts)} posts")
    for p in pollinations_posts:
        print(f"  * [POLLINATIONS] Slug: {p['slug']} | Img: {p['featured_image']}")
        
    print(f"\nMissing images: {len(missing_image_posts)} posts")
    for p in missing_image_posts:
        print(f"  * [MISSING_IMAGE] Slug: {p['slug']} | Status: {p['status']}")
        
    print(f"\nPlaceholder images: {len(placeholder_image_posts)} posts")
    for p in placeholder_image_posts:
        print(f"  * [PLACEHOLDER] Slug: {p['slug']} | Img: {p['featured_image']}")
        
    print(f"\nRepeated images across different articles: {len(repeated_images)} images used across multiple articles")
    for img, group in list(repeated_images.items())[:10]:
        print(f"  * Image used {len(group)} times: {img}")
        for p in group[:3]:
            print(f"      - {p['slug']}")
            
    # 3. Schema Completeness
    missing_schema = []
    empty_ingredients = []
    empty_instructions = []
    
    for p in posts:
        rs = p.get('recipe_schema')
        if not rs:
            missing_schema.append(p)
            continue
        if isinstance(rs, str):
            try:
                rs = json.loads(rs)
            except:
                missing_schema.append(p)
                continue
        ings = rs.get('recipeIngredient') or rs.get('ingredients') or []
        inst = rs.get('recipeInstructions') or rs.get('instructions') or []
        if len(ings) == 0:
            empty_ingredients.append(p)
        if len(inst) == 0:
            empty_instructions.append(p)
            
    print(f"\n--- 3. SCHEMA AUDIT ---")
    print(f"Missing schema: {len(missing_schema)} posts")
    print(f"Empty ingredients: {len(empty_ingredients)} posts")
    print(f"Empty instructions: {len(empty_instructions)} posts")

if __name__ == '__main__':
    audit_database('recetagenial', 'https://hokcljsrrnjxzgdhjice.supabase.co', 'os.getenv('RECETAGENIAL_SUPABASE_KEY', '')')
    audit_database('recetadolce', 'https://xjvmnmfczvwkjiasirsl.supabase.co', 'os.getenv('RECETADOLCE_SUPABASE_KEY', '')')
