# -*- coding: utf-8 -*-
import sys
import io
import re
import json
import base64
from pathlib import Path
import requests
from openai import OpenAI

# Force UTF-8 for Windows
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

"""
RecetaDolce Content Wizard — Gemini Edition
=============================================
Generates premium Pinterest and Blog content with EEAT Signals.

Usage:
  python scripts/content_wizard.py "keyword" [--publish]
"""

# ——— CONFIG ————————————————————————————————————————————————————————————————————————
ANTIGRAVITY_URL = "http://localhost:8045/v1"
ANTIGRAVITY_KEY = "sk-b0f6ebb49b4142deae96af4f56f99ae3"
TEXT_MODEL      = "gemini-3.1-pro"
IMAGE_MODEL     = "gemini-3.1-pro"

SUPABASE_URL    = "https://xjvmnmfczvwkjiasirsl.supabase.co"
SUPABASE_KEY    = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Inhqdm1ubWZjenZ3a2ppYXNpcnNsIiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc3ODIwNjgxMywiZXhwIjoyMDkzNzgyODEzfQ.LWI7MaXTdR5Ma1rdvaCtUrDL-C0rNefro5Qj16QIy0o"
SUPABASE_BUCKET = "recipe-images"

SITE_URL = "https://RecetaDolce.com"

SCRIPTS_DIR = Path(__file__).parent
PROJECT_DIR = SCRIPTS_DIR.parent
OUTPUT_DIR  = PROJECT_DIR / "output"
OUTPUT_DIR.mkdir(exist_ok=True)
CONFIG_FILE = PROJECT_DIR / "nexus_config.json"

def get_nexus_config():
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {
        "niche": "recetas de cocina premium",
        "voice": "profesional, autoritario, experto, cercano",
        "brand_name": "RecetaDolce",
        "language": "es"
    }

NEXUS_CONFIG = get_nexus_config()

# ——— EEAT SYSTEM PROMPT ————————————————————————————————————————————————————————————
EEAT_SYSTEM_PROMPT = """You are Isabella Dolce, a professional chef trained at Le Cordon Bleu and founder of RecetaDolce. 
Your Expertise: High-end Spanish and Mediterranean cuisine.
Your Authority: You strictly adhere to regulatory food safety frameworks including AESAN (Spain), EFSA (EU), and Codex Alimentarius.
Your Mission: To provide recipes that are not only delicious but technically flawless and safety-compliant.

MANDATORY SAFETY STANDARDS:
- For SEAFOOD: Reference AESAN/EFSA safety guidelines.
- For MEAT: Reference Codex Alimentarius standards for safe handling.
- For EGGS/PREPARED MEALS: Reference RD 1021/2022 and Ley 17/2011.

Integration: Naturally cite these authorities when discussing high-risk ingredients or hygiene steps."""

# ——— PROMPTS ——————————————————————————————————————————————————————————————————————

BLOG_PROMPT = """Generate a professional {language} recipe blog post for: "{keyword}"
Target SEO keyword: "{keyword}"
Niche: {niche}
Brand Name: {brand_name}
Voice/Tone: {voice}

Return ONLY a valid JSON object:
{{
  "title": "SEO title in {language} (60 chars max, include keyword naturally)",
  "slug": "url-friendly-slug",
  "category": "Detect appropriate category (e.g., Postres, Arroces, Tapas)",
  "chef_tip": "One premium professional tip for the recipe (max 150 chars)",
  "content": "Full Markdown, 1200+ words. Sections: introduccion, historia/origen, ingredientes detallados, paso a paso numerado, tips de chef, variaciones, maridaje. 
  
  EEAT REQUIREMENT: You MUST include a 'Seguridad Alimentaria y Calidad' section citing relevant authorities (AESAN, EFSA, Codex, or RD 1021/2022) especially if the recipe involves seafood, meat, or raw eggs. Citations should be professional and authoritative.",
  
  "excerpt": "2-sentence excerpt max 200 chars including the chef's authority",
  "meta_title": "SEO meta title under 60 chars",
  "meta_description": "SEO description 150-160 chars with keyword and authority signal",
  "keywords": ["keyword1", "keyword2", "keyword3"],
  "image_alt": "Descriptive alt text for the featured image (SEO optimized)",
  "estimated_cost": "Cost estimation: Economico, Medio, or Premium",
  "recipe_schema": {{
    "prepTime": "XX minutos",
    "cookTime": "XX minutos",
    "totalTime": "XX minutos",
    "servings": 4,
    "calories": "XXX kcal",
    "difficulty": "Facil",
    "secret_ingredient": "A unique ingredient or technique that makes it special",
    "texture_description": "Descriptive sentence about the unique texture of the dish",       
    "ingredients": ["..."],
    "instructions": ["..."],
    "nutrition": {{"calories": "XXX kcal", "protein": "Xg", "carbs": "Xg", "fat": "Xg"}}      
  }},
  "faq_schema": [
    {{"question": "...", "answer": "..."}}
  ],
  "pinterest_metadata": {{
    "title": "Pinterest Title",
    "description": "Pinterest Description with hashtags and security/quality signal #RecetaDolce #CocinaSegura",
    "hashtags": ["#Tag1", "#Tag2"]
  }}
}}"""

