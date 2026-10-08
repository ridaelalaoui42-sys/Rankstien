import json
from backend.services.supabase_client import get_supabase_client

for domain in ['recetadolce', 'recetagenial']:
    print(f"\n=================== {domain.upper()} RECENT ARTICLES & PINS ===================")
    try:
        client = get_supabase_client(domain)
        res = client.table('articles').select('title, slug, pinterest_pin_id, created_at').order('created_at', desc=True).limit(5).execute()
        for r in res.data:
            pin_id = r.get('pinterest_pin_id') or 'N/A'
            pin_url = f"https://www.pinterest.com/pin/{pin_id}/" if pin_id != 'N/A' else 'No Pin ID'
            print(f"Title: {r['title']}")
            print(f"Slug:  {r['slug']}")
            print(f"Pin:   {pin_url}")
            print(f"Date:  {r['created_at']}")
            print("-" * 50)
    except Exception as e:
        print(f"Error fetching for {domain}: {e}")
