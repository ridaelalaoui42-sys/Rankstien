import asyncio
import json
import random
import sys
from pathlib import Path

import requests

from rankstein.domain import get_registry

# ---------- CONFIG ----------
BUCKET = "recipe-images"


def upload_file(file_path, storage_path, domain):
    url = f"{domain.supabase_url}/storage/v1/object/{BUCKET}/{storage_path}"
    key = domain.supabase_service_role_key.get_secret_value()
    headers = {"Authorization": f"Bearer {key}", "x-upsert": "true", "Content-Type": "image/png"}
    with open(file_path, "rb") as f:
        resp = requests.post(url, headers=headers, data=f)

    if resp.status_code in [200, 201]:
        return f"{domain.supabase_url}/storage/v1/object/public/{BUCKET}/{storage_path}"
    return None


async def deploy(json_file_path, steps_img_path, viral_img_path, domain_handle=None):
    registry = get_registry()
    try:
        domain = registry.get(domain_handle)
    except KeyError as e:
        print(f"❌ {e}")
        return

    staging_file = Path(json_file_path)
    if not staging_file.exists():
        print(f"❌ Staging file not found: {json_file_path}")
        return

    with open(staging_file, encoding="utf-8") as f:
        data = json.load(f)

    slug = data["slug"]
    print(f"🚀 Deploying Generic Asset for {domain.handle}: {slug}")

    # 1. Upload Composite Pins
    steps_url = upload_file(steps_img_path, f"pins/{slug}-steps.png", domain)
    viral_url = upload_file(viral_img_path, f"pins/{slug}-viral.png", domain)

    if not steps_url or not viral_url:
        print("❌ Failed to upload images to Supabase storage.")
        return

    print(f"📤 Steps Pin: {steps_url}")
    print(f"📤 Viral Pin: {viral_url}")

    # 2. Mock Pin IDs
    steps_id = f"STEPS_ID_{random.randint(10000, 99999)}"
    viral_id = f"VIRAL_ID_{random.randint(10000, 99999)}"

    # 3. Inject Iframe Logic
    content = data["content_markdown"]
    hero_html = f'<img src="{viral_url}" alt="{data["title"]}" class="w-full rounded-xl shadow-lg mb-8">'
    steps_iframe = f'<div class="pin-container my-8"><blockquote class="pinterest-pin" data-pin-id="{steps_id}" data-pin-build="doBuild"></blockquote></div>'
    final_iframe = f'<div class="pin-container my-8 text-center"><p class="font-bold mb-2">¡Guarda esta receta!</p><blockquote class="pinterest-pin" data-pin-id="{viral_id}"></blockquote></div>'

    content = content.replace("[HERO_IMAGE]", hero_html)
    content = content.replace("[PINTEREST_IFRAME_STEPS]", steps_iframe)
    content = content.replace("[PINTEREST_IFRAME_FINAL]", final_iframe)

    # 4. Push to DB
    db_payload = {
        "title": data["title"],
        "slug": data["slug"],
        "content": content,
        "meta_title": data.get("title"),
        "meta_description": data["meta_description"],
        "category": "Aperitivos",
        "featured_image": viral_url,
        "recipe_schema": json.dumps(data["recipe_schema"], ensure_ascii=False),
        "pinterest_pin_id": viral_id,
        "status": "published",
    }

    key = domain.supabase_service_role_key.get_secret_value()
    headers = {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Prefer": "return=representation",
    }

    print("💾 Saving to Supabase DB...")
    check = requests.get(f"{domain.supabase_url}/rest/v1/posts?slug=eq.{slug}", headers=headers)
    if check.status_code == 200 and check.json():
        resp = requests.patch(
            f"{domain.supabase_url}/rest/v1/posts?slug=eq.{slug}", headers=headers, json=db_payload
        )
    else:
        resp = requests.post(f"{domain.supabase_url}/rest/v1/posts", headers=headers, json=db_payload)

    if resp.status_code in [200, 201, 204]:
        base_url = f"https://{domain.domain}" if not domain.domain.startswith("http") else domain.domain
        print(f"✅ Article live: {base_url}/{slug}")
    else:
        print(f"❌ DB Error: {resp.text}")


if __name__ == "__main__":
    if len(sys.argv) < 4:
        print("Usage: python deploy_generic.py <json_file> <steps_img> <viral_img> [domain_handle]")
        sys.exit(1)

    domain_handle = sys.argv[4] if len(sys.argv) > 4 else None
    asyncio.run(deploy(sys.argv[1], sys.argv[2], sys.argv[3], domain_handle))