PIN_VISUAL_PROMPT = """TASK:
Create a luxury, high-end Pinterest pin (1000x1500px, vertical 2:3 ratio) with a rustic editorial recipe card layout.

INPUT:
Recipe Name: {recipe_name}

---

STEP 1 — AUTO-OPTIMIZE TITLE:
- Detect the language of the recipe
- If not Spanish → translate to natural, appetizing Spanish
- Upgrade wording to sound premium, emotional, and viral-worthy
- Keep it short and mouthwatering

---

STEP 2 — VISUAL CONCEPT:

TOP BANNER:
- Vintage parchment texture with slightly burned edges
- Warm beige tones with subtle grain
- Decorative elements based on recipe (ingredients, tools, icons)
- Elegant serif + handwritten script typography
- Display refined title

---

CENTER IMAGE (HERO FOOD):
- Ultra-realistic, editorial-quality food photography of {recipe_name}
- Styled as a premium plated dish or dessert
- Show textures clearly (creamy, crunchy, juicy, etc.)
- Add natural garnishes related to the recipe
- Scene styling:
  - Rustic wooden surface
  - Kitchen cloth (linen or patterned)
  - 1–2 complementary props (ingredient bowls, utensils, drink)
- Lighting:
  - Warm, soft natural light
  - Slight shadows for depth
  - Shallow depth of field (sharp subject, soft background)

---

BOTTOM SECTION (RECIPE CARD):

LEFT COLUMN — “Ingredientes”
- Auto-generate realistic ingredients for {recipe_name}
- Add small illustrated visuals for key ingredients
- Use warm brown text and clean bullet points

RIGHT COLUMN — “Pasos”
- Generate 3–5 simple, clear steps
- Add small icons (mixing, baking, cutting, etc.)
- Friendly, easy-to-read tone

---

FOOTER:
- Add emotional handwritten phrase:
  “¡Irresistible!”, “¡Delicioso!”, or similar
- Include small decorative icons (hearts, food shapes)

---

STYLE RULES:
- Color palette adapted to recipe (chocolate = dark brown, fruit = vibrant tones, etc.)       
- Rustic + cozy + premium aesthetic
- Editorial food magazine quality
- Balanced composition, not cluttered
- Highly appetizing and Pinterest-optimized

---

NEGATIVE PROMPT:
blurry, low quality, flat lighting, bad typography, distorted text, unrealistic food, messy layout, modern minimal UI

---

OUTPUT:
A complete, cohesive Pinterest pin design ready for image generation."""

# ——— CORE LOGIC ————————————————————————————————————————————————————————————————————

def generate_text(prompt, system_prompt=EEAT_SYSTEM_PROMPT):
    client = OpenAI(base_url=ANTIGRAVITY_URL, api_key=ANTIGRAVITY_KEY)
    try:
        response = client.chat.completions.create(
            model=TEXT_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt}
            ],
            response_format={"type": "json_object"} if "JSON" in prompt else None
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        print(f"[ERROR] Text generation failed: {e}")
        return None

def generate_image(prompt, aspect_ratio="2:3"):
    client = OpenAI(base_url=ANTIGRAVITY_URL, api_key=ANTIGRAVITY_KEY)
    try:
        print(f"[IMG] Generating image with aspect ratio {aspect_ratio}...")
        response = client.images.generate(
            model=IMAGE_MODEL,
            prompt=prompt,
            n=1,
            size="1000x1500" if aspect_ratio == "2:3" else "1024x768",
            response_format="b64_json"
        )
        return base64.b64decode(response.data[0].b64_json)
    except Exception as e:
        print(f"[ERROR] Image generation failed: {e}")
        return None

