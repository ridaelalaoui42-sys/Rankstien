import os, sys
sys.path.insert(0, ".")
from dotenv import load_dotenv
load_dotenv()
from supabase import create_client

client = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_KEY"))
res = client.table("posts").select("id, title, slug, created_at, pinterest_pin_id").order("created_at", desc=True).limit(30).execute()
data = res.data or []

print("==================================================")
print(f"VERIFIED TOTAL RECENT POSTS: {len(data)}")
print("==================================================")
for i, item in enumerate(data, 1):
    pin = item.get("pinterest_pin_id") or "Enqueued in Remaster Campaign"
    print(f"{i:02d}. [{item.get('created_at')[:10]}] {item['title']} ({item['slug']}) | Pin: {pin}")
