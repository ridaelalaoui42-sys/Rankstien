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

STAGING_FILE = Path("data/staging/pasabocas_guacamole_chips.json")
IMG_DIR = Path("nanobanana-output")

IMAGES = {
    "featured": "processstep1a_sequence_of_highen.png",
    "pin1": "processstep2a_sequence_of_highen.png",
    "pin2": "processstep3a_sequence_of_highen.png",
    "platter": "processstep4a_sequence_of_highen.png",
}


def upload_file(file_path, storage_path):
    url = f"{SUPABASE_URL}/storage/v1/object/{BUCKET}/{storage_path}"
    headers = {"Authorization": f"Bearer {SUPABASE_KEY}", "x-upsert": "true", "Content-Type": "image/png"}
    with open(file_path, "rb") as f:
        resp = requests.post(url, headers=headers, data=f)

    if resp.status_code in [200, 201]:
        return f"{SUPABASE_URL}/storage/v1/object/public/{BUCKET}/{storage_path}"
    else:
        print(f"❌ Upload failed for {file_path}: {resp.text}")
        return None


def main():
    if not STAGING_FILE.exists():
        print("❌ Staging file not found")
        return

    with open(STAGING_FILE, encoding="utf-8") as f:
        data = json.load(f)

    slug = data["slug"]
    print(f"🚀 Deploying asset: {slug}")

    # 1. Upload Images
    urls = {}
    for key, filename in IMAGES.items():
        local_path = IMG_DIR / filename
        if local_path.exists():
            print(f"📤 Uploading {key}...")
            storage_path = f"posts/{slug}-{key}.png" if "pin" not in key else f"pins/{slug}-{key}.png"
            url = upload_file(local_path, storage_path)
            if url:
                urls[key] = url

    # 2. Update Payload
    if "featured" in urls:
        data["featured_image"] = urls["featured"]

    # Update recipe schema image
    if "recipe_schema" in data:
        data["recipe_schema"]["image"] = [urls.get("featured", "")]

    # Prepare for DB
    db_payload = {
        "title": data["title"],
        "slug": data["slug"],
        "content": data["content_markdown"],
        "meta_title": data.get("title"),
        "meta_description": data["meta_description"],
        "excerpt": data["meta_description"][:200],
        "category": "Pasabocas",
        "featured_image": urls.get("featured"),
        "recipe_schema": json.dumps(data["recipe_schema"], ensure_ascii=False),
        "status": "published",
    }

    # 3. Upsert to DB
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "return=representation",
    }

    print("💾 Saving to Supabase DB...")
    # Check if exists
    check = requests.get(f"{SUPABASE_URL}/rest/v1/posts?slug=eq.{slug}", headers=headers)
    if check.status_code == 200 and check.json():
        resp = requests.patch(
            f"{SUPABASE_URL}/rest/v1/posts?slug=eq.{slug}", headers=headers, json=db_payload
        )
    else:
        resp = requests.post(f"{SUPABASE_URL}/rest/v1/posts", headers=headers, json=db_payload)

    if resp.status_code in [200, 201, 204]:
        print(f"✅ Article live at: https://recetadolce.com/{slug}")
    else:
        print(f"❌ DB Error: {resp.text}")


if __name__ == "__main__":
    main()
