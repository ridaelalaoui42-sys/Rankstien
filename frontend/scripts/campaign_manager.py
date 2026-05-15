# -*- coding: utf-8 -*-
"""
RecetaDolce Campaign Manager — EEAT Enabled
==============================================
Manages content campaigns with authoritative EEAT signals.
"""

import sys
import io
import json
import os
import re
import base64
import time
import requests
from pathlib import Path
from openai import OpenAI

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

# ——— CONFIG ————————————————————————————————————————————————————————————————————————
ANTIGRAVITY_URL = "http://localhost:8045/v1"
ANTIGRAVITY_KEY = "sk-b0f6ebb49b4142deae96af4f56f99ae3"
TEXT_MODEL  = "gemini-3-flash"
IMAGE_MODEL = "gemini-3-flash"

SUPABASE_URL    = "https://xjvmnmfczvwkjiasirsl.supabase.co"
SUPABASE_KEY    = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Inhqdm1ubWZjenZ3a2ppYXNpcnNsIiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc3ODIwNjgxMywiZXhwIjoyMDkzNzgyODEzfQ.LWI7MaXTdR5Ma1rdvaCtUrDL-C0rNefro5Qj16QIy0o"
SUPABASE_BUCKET = "recipe-images"

PINTEREST_TOKEN    = os.getenv("PINTEREST_ACCESS_TOKEN", "")
PINTEREST_BOARD_ID = os.getenv("PINTEREST_BOARD_ID", "")
SITE_URL           = "https://RecetaDolce.com"

SCRIPTS_DIR   = Path(__file__).parent
CAMPAIGNS_DIR = SCRIPTS_DIR / "campaigns"
IMAGES_DIR    = SCRIPTS_DIR / "generated_images"
PINS_DIR      = SCRIPTS_DIR / "pins"
for d in [IMAGES_DIR, PINS_DIR]:
    d.mkdir(exist_ok=True)

LOCAL_FALLBACKS = {
    1: "public/images/fresas/fresas-tarta-nata.jpg",
    2: "public/images/fresas/fresas-mermelada-casera.jpg",
    3: "public/images/fresas/fresas-con-nata.jpg",
    4: "public/images/fresas/fresas-mousse-mascarpone.jpg",
    5: "public/images/fresas/fresas-batido-cremoso.jpg",
}

UNSPLASH_FALLBACKS = {
    6:  "https://images.unsplash.com/photo-1501746877-14782df58970?q=80&w=1000",
    7:  "https://images.unsplash.com/photo-1488477181946-6428a0291777?q=80&w=1000",
    8:  "https://images.unsplash.com/photo-1452195100486-9cc805987862?q=80&w=1000",
    9:  "https://images.unsplash.com/photo-1464965911861-746a04b4bca6?q=80&w=1000",
    10: "https://images.unsplash.com/photo-1518635017498-87f514b751ba?q=80&w=1000",
}

# ——— EEAT SYSTEM PROMPT ————————————————————————————————————————————————————————————
EEAT_SYSTEM_PROMPT = """You are Isabella Dolce, a professional chef trained at Le Cordon Bleu and founder of RecetaDolce. 
Your Expertise: High-end Spanish and Mediterranean cuisine.
Your Authority: You strictly adhere to regulatory food safety frameworks including AESAN (Spain), EFSA (EU), and Codex Alimentarius.
Your Mission: To provide recipes that are technically flawless and safety-compliant.

MANDATORY SAFETY STANDARDS:
- SEAFOOD: Reference AESAN/EFSA safety guidelines.
- MEAT: Reference Codex Alimentarius standards.
- EGGS/PREPARED MEALS: Reference RD 1021/2022 and Ley 17/2011.

Output ONLY raw valid JSON, no markdown fences."""

RECIPE_PROMPT = '''Generate a professional Spanish recipe blog post for: "{recipe_name}"      
Target SEO keyword: "{keyword}"
Category: "{category}"

Return ONLY a valid JSON object:
{{
  "title": "SEO title in Spanish (60 chars max)",
  "slug": "url-friendly-slug-with-fresas",
  "content": "Full Markdown, 1200+ words. Include a 'Seguridad Alimentaria' section citing AESAN, EFSA, or RD 1021/2022.",
  "excerpt": "2-sentence excerpt including authority signal",
  "category": "{category}",
  "status": "published",
  "meta_title": "SEO meta title",
  "meta_description": "SEO description with quality signal",
  "keywords": ["keyword1", "keyword2"],
  "recipe_schema": {{
    "prepTime": "XX minutos",
    "cookTime": "XX minutos",
    "totalTime": "XX minutos",
    "servings": 4,
    "ingredients": ["..."],
    "instructions": ["..."],
    "nutrition": {{"calories": "XXX kcal"}}      
  }},
  "faq_schema": [ {{"question": "...", "answer": "..."}} ],
  "pinterest_description": "Pinterest description with #RecetaDolce #CocinaSegura"
}}'''

def load_campaign(campaign_file: str) -> dict:
    path = CAMPAIGNS_DIR / campaign_file
    with open(path, "r", encoding="utf-8") as f: return json.load(f)

def save_campaign(campaign: dict, campaign_file: str):
    path = CAMPAIGNS_DIR / campaign_file
    with open(path, "w", encoding="utf-8") as f: json.dump(campaign, f, indent=2, ensure_ascii=False)

