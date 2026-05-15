import json
import os
import sys
from supabase import create_client
from rankstein.domain import get_registry

def check_unpinned(domain_handle=None):
    # Ensure project root is in sys.path
    project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    if project_root not in sys.path:
        sys.path.insert(0, project_root)

    registry = get_registry()
    domain = registry.get(domain_handle)
    
    url = domain.supabase_url
    key = domain.supabase_service_role_key.get_secret_value()

    sb = create_client(url, key)
    res = sb.table("posts").select("id, title, slug, pinterest_pin_id").eq("status", "published").execute()
    unpinned = [p for p in res.data if not p.get("pinterest_pin_id") or len(str(p["pinterest_pin_id"])) < 15]
    print(json.dumps(unpinned, indent=2))

if __name__ == "__main__":
    handle = sys.argv[1] if len(sys.argv) > 1 else None
    check_unpinned(handle)
