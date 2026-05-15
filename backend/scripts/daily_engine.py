"""
================================================================================
RETIRED — NOT THE PRIMARY RUNNER
================================================================================
This script is retired and is no longer the primary entry point.

PRIMARY ENTRY POINT:
    python rankstein.py run

The current autonomous pipeline runs via:
    Gemini CLI subscription + AgentMemory + domain-aware startup workers

This file is kept for reference only. Running it directly delegates to the
production startup runner to avoid stale single-domain behavior.
================================================================================
"""

import asyncio
import json
import os
import random
import re
import subprocess
from datetime import datetime
from pathlib import Path

import requests

from backend.scripts.batch_upload_remastered import deploy_remastered_campaign
from backend.scripts.deploy_generic import upload_file

# Import existing RankStein modules
from backend.services.remasterer import inject_seo_metadata, run_remasterer

# ---------- CONFIG ----------
SUPABASE_URL = os.environ.get("NEXT_PUBLIC_SUPABASE_URL", "https://xjvmnmfczvwkjiasirsl.supabase.co")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
KEYWORDS_FILE = PROJECT_ROOT / "memory" / "keywords.md"


async def get_pending_keyword():
    """Reads keywords.md and returns the highest priority pending keyword and its cluster."""
    if not KEYWORDS_FILE.exists():
        return None, None

    with open(KEYWORDS_FILE, encoding="utf-8") as f:
        lines = f.readlines()

    for line in lines:
        if "Pending" in line and "High" in line:
            parts = [p.strip() for p in line.split("|")]
            if len(parts) > 2:
                return parts[1], parts[2]

    # Auto-promote first Medium + Pending
    for line in lines:
        if "Pending" in line and "Medium" in line:
            parts = [p.strip() for p in line.split("|")]
            if len(parts) > 2:
                keyword = parts[1]
                print(f"📈 Auto-promoting Medium keyword to High: '{keyword}'")
                _update_keyword_field(keyword, priority="High")
                return keyword, parts[2]

    return None, None