def upload_to_supabase(data, filename, bucket=SUPABASE_BUCKET):
    url = f"{SUPABASE_URL}/storage/v1/object/{bucket}/{filename}"
    headers = {
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "x-upsert": "true"
    }
    content_type = "image/jpeg" if filename.endswith(".jpg") else ("image/png" if filename.endswith(".png") else "application/json")
    headers["Content-Type"] = content_type

    resp = requests.post(url, headers=headers, data=data)
    if resp.status_code in [200, 201]:
        return f"{SUPABASE_URL}/storage/v1/object/public/{bucket}/{filename}"
    return None

def main():
    if len(sys.argv) < 2:
        print("Usage: python scripts/content_wizard.py 'keyword' [--publish]")
        return

    keyword = sys.argv[1]
    publish = "--publish" in sys.argv

    print(f"\n[START] Content Wizard (EEAT Enabled) for: {keyword}")
    print("=" * 50)

    # 1. Generate Blog Content
    print("\n[BLOG] Generating Blog Article...")
    lang_name = "Spanish" if NEXUS_CONFIG.get("language") == "es" else "English"
    raw_blog = generate_text(BLOG_PROMPT.format(
        keyword=keyword,
        language=lang_name,
        niche=NEXUS_CONFIG.get("niche"),
        voice=NEXUS_CONFIG.get("voice"),
        brand_name=NEXUS_CONFIG.get("brand_name")
    ))
    if not raw_blog: return
    blog_data = json.loads(re.sub(r'^```json\s*|\s*```$', '', raw_blog, flags=re.MULTILINE))  
    recipe_name = blog_data["title"]
    slug = blog_data["slug"]

    # 2. Generate Pinterest Pin Image
    print("\n[PIN] Generating Luxury Pinterest Pin...")
    pin_prompt = PIN_VISUAL_PROMPT.format(recipe_name=recipe_name)
    pin_image = generate_image(pin_prompt, aspect_ratio="2:3")

    # 3. Generate Featured Blog Image
    print("\n[HERO] Generating Featured Image (4:3)...")
    featured_prompt = f"Ultra high-end editorial food photography of {recipe_name}. rustic wooden surface, linen cloth, natural lighting, shallow depth of field, 4:3."
    featured_image = generate_image(featured_prompt, aspect_ratio="4:3")

    # 4. Save Locally
    out_path = OUTPUT_DIR / slug
    out_path.mkdir(exist_ok=True)

    with open(out_path / "article.json", "w", encoding="utf-8") as f:
        json.dump(blog_data, f, indent=2, ensure_ascii=False)

    if pin_image:
        with open(out_path / "pinterest_pin.png", "wb") as f:
            f.write(pin_image)

    if featured_image:
        with open(out_path / "featured.jpg", "wb") as f:
            f.write(featured_image)

    print(f"\n[SAVE] Content saved to: {out_path}")

    # 5. Optional Publishing
    if publish:
        print("\n[PUBLISH] Publishing to Supabase...")
        feat_url = upload_to_supabase(featured_image, f"posts/{slug}.jpg") if featured_image else None
        
        if feat_url:
            blog_data["featured_image"] = feat_url

        # Prepare for Supabase DB
        db_payload = blog_data.copy()

        # Map metrics
        rs = db_payload.get("recipe_schema", {})
        if rs:
            try:
                db_payload["prep_time"] = int("".join(filter(str.isdigit, str(rs.get("prepTime", "0")))))
                db_payload["cook_time"] = int("".join(filter(str.isdigit, str(rs.get("cookTime", "0")))))
                db_payload["difficulty"] = rs.get("difficulty", "Media")
            except: pass

        db_payload["recipe_schema"] = json.dumps(db_payload["recipe_schema"], ensure_ascii=False)
        db_payload["faq_schema"] = json.dumps(db_payload["faq_schema"], ensure_ascii=False)   
        db_payload.pop("pinterest_metadata", None)

        headers = {
            "apikey": SUPABASE_KEY,
            "Authorization": f"Bearer {SUPABASE_KEY}",
            "Content-Type": "application/json",
            "Prefer": "return=minimal"
        }

        # Check if exists
        check = requests.get(f"{SUPABASE_URL}/rest/v1/posts?slug=eq.{slug}", headers=headers) 
        if check.status_code == 200 and check.json():
            resp = requests.patch(f"{SUPABASE_URL}/rest/v1/posts?slug=eq.{slug}", headers=headers, json=db_payload)
            print(f"[LIVE] Article updated at: {SITE_URL}/{slug}")
        else:
            resp = requests.post(f"{SUPABASE_URL}/rest/v1/posts", headers=headers, json=db_payload)
            print(f"[LIVE] Article live at: {SITE_URL}/{slug}")

if __name__ == "__main__":
    main()