def find_campaign_file() -> str:
    files = list(CAMPAIGNS_DIR.glob("*.json"))
    if not files: sys.exit(1)
    if len(files) == 1: return files[0].name
    for i, f in enumerate(files): print(f"  [{i}] {f.name}")
    return files[int(input("Select: "))].name

def cmd_status(campaign: dict):
    articles = campaign["articles"]
    print(f"\n📋 Campaign: {campaign['name']}")
    for a in articles:
        print(f"  {a['id']:<4} {a['state']:<10} {a['recipe_name']}")

IMAGE_PROMPT_TEMPLATE = """Ultra high-end editorial food photography of {recipe_name}.        
Michelin-starred plating, Hasselblad quality, rustic restaurant aesthetic."""

def generate_image_via_api(article: dict) -> bytes | None:
    prompt = IMAGE_PROMPT_TEMPLATE.format(recipe_name=article["recipe_name"])
    try:
        client = OpenAI(base_url=ANTIGRAVITY_URL, api_key=ANTIGRAVITY_KEY)
        response = client.images.generate(model=IMAGE_MODEL, prompt=prompt, n=1, size="1024x768", response_format="b64_json")
        return base64.b64decode(response.data[0].b64_json)
    except: return None

def upload_image_to_supabase(image_bytes: bytes, filename: str) -> str | None:
    url = f"{SUPABASE_URL}/storage/v1/object/{SUPABASE_BUCKET}/{filename}"
    headers = {"Authorization": f"Bearer {SUPABASE_KEY}", "Content-Type": "image/jpeg", "x-upsert": "true"}
    resp = requests.post(url, headers=headers, data=image_bytes)
    return f"{SUPABASE_URL}/storage/v1/object/public/{SUPABASE_BUCKET}/{filename}" if resp.status_code in [200, 201] else None

def get_or_generate_image(article: dict) -> str:
    article_id = article["id"]
    slug_fn = f"fresas/{article.get('slug', f'fresas-{article_id}')}.jpg"
    img_bytes = generate_image_via_api(article)
    if img_bytes:
        url = upload_image_to_supabase(img_bytes, slug_fn)
        if url: return url
    return UNSPLASH_FALLBACKS.get(article_id, "https://images.unsplash.com/photo-1464965911861-746a04b4bca6?q=80&w=1000")

def generate_article_content(article: dict) -> dict | None:
    client = OpenAI(base_url=ANTIGRAVITY_URL, api_key=ANTIGRAVITY_KEY)
    prompt = RECIPE_PROMPT.format(recipe_name=article["recipe_name"], keyword=article["keyword"], category=article["category"], cat_tag=article["category"])
    try:
        response = client.chat.completions.create(model=TEXT_MODEL, messages=[{"role": "system", "content": EEAT_SYSTEM_PROMPT}, {"role": "user", "content": prompt}], response_format={"type": "json_object"})
        data = json.loads(re.sub(r'^```json\s*|\s*```$', '', response.choices[0].message.content.strip(), flags=re.MULTILINE))
        if isinstance(data.get("recipe_schema"), dict): data["recipe_schema"] = json.dumps(data["recipe_schema"], ensure_ascii=False)     
        if isinstance(data.get("faq_schema"), list): data["faq_schema"] = json.dumps(data["faq_schema"], ensure_ascii=False)
        return data
    except: return None

def publish_to_supabase(post_data: dict) -> str | None:
    headers = {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}", "Content-Type": "application/json", "Prefer": "return=representation"}
    check = requests.get(f"{SUPABASE_URL}/rest/v1/posts?slug=eq.{post_data['slug']}", headers=headers)
    if check.status_code == 200 and check.json():
        requests.patch(f"{SUPABASE_URL}/rest/v1/posts?slug=eq.{post_data['slug']}", headers=headers, json=post_data)
        return check.json()[0]["id"]
    resp = requests.post(f"{SUPABASE_URL}/rest/v1/posts", headers=headers, json=post_data)
    return str(resp.json()[0]["id"]) if resp.status_code in [200, 201] else None

def process_next(campaign: dict, campaign_file: str) -> bool:
    pending = [a for a in campaign["articles"] if a["state"] == "pending"]
    if not pending: return False
    article = pending[0]
    idx = next(i for i, a in enumerate(campaign["articles"]) if a["id"] == article["id"])
    campaign["articles"][idx]["state"] = "generating"
    save_campaign(campaign, campaign_file)
    img_url = get_or_generate_image(article)
    post_data = generate_article_content(article)
    if not post_data: return False
    post_data["featured_image"] = img_url
    row_id = publish_to_supabase(post_data)
    if row_id:
        campaign["articles"][idx].update({"state": "published", "slug": post_data["slug"], "supabase_id": row_id, "featured_image": img_url})
        save_campaign(campaign, campaign_file)
        return True
    return False

def main():
    args = sys.argv[1:]
    if not args: return
    campaign_file = find_campaign_file()
    cmd = args[0]
    if cmd == "status": cmd_status(load_campaign(campaign_file))
    elif cmd == "run":
        while True:
            if not process_next(load_campaign(campaign_file), campaign_file): break
            time.sleep(5)

if __name__ == "__main__": main()