def _update_keyword_field(keyword, priority=None, status=None):
    """Updates priority or status of a keyword in keywords.md."""
    with open(KEYWORDS_FILE, encoding="utf-8") as f:
        content = f.read()
    lines = content.split("\n")
    for i, line in enumerate(lines):
        if f"| {keyword} |" in line:
            parts = line.split("|")
            if len(parts) >= 7:
                if priority:
                    parts[-3] = f" {priority} "
                if status:
                    parts[-2] = f" {status} "
                lines[i] = "|".join(parts)
            break
    with open(KEYWORDS_FILE, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def mark_keyword_status(keyword, status):
    """Updates the status of a keyword in keywords.md."""
    _update_keyword_field(keyword, status=status)


async def generate_article_content(keyword):
    """
    Cocinero Master Agent Logic using native Gemini CLI.
    Generates a 2500-3500 word skyscraper article mapped perfectly to the Supabase database schema.
    """
    print(f"👨‍🍳 Cocinero is generating Skyscraper content for '{keyword}'...")

    prompt = f"""Generate a high-end SEO optimized recipe blog post in Spanish for the keyword: {keyword}.
CRITICAL INSTRUCTIONS: DO NOT USE ANY TOOLS. DO NOT CREATE A PLAN. DO NOT OUTPUT ANY CONVERSATIONAL TEXT. 
Return ONLY a raw, valid JSON object. 
Act as a Master Chef and SEO Expert. Include E-E-A-T signals (e.g., citing AESAN or EFSA), the scientific background of ingredients, and advanced chef tips.

Schema mapping strictly to our database columns:
{{
  "title": "SEO-optimized, emotive title (max 60 chars)",
  "slug": "url-friendly-slug-without-special-chars",
  "content": "Full markdown content. Minimum 2000 words. MUST include exactly these placeholders: [HERO_IMAGE] after the introduction, [PINTEREST_IFRAME_STEPS] before the step-by-step instructions, and [PINTEREST_IFRAME_FINAL] at the very end. Include H2/H3 tags, ingredient science, history, and variations.",
  "excerpt": "Compelling summary (max 155 chars) for blog cards.",
  "featured_image": "PLACEHOLDER",
  "category": "Choose from: Aperitivos, Postres, Ensaladas, Carnes, Pescados",
  "status": "published",
  "meta_title": "SEO Title (max 60 chars)",
  "meta_description": "SEO Meta Description (max 155 chars)",
  "keywords": ["keyword1", "keyword2", "keyword3", "keyword4"],
  "difficulty": "Baja, Media, or Alta",
  "estimated_cost": "Económico, Medio, or Alto",
  "prep_time": 15,
  "cook_time": 30,
  "image_alt": "Alt text for the main image",
  "chef_tip": "One advanced culinary secret that elevates the dish.",
  "recipe_schema": {{
    "@context": "https://schema.org/",
    "@type": "Recipe",
    "name": "{keyword.title()}",
    "description": "Aprende el secreto de chef para hacer esta receta en casa de forma fácil y económica.",
    "recipeYield": "4 raciones",
    "prepTime": "PT15M",
    "cookTime": "PT30M",
    "totalTime": "PT45M",
    "recipeIngredient": ["Ingrediente 1", "Ingrediente 2"],
    "recipeInstructions": [{{"@type": "HowToStep", "text": "Paso 1"}}]
  }},
  "faq_schema": [
    {{"question": "¿Se puede guardar para el día siguiente?", "answer": "Sí, en la nevera por 2 días máximo."}}
  ],
  "pinterest_pin_prompt": "A highly visual, luxury editorial style pin prompt for this recipe. Max 2 sentences."
}}
"""

    try:
        # Run Gemini CLI
        print("   🧠 Engaging Gemini CLI for content...")
        # Force raw text output and disable all tools/agentic behavior to prevent planning
        process = subprocess.Popen(
            f'gemini -p "{prompt}" -o text --yolo --allowed-tools none --allowed-mcp-server-names none',
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
        )
        stdout, stderr = process.communicate(timeout=600)  # 10 min timeout for generation

        match = re.search(r"\{[\s\S]*\}", stdout)
        if match:
            raw_text = match.group(0)
            article = json.loads(raw_text)

            # Ensure slug is clean
            if "slug" not in article or not article["slug"]:
                article["slug"] = re.sub(r"[^a-z0-9]", "-", keyword.lower())
                article["slug"] = re.sub(r"-+", "-", article["slug"]).strip("-")

            print(f"   ✅ Gemini generated {len(article.get('content', '').split())} words for '{keyword}'")
            return article
        else:
            print(f"   ❌ Failed to extract JSON from Gemini CLI output. Output: {stdout[:200]}")
            raise Exception("Invalid JSON output")

    except Exception as e:
        print(f"   ⚠️ Gemini CLI generation failed: {e}. Falling back to default template.")

        slug = re.sub(r"[^a-z0-9]", "-", keyword.lower())
        slug = re.sub(r"-+", "-", slug).strip("-")

        article = {
            "title": f"{keyword.title()}: La Guía Definitiva y Viral 2026",
            "slug": slug,
            "meta_title": f"{keyword.title()} | Receta Fácil y Original",
            "meta_description": f"Descubre cómo preparar {keyword} paso a paso. Secretos de chef y trucos E-E-A-T para un resultado espectacular.",
            "excerpt": f"Aprende el secreto de chef para hacer {keyword} en casa de forma fácil y económica.",
            "content": f"# {keyword.title()}\n\nBienvenidos a la mejor guía de {keyword}...\n\n[HERO_IMAGE]\n\n## La Ciencia de la Receta\n\n🛡️ **Seguridad Alimentaria (AESAN):** Siguiendo las recomendaciones oficiales, es imperativo mantener la higiene en todas las fases de preparación.\n\n## Paso a Paso\n\n[PINTEREST_IFRAME_STEPS]\n\n*(Contenido optimizado por Cocinero Expert)*\n\n[PINTEREST_IFRAME_FINAL]",
            "keywords": [keyword, "receta viral", "2026", "paso a paso"],
            "difficulty": "Media",
            "estimated_cost": "Medio",
            "prep_time": 15,
            "cook_time": 20,
            "image_alt": f"Plato terminado de {keyword}",
            "chef_tip": "Usa ingredientes frescos de proximidad para potenciar el sabor y la textura.",
            "recipe_schema": {
                "@context": "https://schema.org/",
                "@type": "Recipe",
                "name": keyword.title(),
                "recipeYield": "4 raciones",
                "recipeCategory": "Aperitivos",
                "nutrition": {"@type": "NutritionInformation", "calories": "250 kcal"},
                "recipeIngredient": ["Ingrediente 1", "Ingrediente 2"],
                "recipeInstructions": [{"@type": "HowToStep", "text": "Mezclar y servir."}],
            },
            "faq_schema": [
                {
                    "question": "¿Se puede guardar para el día siguiente?",
                    "answer": "Sí, en la nevera por 2 días máximo.",
                }
            ],
            "pinterest_pin_prompt": f"Luxury editorial food photography of {keyword}, dark moody background, high contrast.",
        }
        return article


async def publish_to_supabase(data, viral_url, pin_id=None, category="Aperitivos"):
    """Publicador Agent logic - Optimized for blog frontend visibility and full schema compliance."""
    final_category = data.get("category", category)

    db_payload = {
        "title": data.get("title"),
        "slug": data.get("slug"),
        "content": data.get("content", ""),
        "meta_title": data.get("meta_title"),
        "meta_description": data.get("meta_description"),
        "excerpt": data.get("excerpt"),
        "category": final_category,
        "featured_image": viral_url,
        "pinterest_pin_id": pin_id,
        "keywords": data.get("keywords", []),
        "difficulty": data.get("difficulty", "Media"),
        "estimated_cost": data.get("estimated_cost", "Medio"),
        "prep_time": data.get("prep_time", 20),
        "cook_time": data.get("cook_time", 30),
        "image_alt": data.get("image_alt", data.get("title")),
        "chef_tip": data.get("chef_tip", ""),
        "recipe_schema": data.get("recipe_schema", {}),
        "faq_schema": data.get("faq_schema", []),
        "status": "published",
    }

    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "return=representation",
    }

    print(
        f"💾 Publicador saving to Supabase: {data.get('slug')} (Pin ID: {pin_id}, Category: {final_category})"
    )
    check = requests.get(f"{SUPABASE_URL}/rest/v1/posts?slug=eq.{data.get('slug')}", headers=headers)
    if check.status_code == 200 and check.json():
        resp = requests.patch(
            f"{SUPABASE_URL}/rest/v1/posts?slug=eq.{data.get('slug')}", headers=headers, json=db_payload
        )
    else:
        resp = requests.post(f"{SUPABASE_URL}/rest/v1/posts", headers=headers, json=db_payload)

    return resp.status_code in [200, 201, 204]


