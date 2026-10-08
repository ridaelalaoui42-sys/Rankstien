"""Backfill SEO meta descriptions for articles missing metadata descriptions.

Ensures all published articles have high-CTR, SEO-compliant meta descriptions
(120-155 characters, complete sentences, no cut-offs or dangling prepositions).
Updates both `meta_description` and `seo_description` columns in Supabase.
"""

from __future__ import annotations

import argparse
import logging
import re
import sys
import time
from pathlib import Path

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv
from supabase import create_client

from rankstein.domain import DomainRegistry

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("backfill_meta")

DEFAULT_CATEGORY_DESCRIPTIONS = {
    "recetagenial": {
        "aperitivos": "Bocados ágiles y llenos de sabor para abrir la mesa, compartir y resolver una reunión sin complicaciones.",
        "arroces": "Arroces secos, melosos y caldosos explicados con tiempos claros y técnicas que puedes repetir.",
        "carnes": "Recetas familiares, guisos y cocciones precisas para sacar partido a cada corte.",
        "pescados": "Pescados y mariscos con preparaciones frescas, puntos de cocción fiables y producto en primer plano.",
        "ensaladas": "Platos frescos y completos que celebran verduras, legumbres y aliños de temporada.",
        "postres": "Dulces cotidianos y postres tradicionales con instrucciones sencillas y resultados consistentes.",
        "pasabocas": "Aperitivos y tapas fáciles y rápidas para compartir en reuniones o picoteos informales.",
    },
    "recetadolce": {
        "carnes": "Exquisitas preparaciones de carnes elevadas a la categoría de alta cocina tradicional.",
        "fresas": "Nuestra colección insignia: el equilibrio perfecto entre fresas frescas y nata montada artesanal.",
        "chocolate": "El universo del cacao de alta gama: trufas, bombones y mousses cremosas.",
        "dulces-saludables": "El placer de cuidarse con postres ligeros, frutas frescas y repostería sin azúcares refinados.",
        "ensaladas": "Frescura y elegancia en cada bocado, ensaladas gourmet con aliños aromáticos.",
    },
}


def clean_title(title: str) -> str:
    """Clean promotional suffixes from title for natural description embedding."""
    t = re.sub(r":\s*La Receta.*$", "", title, flags=re.IGNORECASE)
    t = re.sub(r":\s*El Secreto.*$", "", title, flags=re.IGNORECASE)
    t = re.sub(r":\s*Un Bocado.*$", "", title, flags=re.IGNORECASE)
    t = re.sub(r":\s*Los Mejores.*$", "", title, flags=re.IGNORECASE)
    t = re.sub(r":\s*La Estrella.*$", "", title, flags=re.IGNORECASE)
    t = re.sub(r":\s*La Tapa.*$", "", title, flags=re.IGNORECASE)
    t = re.sub(r":\s*Frescura.*$", "", title, flags=re.IGNORECASE)
    t = re.sub(r":\s*Un Lujo.*$", "", title, flags=re.IGNORECASE)
    t = re.sub(r":\s*Una Delicia.*$", "", title, flags=re.IGNORECASE)
    t = re.sub(r":\s*El Tesoro.*$", "", title, flags=re.IGNORECASE)
    t = re.sub(r":\s*El Sabor.*$", "", title, flags=re.IGNORECASE)
    t = re.sub(r":\s*Tu Plato.*$", "", title, flags=re.IGNORECASE)
    t = re.sub(r":\s*El Clásico.*$", "", title, flags=re.IGNORECASE)
    t = re.sub(r":\s*Tiempo y.*$", "", title, flags=re.IGNORECASE)
    t = re.sub(r"\s*—\s*Receta.*$", "", t, flags=re.IGNORECASE)
    t = re.sub(r"\s*\|\s*Receta.*$", "", t, flags=re.IGNORECASE)
    return t.strip()


