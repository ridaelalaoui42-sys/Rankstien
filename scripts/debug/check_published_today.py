import sys, os, sqlite3
sys.path.insert(0, ".")
from dotenv import load_dotenv
load_dotenv()
from supabase import create_client

def check_supabase():
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_KEY")
    if not url or not key:
        print("Missing SUPABASE credentials")
        return []

    client = create_client(url, key)
    res = client.table('posts').select('id, title, slug, created_at, pinterest_pin_id').order('created_at', desc=True).limit(25).execute()
    return res.data or []

def check_sqlite():
    db_path = "data/pipeline_events.db"
    if not os.path.exists(db_path):
        return []
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT id, domain_handle, keyword, slug, status, created_at FROM pipeline_runs ORDER BY created_at DESC LIMIT 25"
        ).fetchall()
        return [dict(r) for r in rows]

if __name__ == "__main__":
    sb_posts = check_supabase()
    db_runs = check_sqlite()
    
    print(f"=== LATEST SUPABASE POSTS: TOTAL {len(sb_posts)} ===")
    for p in sb_posts:
        print(f"  - [{p.get('created_at')}] {p.get('title')} ({p.get('slug')}) | Pin: {p.get('pinterest_pin_id')}")

    print(f"\n=== LATEST PIPELINE RUNS: TOTAL {len(db_runs)} ===")
    by_dom = {}
    for r in db_runs:
        by_dom.setdefault(r.get('domain_handle', 'unknown'), []).append(r)
    for dom, items in by_dom.items():
        print(f"\nDomain: {dom} ({len(items)} runs)")
        for i in items:
            print(f"  - [{i.get('created_at')}] [{i.get('status')}] {i.get('keyword')} (slug: {i.get('slug')})")
