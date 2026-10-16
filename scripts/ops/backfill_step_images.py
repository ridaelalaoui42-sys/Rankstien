"""
Backfill Step Images for Existing Published Articles.
Scans data/media/steps/ for existing step images, uploads any un-uploaded ones to Supabase storage,
and updates the corresponding post in the Supabase database.
"""

from __future__ import annotations

import json
import logging
import re
import sys
from pathlib import Path

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

import requests

from backend.scripts.turbo_articles import _embed_step_images_in_content
from rankstein.domain import get_registry
from rankstein_mcp_server import upload_image_to_supabase

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("backfill_steps")


def backfill_all_domains():
    steps_dir = PROJECT_ROOT / "data" / "media" / "steps"
    if not steps_dir.exists():
        logger.warning("No data/media/steps directory found.")
        return

    # Map slug -> list of step files
    slug_files: dict[str, list[tuple[int, Path]]] = {}
    for f in steps_dir.glob("*-step-*.jpg"):
        m = re.match(r"^(.+)-step-(\d+)\.jpg$", f.name)
        if m:
            s_slug = m.group(1)
            s_num = int(m.group(2))
            slug_files.setdefault(s_slug, []).append((s_num, f))

    for s_slug in slug_files:
        slug_files[s_slug].sort(key=lambda x: x[0])

    logger.info("Found step image sets for %d distinct slugs.", len(slug_files))

    registry = get_registry()
    domains = [registry.get("recetadolce"), registry.get("recetagenial")]

    updated_count = 0

    for domain in domains:
        url = domain.supabase_url
        key = domain.supabase_service_role_key.get_secret_value()
        headers = {
            "apikey": key,
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "Prefer": "return=representation",
        }

        for slug, step_items in slug_files.items():
            # Check if post exists for this domain
            try:
                resp = requests.get(
                    f"{url}/rest/v1/posts?slug=eq.{slug}&select=id,title,slug,content,recipe_schema,step_images",
                    headers=headers,
                    timeout=30,
                )
            except Exception as get_err:
                logger.warning("[%s] Error fetching '%s': %s", domain.handle, slug, get_err)
                continue

            if resp.status_code != 200 or not resp.json():
                continue

            post = resp.json()[0]

            # Skip if already has step images
            if post.get("step_images") and len(post["step_images"]) >= len(step_items):
                continue

            # Upload images to Supabase storage if needed
            uploaded_steps = []
            for num, local_path in step_items:
                storage_path = f"{domain.handle}/steps/{slug}-step-{num}.jpg"
                up_res = upload_image_to_supabase(str(local_path), storage_path, domain.handle)
                if up_res.get("success") and up_res.get("public_url"):
                    uploaded_steps.append(
                        {
                            "step_number": num,
                            "image_url": up_res["public_url"],
                            "text": f"Paso {num}",
                        }
                    )

            if not uploaded_steps:
                continue

            # Update content with embedded images
            title = post.get("title") or slug
            content = post.get("content") or ""
            new_content = _embed_step_images_in_content(content, uploaded_steps, title)

            # Update recipe_schema with step images
            schema = post.get("recipe_schema") or {}
            if isinstance(schema, str):
                try:
                    schema = json.loads(schema)
                except Exception:
                    schema = {}

            if isinstance(schema, dict) and "recipeInstructions" in schema:
                instructions = schema.get("recipeInstructions")
                if isinstance(instructions, list):
                    step_map = {s["step_number"]: s["image_url"] for s in uploaded_steps}
                    for idx, inst in enumerate(instructions, 1):
                        if isinstance(inst, dict) and idx in step_map:
                            inst["image"] = step_map[idx]
                    schema["recipeInstructions"] = instructions

            update_payload = {
                "step_images": uploaded_steps,
                "content": new_content,
                "recipe_schema": schema,
            }

            try:
                patch_resp = requests.patch(
                    f"{url}/rest/v1/posts?slug=eq.{slug}",
                    headers=headers,
                    json=update_payload,
                    timeout=30,
                )

                if patch_resp.status_code in [200, 204]:
                    logger.info(
                        "[%s] Backfilled %d step images for '%s'",
                        domain.handle,
                        len(uploaded_steps),
                        slug,
                    )
                    updated_count += 1
                else:
                    logger.warning(
                        "[%s] Failed to patch '%s': %s",
                        domain.handle,
                        slug,
                        patch_resp.text[:120],
                    )
            except Exception as patch_err:
                logger.warning("[%s] Timeout/Error patching '%s': %s", domain.handle, slug, patch_err)

    logger.info("Backfill complete. Updated %d posts with step images.", updated_count)


if __name__ == "__main__":
    backfill_all_domains()
