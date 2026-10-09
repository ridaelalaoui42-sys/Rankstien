import os
import urllib.request
import json

def audit(domain_name, url, key):
    headers = {'apikey': key, 'Authorization': f'Bearer {key}'}
    req = urllib.request.Request(f'{url}/rest/v1/posts?select=slug,title,status,recipe_schema,category,featured_image&limit=500', headers=headers)
    with urllib.request.urlopen(req) as resp:
        posts = json.loads(resp.read().decode('utf-8'))
    
    print(f"\n================ {domain_name} ({len(posts)} total posts) ================")
    issues = []
    for p in posts:
        slug = p.get('slug')
        title = p.get('title')
        status = p.get('status')
        rs = p.get('recipe_schema')
        
        if not rs:
            issues.append((slug, title, "NO_SCHEMA"))
            continue
        
        if isinstance(rs, str):
            try:
                rs = json.loads(rs)
            except:
                issues.append((slug, title, "INVALID_JSON_SCHEMA"))
                continue
                
        ingredients = rs.get('recipeIngredient') or rs.get('ingredients') or []
        instructions = rs.get('recipeInstructions') or rs.get('instructions') or []
        
        if not ingredients or len(ingredients) == 0:
            issues.append((slug, title, f"EMPTY_INGREDIENTS (status={status})"))
        if not instructions or len(instructions) == 0:
            issues.append((slug, title, f"EMPTY_INSTRUCTIONS (status={status})"))
            
    print(f"Total issue posts: {len(issues)}")
    for iss in issues:
        print(f" - {iss[0]}: {iss[2]} ('{iss[1]}')")

audit('recetagenial', 'https://hokcljsrrnjxzgdhjice.supabase.co', 'os.getenv('RECETAGENIAL_SUPABASE_KEY', '')')
audit('recetadolce', 'https://xjvmnmfczvwkjiasirsl.supabase.co', 'os.getenv('RECETADOLCE_SUPABASE_KEY', '')')
