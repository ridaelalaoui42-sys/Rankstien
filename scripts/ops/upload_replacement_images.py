import urllib.request
import json
import os

SUPABASE_URL = "https://hokcljsrrnjxzgdhjice.supabase.co"
SERVICE_KEY = "os.getenv('RECETAGENIAL_SUPABASE_KEY', '')"
BUCKET = "recipe-images"

images_to_update = [
    {
        "slug": "merluza-en-salsa-verde-con-almejas-y-esparragos",
        "file_path": r"C:\Users\REDX420\.gemini\antigravity\brain\bd73ffe9-b0fe-4a21-8ff9-e1a88e7d7a04\merluza_salsa_verde_1791521110223.jpg",
        "storage_path": "posts/merluza-en-salsa-verde-con-almejas-y-esparragos-hero.jpg"
    },
    {
        "slug": "rodaballo-al-horno-con-costra-de-hierbas-provenzales",
        "file_path": r"C:\Users\REDX420\.gemini\antigravity\brain\bd73ffe9-b0fe-4a21-8ff9-e1a88e7d7a04\rodaballo_al_horno_1791521144576.jpg",
        "storage_path": "posts/rodaballo-al-horno-con-costra-de-hierbas-provenzales-hero.jpg"
    },
    {
        "slug": "pollo-tikka-masala-cremoso",
        "file_path": r"C:\Users\REDX420\.gemini\antigravity\brain\bd73ffe9-b0fe-4a21-8ff9-e1a88e7d7a04\pollo_tikka_masala_1791521163650.jpg",
        "storage_path": "posts/pollo-tikka-masala-cremoso-hero.jpg"
    }
]

def upload_and_update():
    headers_storage = {
        'apikey': SERVICE_KEY,
        'Authorization': f'Bearer {SERVICE_KEY}',
        'Content-Type': 'image/jpeg',
        'x-upsert': 'true'
    }
    
    headers_db = {
        'apikey': SERVICE_KEY,
        'Authorization': f'Bearer {SERVICE_KEY}',
        'Content-Type': 'application/json',
        'Prefer': 'return=representation'
    }

    for item in images_to_update:
        slug = item["slug"]
        local_path = item["file_path"]
        storage_path = item["storage_path"]
        
        print(f"\nProcessing {slug}...")
        with open(local_path, "rb") as f:
            img_bytes = f.read()
            
        # 1. Upload to Supabase Storage
        upload_url = f"{SUPABASE_URL}/storage/v1/object/{BUCKET}/{storage_path}"
        req = urllib.request.Request(upload_url, data=img_bytes, headers=headers_storage, method='POST')
        try:
            with urllib.request.urlopen(req) as resp:
                print(f" [+] Uploaded to Storage: {storage_path}")
        except Exception as e:
            # Try PUT if POST fails (upsert)
            req = urllib.request.Request(upload_url, data=img_bytes, headers=headers_storage, method='PUT')
            with urllib.request.urlopen(req) as resp:
                print(f" [+] Uploaded (PUT) to Storage: {storage_path}")

        public_url = f"{SUPABASE_URL}/storage/v1/object/public/{BUCKET}/{storage_path}"
        print(f" Public URL: {public_url}")

        # 2. Update post featured_image in Supabase
        update_data = json.dumps({"featured_image": public_url}).encode('utf-8')
        db_url = f"{SUPABASE_URL}/rest/v1/posts?slug=eq.{slug}"
        db_req = urllib.request.Request(db_url, data=update_data, headers=headers_db, method='PATCH')
        with urllib.request.urlopen(db_req) as resp:
            print(f" [+] Updated post {slug} in DB with new featured_image!")

if __name__ == "__main__":
    upload_and_update()
