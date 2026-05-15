import asyncio
import os
import sys
import json
import requests
from pathlib import Path
from dotenv import load_dotenv

# Load env vars
load_dotenv()

# Ensure backend is in path
sys.path.append(os.getcwd())

from backend.services.remasterer import run_remasterer

from rankstein.domain import get_registry

# Removed mock registry in favor of rankstein.domain.get_registry()

BACKLOG_FILE = Path("memory/pinterest_backlog.md")
MAX_CONCURRENT_ARTICLES = 3

async def get_db_data(slug, domain_handle):
    registry = get_registry()
    domain = registry.get(domain_handle)
    if not domain:
        return {"success": False}
        
    url = f"{domain.supabase_url}/rest/v1/posts?slug=eq.{slug}&select=title,hero_image"
    key = domain.supabase_service_role_key.get_secret_value()
    headers = {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }
    try:
        resp = requests.get(url, headers=headers, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            if data:
                return {"success": True, "title": data[0].get("title")}
    except:
        pass
    return {"success": False}

async def get_domain_for_slug(slug):
    registry = get_registry()
    for domain in registry.all():
        handle = domain.handle
        res = await get_db_data(slug, handle)
        if res.get("success"):
            return handle, domain.display_name, res.get("title")
            
    return None, None, None

async def process_article(slug, title, semaphore, index):
    async with semaphore:
        session_name = f"remasterer_p{index % MAX_CONCURRENT_ARTICLES}"
        print(f"\n>>> [START] Processing: {title} ({slug}) | Session: {session_name}")
        
        domain_handle, brand_name, db_title = await get_domain_for_slug(slug)
        if not domain_handle:
            # Try fuzzy check by removing accents or common suffix
            clean_slug = slug.replace("ñ", "n").replace("á", "a").replace("é", "e").replace("í", "i").replace("ó", "o").replace("ú", "u")
            if clean_slug != slug:
                domain_handle, brand_name, db_title = await get_domain_for_slug(clean_slug)
            
            if not domain_handle:
                print(f"!!! [SKIP] Could not find domain for slug: {slug}")
                return
            
        final_title = db_title or title
        print(f"--- [INFO] Domain: {domain_handle} | Brand: {brand_name} | Title: {final_title}")
        
        try:
            # Step 1: Remaster
            pins = await run_remasterer(final_title, final_title, brand_name=brand_name, session_name=session_name)
            print(f"✅ [DONE] Generated {len(pins) if pins else 0} pins for {slug}")
            
            # Step 2: Enqueue for upload
            from rankstein_mcp_server import automation_enqueue_pin
            for pin in pins:
                img_path = pin["remastered_path"]
                try:
                    automation_enqueue_pin(
                        image_path=img_path,
                        title=final_title,
                        description=f"Descubre cómo preparar {final_title}. Receta premium de {brand_name}.",
                        link=f"https://{domain_handle}.com/{slug}",
                        board_name="Recetas Geniales"
                    )
                    print(f"   [+] Enqueued: {Path(img_path).name}")
                except Exception as eq_err:
                    print(f"   [!] Queue error: {eq_err}")
            
        except Exception as e:
            print(f"❌ [ERROR] Failed to siphon {slug}: {e}")

async def orchestrate_siphon():
    if not BACKLOG_FILE.exists():
        print("Backlog file not found.")
        return

    with open(BACKLOG_FILE, encoding="utf-8") as f:
        lines = f.readlines()

    to_process = []
    for line in lines:
        if "|" in line and "Article Slug" not in line and "---" not in line:
            parts = [p.strip() for p in line.split("|")]
            if len(parts) >= 4:
                slug = parts[1]
                title = parts[2]
                status = parts[3]
                if status in ["Missing", "Failed"]:
                    to_process.append((slug, title))

    print(f"Found {len(to_process)} items to process in Social Siphon.")
    
    semaphore = asyncio.Semaphore(MAX_CONCURRENT_ARTICLES)
    tasks = [process_article(slug, title, semaphore, i) for i, (slug, title) in enumerate(to_process)]
    
    await asyncio.gather(*tasks)

    print("\n\n=== Social Siphon Remastering Phase Complete ===")
    print("The Autonomous Supervisor is processing the queue in parallel.")

if __name__ == "__main__":
    asyncio.run(orchestrate_siphon())