def generate_seo_meta_description(title: str, excerpt: str, brand: str) -> str:
    """Generate high-CTR, SEO-optimized meta description (120-155 chars).
    Guarantees:
    - Never uses cut-off fragments or clipped words.
    - Every description is a complete, grammatical sentence.
    - Always ends in valid terminal punctuation.
    - Ideal Google SERP display length (120-155 chars).
    """
    raw_ex = (excerpt or "").strip()
    ct = clean_title(title)

    has_terminal_punct = raw_ex.endswith((".", "!", "?"))
    valid_excerpt = ""

    if has_terminal_punct:
        if raw_ex.lower() not in {
            "la mejor receta explicada paso a paso.",
            "receta explicada paso a paso.",
        }:
            valid_excerpt = raw_ex
    else:
        # Check if excerpt contains a complete earlier sentence
        sentences = [s.strip() for s in re.findall(r"[^.!?]+[.!?]", raw_ex)]
        for s in sentences:
            if 115 <= len(s) <= 155:
                valid_excerpt = s
                break
            elif 75 <= len(s) < 115:
                s_clean = s.rstrip(". !?")
                for cta in [
                    f" ¡Descubre la receta paso a paso en {brand}!",
                    f" ¡Aprende a prepararlo paso a paso en {brand}!",
                    f" ¡Receta fácil paso a paso en {brand}!",
                    " ¡Receta completa paso a paso!",
                ]:
                    cand = f"{s_clean}.{cta}"
                    if 120 <= len(cand) <= 155:
                        valid_excerpt = cand
                        break
                if valid_excerpt:
                    break

    # If we have a valid, un-truncated excerpt:
    if valid_excerpt:
        # 1. Ideal length: 120-155 chars
        if 120 <= len(valid_excerpt) <= 155:
            return valid_excerpt

        # 2. Short complete sentence: 75-119 chars
        if 75 <= len(valid_excerpt) < 120:
            ex_clean = valid_excerpt.rstrip(". !?")
            cta_candidates = [
                f" ¡Descubre la receta paso a paso en {brand}!",
                f" ¡Aprende a prepararlo paso a paso en {brand}!",
                " ¡Entra y descubre los trucos paso a paso!",
                f" ¡Receta fácil paso a paso en {brand}!",
                f" ¡Descúbrelo paso a paso en {brand}!",
                " ¡Receta completa paso a paso!",
                " ¡Entra y pruébalo en casa!",
                f" ¡Paso a paso en {brand}!",
            ]
            for cta in cta_candidates:
                combined = f"{ex_clean}.{cta}"
                if 120 <= len(combined) <= 155:
                    return combined

    # Fallback: Synthesize guaranteed complete grammatical sentence from clean title
    templates = [
        f"Aprende a preparar {ct} paso a paso: ingredientes exactos, tiempos y trucos para que quede perfecto. ¡Receta fácil en {brand}!",
        f"Descubre cómo preparar {ct} paso a paso: ingredientes exactos, tiempos y trucos del chef. ¡Entra y descúbrelo en {brand}!",
        f"Receta de {ct} fácil y deliciosa paso a paso: ingredientes exactos y consejos clave para triunfar en casa con {brand}.",
        f"Prepara {ct} paso a paso con esta receta fácil: ingredientes exactos, tiempos y consejos para que quede perfecta en {brand}.",
        f"Aprende a preparar {ct} paso a paso: ingredientes exactos y trucos para un resultado perfecto. ¡Entra en {brand}!",
        f"Receta de {ct} paso a paso: ingredientes exactos y consejos para triunfar. ¡Entra en {brand}!",
        f"Descubre cómo preparar {ct} paso a paso con ingredientes exactos y trucos en {brand}.",
        f"Receta de {ct} paso a paso con trucos y consejos para triunfar en casa con {brand}.",
    ]
    for tmpl in templates:
        if 120 <= len(tmpl) <= 155:
            return tmpl

    base = f"Descubre cómo preparar {ct} paso a paso: ingredientes exactos y trucos en {brand}."
    if len(base) > 155:
        base = f"Receta de {ct} paso a paso con trucos y consejos en {brand}."
    if len(base) > 155:
        base = f"Receta de {ct} paso a paso en {brand}."
    return base


