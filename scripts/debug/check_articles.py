import os
import sys
from datetime import datetime, timezone
from dotenv import load_dotenv
from supabase import create_client

load_dotenv()

TODAY_PREFIX = "2026-09-05"

def query_today(name, url, key):
    if not url or not key:
        print(f"[{name}] Missing Supabase credentials")
        return []
    try:
        client = create_client(url, key)
        res = client.table('posts').select('id, title, slug, created_at, pinterest_pin_id').gte('created_at', f'{TODAY_PREFIX}T00:00:00').order('created_at', desc=True).execute()
        print(f"=== {name.upper()} Articles Published Today ({TODAY_PREFIX}): {len(res.data)} ===")
        for r in res.data:
            title = r.get('title')
            slug = r.get('slug')
            pin_id = r.get('pinterest_pin_id') or 'N/A'
            created = r.get('created_at')
            print(f"• {title}")
            print(f"  Slug: {slug} | Pin ID: {pin_id} | Created: {created}")
        return res.data
    except Exception as e:
        print(f"[{name}] Error querying Supabase: {e}")
        return []

def main():
    print(f"Checking for articles published TODAY ({TODAY_PREFIX})...\n")
    url_dolce = os.getenv("SUPABASE_URL")
    key_dolce = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_KEY")
    dolce_posts = query_today("RecetaDolce", url_dolce, key_dolce)
    
    print("\n" + "-"*60 + "\n")
    
    url_genial = os.getenv("RECETAGENIAL_SUPABASE_URL")
    key_genial = os.getenv("RECETAGENIAL_SUPABASE_KEY")
    genial_posts = query_today("RecetaGenial", url_genial, key_genial)

if __name__ == '__main__':
    main()
