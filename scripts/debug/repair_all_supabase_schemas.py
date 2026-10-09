import os
import urllib.request
import json
import re

def extract_recipe_from_markdown(content, title):
    if not content:
        return None
    
    # 1. Extract ingredients
    ing_match = re.search(r'#+\s*Ingredientes.*?\n([\s\S]*?)(?=\n#+ |\Z)', content, re.IGNORECASE)
    ingredients = []
    if ing_match:
        lines = ing_match.group(1).strip().split('\n')
        for l in lines:
            line_str = l.strip()
            if line_str.startswith(('-', '*', '•')) or re.match(r'^\d+\.', line_str):
                clean_item = re.sub(r'^[-*•\d.]\s*', '', line_str).replace('**', '').replace('*', '').strip()
                if len(clean_item) > 2:
                    ingredients.append(clean_item)
                    
    # 2. Extract instructions
    inst_match = re.search(r'#+\s*(?:Instrucciones|Preparaci[óo]n|Elaboraci[óo]n|Paso a paso|C[óo]mo hacer|Elaboraci[óo]n paso a paso).*?\n([\s\S]*?)(?=\n#+ |\Z)', content, re.IGNORECASE)
    instructions = []
    if inst_match:
        lines = inst_match.group(1).strip().split('\n')
        for l in lines:
            line_str = l.strip()
            if len(line_str) > 10 and not line_str.startswith('#'):
                clean_step = re.sub(r'^[-*•\d.]\s*', '', line_str).replace('**', '').replace('*', '').strip()
                if len(clean_step) > 8:
                    instructions.append(clean_step)
                    
    if len(ingredients) >= 2 and len(instructions) >= 2:
        return {
            "name": title,
            "recipeIngredient": ingredients,
            "recipeInstructions": [
                {"@type": "HowToStep", "name": f"Paso {i+1}", "text": step}
                for i, step in enumerate(instructions)
            ],
            "prepTime": "PT15M",
            "cookTime": "PT30M",
            "totalTime": "PT45M",
            "recipeYield": "4 raciones",
            "recipeCuisine": "Española"
        }
    return None

def repair_domain(domain_name, url, key):
    headers = {
        'apikey': key,
        'Authorization': f'Bearer {key}',
        'Content-Type': 'application/json',
        'Prefer': 'return=representation'
    }
    
    # Fetch all posts
    req = urllib.request.Request(f'{url}/rest/v1/posts?select=slug,title,status,recipe_schema,content,category', headers=headers)
    with urllib.request.urlopen(req) as resp:
        posts = json.loads(resp.read().decode('utf-8'))
        
    print(f"\n================ REPAIRING {domain_name} ({len(posts)} total posts) ================")
    
    updated_count = 0
    for p in posts:
        slug = p.get('slug')
        title = p.get('title')
        content = p.get('content') or ''
        category = p.get('category') or 'Recetas'
        rs = p.get('recipe_schema')
        
        needs_repair = False
        if not rs:
            needs_repair = True
        elif isinstance(rs, dict):
            ings = rs.get('recipeIngredient') or rs.get('ingredients') or []
            steps = rs.get('recipeInstructions') or rs.get('instructions') or []
            if len(ings) == 0 or len(steps) == 0:
                needs_repair = True
        elif isinstance(rs, str):
            try:
                parsed = json.loads(rs)
                ings = parsed.get('recipeIngredient') or parsed.get('ingredients') or []
                steps = parsed.get('recipeInstructions') or parsed.get('instructions') or []
                if len(ings) == 0 or len(steps) == 0:
                    needs_repair = True
            except:
                needs_repair = True
                
        if needs_repair:
            extracted = extract_recipe_from_markdown(content, title)
            if extracted:
                extracted['recipeCategory'] = category
                # Update Supabase post
                update_payload = json.dumps({"recipe_schema": extracted}).encode('utf-8')
                update_req = urllib.request.Request(
                    f'{url}/rest/v1/posts?slug=eq.{slug}',
                    data=update_payload,
                    headers=headers,
                    method='PATCH'
                )
                try:
                    with urllib.request.urlopen(update_req) as u_resp:
                        print(f" [+] REPAIRED SCHEMA FOR '{slug}': {len(extracted['recipeIngredient'])} ingredients, {len(extracted['recipeInstructions'])} steps")
                        updated_count += 1
                except Exception as e:
                    print(f" [!] FAILED TO UPDATE '{slug}': {e}")
            else:
                print(f" [-] SKIPPED (Editorial/Guide, no markdown recipe): '{slug}' ('{title}')")

    print(f"Finished {domain_name}: {updated_count} posts updated.")

if __name__ == '__main__':
    repair_domain('recetagenial', 'https://hokcljsrrnjxzgdhjice.supabase.co', 'os.getenv('RECETAGENIAL_SUPABASE_KEY', '')')
    repair_domain('recetadolce', 'https://xjvmnmfczvwkjiasirsl.supabase.co', 'os.getenv('RECETADOLCE_SUPABASE_KEY', '')')