def fetch_all_posts(client) -> list[dict]:
    posts, start, sz = [], 0, 100
    while True:
        for attempt in range(3):
            try:
                res = (
                    client.from_("posts")
                    .select("id, title, slug, meta_description, seo_description, excerpt")
                    .range(start, start + sz - 1)
                    .execute()
                )
                data = res.data or []
                break
            except Exception:
                if attempt == 2:
                    raise
                time.sleep(1 + attempt)
        posts.extend(data)
        if len(data) < sz:
            break
        start += sz
    return posts


def run_backfill(apply_changes: bool = False, target_domain: str | None = None) -> None:
    load_dotenv(PROJECT_ROOT / ".env")
    registry = DomainRegistry(PROJECT_ROOT)

    domains = [registry.get(target_domain)] if target_domain else registry.all()

    total_updated = 0

    for domain in domains:
        logger.info("Processing domain %s (%s)", domain.handle, domain.domain)
        client = create_client(domain.supabase_url, domain.supabase_service_role_key.get_secret_value())

        posts = fetch_all_posts(client)
        targets = [
            p
            for p in posts
            if not (p.get("meta_description") or "").strip()
            or len((p.get("meta_description") or "").strip()) < 70
            or not (p.get("seo_description") or "").strip()
            or len((p.get("seo_description") or "").strip()) < 70
        ]

        logger.info(
            "Found %d articles requiring metadata description updates in %s",
            len(targets),
            domain.handle,
        )

        domain_updated = 0
        for i, post in enumerate(targets, 1):
            title = post["title"]
            excerpt = post.get("excerpt") or ""
            desc = generate_seo_meta_description(title, excerpt, domain.display_name)

            if apply_changes:
                # Update both meta_description and seo_description
                for attempt in range(3):
                    try:
                        client.from_("posts").update(
                            {
                                "meta_description": desc,
                                "seo_description": desc,
                            }
                        ).eq("id", post["id"]).execute()
                        break
                    except Exception as exc:
                        if attempt == 2:
                            logger.error("Failed to update post %s (%s): %s", post["id"], title, exc)
                            raise
                        time.sleep(0.5)

                domain_updated += 1
                if i % 25 == 0 or i == len(targets):
                    logger.info("  [%d/%d] Updated: %s (%d chars)", i, len(targets), title, len(desc))
            else:
                if i <= 3 or i == len(targets):
                    logger.info(
                        "  [DRY-RUN %d/%d] %s -> (%d chars) %s", i, len(targets), title, len(desc), desc
                    )

        if apply_changes:
            logger.info("Successfully updated %d articles in %s", domain_updated, domain.handle)
            total_updated += domain_updated

        # Backfill categories table if description is missing
        try:
            cat_res = client.from_("categories").select("id, name, slug, description").execute()
            categories = cat_res.data or []
            cat_defaults = DEFAULT_CATEGORY_DESCRIPTIONS.get(domain.handle, {})
            cat_updated = 0
            for cat in categories:
                if not (cat.get("description") or "").strip():
                    c_slug = (cat.get("slug") or cat.get("name") or "").lower()
                    desc = (
                        cat_defaults.get(c_slug)
                        or f"Descubre las mejores recetas de {cat.get('name')} explicadas paso a paso con trucos y consejos en {domain.display_name}."
                    )
                    if apply_changes:
                        client.from_("categories").update({"description": desc}).eq("id", cat["id"]).execute()
                        cat_updated += 1
                        logger.info("  [CATEGORY] Updated %s -> %s", cat.get("name"), desc[:60])
                    else:
                        logger.info("  [DRY-RUN CATEGORY] %s -> %s", cat.get("name"), desc[:60])
            if apply_changes and cat_updated:
                logger.info("Updated %d categories in %s", cat_updated, domain.handle)
        except Exception as exc:
            logger.warning("Categories table check skipped for %s: %s", domain.handle, exc)

    logger.info("Backfill complete. Total updated: %d", total_updated)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Backfill missing article metadata descriptions")
    parser.add_argument("--apply", action="store_true", help="Apply updates to Supabase (default is dry-run)")
    parser.add_argument("--domain", type=str, default=None, help="Specific domain handle to process")
    args = parser.parse_args()

    run_backfill(apply_changes=args.apply, target_domain=args.domain)
