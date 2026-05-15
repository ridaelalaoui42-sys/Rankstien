import asyncio
import json
import os
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv()

# ---------- CONFIG ----------
SUPABASE_URL = os.environ.get("NEXT_PUBLIC_SUPABASE_URL", "https://xjvmnmfczvwkjiasirsl.supabase.co")
SUPABASE_KEY = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
BUCKET = "recipe-images"

STAGING_FILE = Path("data/staging/guacamole_v2.json")
# Fix paths from generate_story output
STEPS_PIN_LOCAL = Path("nanobanana-output/processstep1frame_1_steps_pin_23.png")
VIRAL_PIN_LOCAL = Path("nanobanana-output/processstep2frame_1_steps_pin_23.png")


def upload_file(file_path, storage_path):
    url = f"{SUPABASE_URL}/storage/v1/object/{BUCKET}/{storage_path}"
    headers = {"Authorization": f"Bearer {SUPABASE_KEY}", "x-upsert": "true", "Content-Type": "image/png"}
    with open(file_path, "rb") as f:
        resp = requests.post(url, headers=headers, data=f)

    if resp.status_code in [200, 201]:
        return f"{SUPABASE_URL}/storage/v1/object/public/{BUCKET}/{storage_path}"
    return None


async def main():
    if not STAGING_FILE.exists():
        print("❌ Staging file not found")
        return

    with open(STAGING_FILE, encoding="utf-8") as f:
        data = json.load(f)

    slug = data["slug"]
    print(f"🚀 Deploying V2: {slug}")

    # 1. Upload Composite Pins
    steps_url = upload_file(STEPS_PIN_LOCAL, f"pins/{slug}-steps.png")
    viral_url = upload_file(VIRAL_PIN_LOCAL, f"pins/{slug}-viral.png")

    print(f"📤 Steps Pin: {steps_url}")
    print(f"📤 Viral Pin: {viral_url}")

    # 2. Mock Pin Publishing to get IDs (Actual uploader would return these)
    # For now, we will store the URLs and placeholders.
    # In a real run, PinMaster would return numeric IDs like '123456789'
    steps_id = "12345_STEPS"  # Placeholder
    viral_id = "67890_VIRAL"  # Placeholder

    # 3. Inject Iframe Logic into Content
    # We replace placeholders with interactive HTML/Iframe blocks
    content = data["content_markdown"]

    hero_html = f'<img src="{viral_url}" alt="{data["title"]}" class="w-full rounded-xl shadow-lg mb-8">'
    steps_iframe = f'<div class="pin-container my-8"><blockquote class="pinterest-pin" data-pin-id="{steps_id}" data-pin-build="doBuild"></blockquote></div>'
    final_iframe = f'<div class="pin-container my-8 text-center"><p class="font-bold mb-2">¡Guarda esta receta!</p><blockquote class="pinterest-pin" data-pin-id="{viral_id}"></blockquote></div>'

    content = content.replace("[HERO_IMAGE]", hero_html)
    content = content.replace("[PINTEREST_IFRAME_STEPS]", steps_iframe)
    content = content.replace("[PINTEREST_IFRAME_FINAL]", final_iframe)

    # 4. Push to Supabase
    db_payload = {
        "title": data["title"],
        "slug": data["slug"],
        "content": content,
        "meta_title": data.get("title"),
        "meta_description": data["meta_description"],
        "category": "Pasabocas",
        "featured_image": viral_url,
        "recipe_schema": json.dumps(data["recipe_schema"], ensure_ascii=False),
        "pinterest_pin_id": viral_id,  # Store the primary viral pin ID
        "status": "published",
    }

    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "return=representation",
    }

    print("💾 Saving to Supabase DB (V2)...")
    check = requests.get(f"{SUPABASE_URL}/rest/v1/posts?slug=eq.{slug}", headers=headers)
    if check.status_code == 200 and check.json():
        resp = requests.patch(
            f"{SUPABASE_URL}/rest/v1/posts?slug=eq.{slug}", headers=headers, json=db_payload
        )
    else:
        resp = requests.post(f"{SUPABASE_URL}/rest/v1/posts", headers=headers, json=db_payload)

    if resp.status_code in [200, 201, 204]:
        print(f"✅ V2 Article live: https://recetadolce.com/{slug}")
        print(
            "🔗 Note: Pin IDs are placeholders for this demo. Interactive iframes will activate once real Pins are published."
        )
    else:
        print(f"❌ DB Error: {resp.text}")


if __name__ == "__main__":
    asyncio.run(main())
