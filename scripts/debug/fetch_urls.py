import os, json
from dotenv import load_dotenv
from supabase import create_client

load_dotenv()

supabase_url = os.environ.get('SUPABASE_URL')
supabase_key = os.environ.get('SUPABASE_SERVICE_ROLE_KEY') or os.environ.get('SUPABASE_SERVICE_KEY') or os.environ.get('SUPABASE_KEY')

if supabase_url and supabase_key:
    sb = create_client(supabase_url, supabase_key)
    res = sb.table('posts').select('*').order('created_at', desc=True).limit(30).execute()
    
    output_lines = []
    for item in res.data:
        domain = item.get('domain_handle') or item.get('domain') or 'recetadolce'
        base_domain = 'https://recetadolce.com' if 'dolce' in str(domain).lower() else 'https://recetagenial.com'
        slug = item.get('slug') or item.get('url_slug') or ''
        title = item.get('title') or item.get('name') or 'Untitled'
        pin_url = item.get('pinterest_pin_url') or item.get('primary_pin_url') or item.get('pin_url') or 'N/A'
        pin_id = item.get('pinterest_pin_id') or item.get('pin_id') or 'N/A'
        created = item.get('created_at') or ''
        
        article_url = f"{base_domain}/recetas/{slug}" if slug else base_domain
        output_lines.append({
            "title": title,
            "domain": domain,
            "article_url": article_url,
            "pin_url": pin_url,
            "pin_id": pin_id,
            "created_at": created
        })
    
    with open('data/reports/published_urls.json', 'w', encoding='utf-8') as f:
        json.dump(output_lines, f, indent=2, default=str)
    print("SUCCESS:", len(output_lines), "articles fetched")
else:
    print("ERROR: Supabase credentials missing")
