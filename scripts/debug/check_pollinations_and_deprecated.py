import os
import requests
from dotenv import load_dotenv

load_dotenv()

rg_url = "https://hokcljsrrnjxzgdhjice.supabase.co"
rg_key = os.environ.get("RECETAGENIAL_SUPABASE_KEY") or os.environ.get("SUPABASE_SERVICE_ROLE_KEY_RECETAGENIAL") or os.environ.get("SUPABASE_SERVICE_ROLE_KEY")

rd_url = "https://xjvmnmfczvwkjiasirsl.supabase.co"
rd_key = os.environ.get("RECETADOLCE_SUPABASE_KEY") or os.environ.get("SUPABASE_SERVICE_ROLE_KEY_RECETADOLCE")


def check_db(name, url, key):
    if not url or not key:
        print(f"{name}: Missing credentials")
        return
    headers = {"apikey": key, "Authorization": f"Bearer {key}"}
    resp = requests.get(
        f"{url}/rest/v1/posts?select=id,title,slug,featured_image,content,recipe_schema",
        headers=headers,
    )
    if resp.status_code != 200:
        print(f"{name}: HTTP error {resp.status_code}")
        return
    posts = resp.json()
    print(f"=== {name} (Total: {len(posts)}) ===")
    pollinations_featured = 0
    pollinations_content = 0
    pollinations_schema = 0
    empty_images = 0
    image_counts = {}
    for p in posts:
        img = p.get("featured_image") or ""
        content = p.get("content") or ""
        schema = str(p.get("recipe_schema") or "")
        if "pollination" in img.lower():
            pollinations_featured += 1
            print(f"  [POLLINATIONS FEATURED] {p['slug']}: {img}")
        if "pollination" in content.lower():
            pollinations_content += 1
            print(f"  [POLLINATIONS CONTENT] {p['slug']}")
        if "pollination" in schema.lower():
            pollinations_schema += 1
            print(f"  [POLLINATIONS SCHEMA] {p['slug']}")
        if not img:
            empty_images += 1
        image_counts[img] = image_counts.get(img, 0) + 1

    repeated = {k: v for k, v in image_counts.items() if v > 1 and k}
    print(f"  Pollinations in featured_image: {pollinations_featured}")
    print(f"  Pollinations in content: {pollinations_content}")
    print(f"  Pollinations in recipe_schema: {pollinations_schema}")
    print(f"  Empty images: {empty_images}")
    print(f"  Repeated images (>1): {len(repeated)}")


check_db("RECETAGENIAL", rg_url, rg_key)
check_db("RECETADOLCE", rd_url, rd_key)