async def generate_ai_hero_image(keyword, slug):
    """Generates a unique AI hero image using Nano Banana via MCP."""
    print(f"🎨 Generating AI Hero Image for: '{keyword}' via Nano Banana MCP...")

    output_dir = PROJECT_ROOT / "nanobanana-output"
    output_dir.mkdir(parents=True, exist_ok=True)

    try:
        # Ask Gemini CLI to use the Nano Banana MCP to generate the image
        prompt = f"Use the mcp_nanobanana_generate_image tool to generate a single high-end, luxury editorial food photography image for the recipe '{keyword}'. Output format should be 'separate'. Reply ONLY with 'DONE'."

        process = subprocess.Popen(
            f'gemini -p "{prompt}" -o text --yolo',
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
        )
        stdout, stderr = process.communicate(timeout=600)

        # Wait for file system to sync
        await asyncio.sleep(5)

        # Grab the newest image in the nanobanana-output folder
        files = list(output_dir.glob("*.png")) + list(output_dir.glob("*.jpg"))
        if files:
            newest_file = max(files, key=os.path.getmtime)
            print(f"   ✅ Nano Banana image acquired: {newest_file.name}")
            return str(newest_file)

        raise Exception("No new images found in output directory after MCP call.")

    except Exception as e:
        print(f"   ⚠️ Nano Banana MCP generation failed: {e}")
        fallbacks = list(output_dir.glob("*.png"))
        if fallbacks:
            chosen = random.choice(fallbacks)
            print(f"   🔄 Using fallback image: {chosen.name}")
            return str(chosen)
        print("   ❌ No fallback images available")
        return ""


