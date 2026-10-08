import os, json
from dotenv import load_dotenv
from supabase import create_client

load_dotenv()
sb = create_client(os.environ['SUPABASE_URL'], os.environ.get('SUPABASE_SERVICE_ROLE_KEY') or os.environ.get('SUPABASE_KEY'))
res = sb.table('posts').select('id, title, slug, pinterest_pin_id, created_at, is_published').order('created_at', desc=True).limit(50).execute()

output = []
for r in res.data:
    title = r.get('title')
    slug = r.get('slug')
    pin_id = r.get('pinterest_pin_id') or 'N/A'
    created_at = r.get('created_at')
    
    # RecetaDolce is the default target domain for these posts
    article_url = f"https://recetadolce.com/recetas/{slug}" if slug else "N/A"
    pin_url = f"https://www.pinterest.com/pin/{pin_id}/" if pin_id and pin_id != 'N/A' else "N/A"
    
    output.append({
        "title": title,
        "article_url": article_url,
        "pin_url": pin_url,
        "pin_id": pin_id,
        "created_at": created_at
    })

with open('data/reports/final_urls_report.json', 'w', encoding='utf-8') as f:
    json.dump(output, f, indent=2, default=str)

print("SUCCESS: Wrote", len(output), "urls to data/reports/final_urls_report.json")
