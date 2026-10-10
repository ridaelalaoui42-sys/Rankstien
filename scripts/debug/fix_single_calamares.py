"""Replace Dolce bucket URL across all fields of calamares post on Genial."""

import os
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import json
import requests
from dotenv import load_dotenv
from rankstein.domain import get_registry

load_dotenv()
genial_dom = get_registry().get("recetagenial")
key = genial_dom.supabase_service_role_key.get_secret_value()
base = genial_dom.supabase_url.rstrip("/")

headers = {
    "apikey": key,
    "Authorization": f"Bearer {key}",
    "Content-Type": "application/json",
}

resp = requests.get(f"{base}/rest/v1/posts?slug=eq.calamares-a-la-romana-crujientes", headers=headers)
posts = resp.json()
if posts:
    p = posts[0]
    old_url = "https://xjvmnmfczvwkjiasirsl.supabase.co/storage/v1/object/public/recipe-images/recipes/calamares-a-la-romana-crujientes.jpg"
    new_url = f"{base}/storage/v1/object/public/recipe-images/calamares-a-la-romana-crujientes.jpg"
    
    content = (p.get("content") or "").replace(old_url, new_url)
    schema = p.get("recipe_schema") or {}
    if isinstance(schema, str):
        try: schema = json.loads(schema)
        except: schema = {}
    if isinstance(schema, dict):
        if schema.get("image") == old_url:
            schema["image"] = new_url
            
    patch_payload = {
        "featured_image": new_url,
        "hero_image": new_url,
        "content": content,
        "recipe_schema": schema,
    }
    patch_resp = requests.patch(f"{base}/rest/v1/posts?id=eq.{p['id']}", headers=headers, json=patch_payload)
    print("Patched calamares post fields:", patch_resp.status_code)