async def daily_growth_loop():
    """The Master Orchestrator Loop - Premium Edition."""
    print(f"\n[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 🚀 INITIATING DAILY GROWTH LOOP")

    keyword, category = await get_pending_keyword()
    if not keyword:
        print("🧊 No 'High' priority 'Pending' keywords found. Sleeping for 24h.")
        return

    category_map = {
        "Postres": "postres",
        "Fusion": "aperitivos",
        "Pasabocas": "aperitivos",
        "Vegetariano 2026": "ensaladas",
        "Finger Food": "aperitivos",
        "Aperitivos": "aperitivos",
        "Carnes": "carnes",
        "Pescados": "pescados",
    }
    final_category = category_map.get(category, "aperitivos")

    print(f"🎯 Target Acquired: '{keyword}' in Category: '{final_category}'")
    mark_keyword_status(keyword, "In Progress")

    try:
        article_data = await generate_article_content(keyword)
        slug = article_data["slug"]

        hero_local_path = await generate_ai_hero_image(keyword, slug)

        remastered_pins = await run_remasterer(keyword, article_data["title"])

        hero_url = ""
        if os.path.exists(hero_local_path):
            print("📤 Uploading AI Hero to Supabase...")
            # Inject SEO Metadata to the AI Hero image
            seo_title = f"{keyword.title()} | Receta Dolce"
            seo_desc = f"Aprende cómo preparar {keyword} paso a paso. Receta espectacular."
            seo_keys = f"{keyword}, receta, paso a paso, 2026, recetadolce"
            inject_seo_metadata(hero_local_path, seo_title, seo_desc, seo_keys)

            hero_url = upload_file(hero_local_path, f"posts/{slug}-hero.png")

        if not hero_url and remastered_pins:
            hero_url = upload_file(remastered_pins[0]["remastered_path"], f"posts/{slug}-hero.png")

        article_data["content"] = article_data["content"].replace(
            "[HERO_IMAGE]", f'<img src="{hero_url}" alt="{keyword}" class="w-full rounded-xl shadow-lg mb-8">'
        )
        article_data["content"] = article_data["content"].replace("[PINTEREST_IFRAME_STEPS]", "")
        article_data["content"] = article_data["content"].replace("[PINTEREST_IFRAME_FINAL]", "")

        master_pin_id = None
        if remastered_pins:
            print("📢 Capturing Master Pin ID...")
            from backend.scripts.batch_upload_remastered import BatchPinUploader

            uploader = BatchPinUploader(headless=True)
            if await uploader.start():
                master_pin_id = await uploader.upload_remastered_pin(
                    remastered_pins[0]["remastered_path"],
                    f"{keyword.title()} - Tendencia 2026",
                    f"https://recetadolce.com/{slug}",
                    f"Descubre la mejor receta de {keyword}. #RecetaDolce",
                )
                await uploader.stop()

        success = await publish_to_supabase(article_data, hero_url, master_pin_id, final_category)
        if not success:
            raise Exception("Failed to publish to Supabase.")

        print(f"✅ Article Live on RecetaDolce in '{final_category}'")

        if remastered_pins:
            print("📢 Starting Batch Social Funnel...")
            await deploy_remastered_campaign(slug, keyword.title(), remastered_pins)

        mark_keyword_status(keyword, "Live")
        print("🏁 Daily Cycle Complete.")

    except Exception as e:
        print(f"❌ Critical Error in Daily Loop: {e}")
        mark_keyword_status(keyword, "Failed")


async def run_forever():
    while True:
        await daily_growth_loop()
        delay = 86400 + random.randint(0, 7200)
        print(f"💤 Loop entering sleep state. Next autonomous run scheduled in {delay} seconds.")
        await asyncio.sleep(delay)


if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser(description="RankStein Daily Engine")
    parser.add_argument("--run-once", action="store_true", help="Run the loop once and exit.")
    args = parser.parse_args()

    cmd = [sys.executable, str(PROJECT_ROOT / "rankstein.py"), "run", "--all"]
    if args.run_once:
        cmd.append("--no-launch")
    raise SystemExit(subprocess.call(cmd, cwd=PROJECT_ROOT))
