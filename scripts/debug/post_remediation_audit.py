"""Post-remediation audit for RecetaGenial and RecetaDolce."""

from __future__ import annotations

import json
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any
import requests
from dotenv import load_dotenv

load_dotenv()
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from rankstein.domain import Domain, get_registry

registry = get_registry()
dolce_dom = registry.get("recetadolce")
genial_dom = registry.get("recetagenial")

PLACEHOLDER_MARKERS = [
    "ingrediente principal",
    "cocina la base",
    "base cremosa o caldo",
    "toque aromático",
    "toque aromatico",
    "integra el ingrediente principal",
    "ingrediente de calidad",
]

SAVORY_SLUGS = [
    "pollo-al-horno-recetas-tradicional",
    "salmon-horno-esparragos",
    "ragu-ternera-polenta-cremosa",
    "pollo-teriyaki-miel-cana-autor",
    "paella-de-marisco-tradicional-mediterraneo",
]

DOLCE_APPROVED_CATEGORIES = {
    "fresas-y-nata",
    "tartas-y-pasteles",
    "chocolates",
    "dulces-saludables",
    "Fresas y Nata",
    "Tartas y Pasteles",
    "Chocolates",
    "Dulces Saludables",
}

GENIAL_APPROVED_CATEGORIES = {
    "Aperitivos",
    "Arroces",
    "Carnes",
    "Pescados",
    "Ensaladas",
    "Postres",
    "aperitivos",
    "arroces",
    "carnes",
    "pescados",
    "ensaladas",
    "postres",
}

GENIAL_BUCKET = "hokcljsrrnjxzgdhjice"
DOLCE_BUCKET = "xjvmnmfczvwkjiasirsl"

def fetch_posts(domain: Domain) -> list[dict[str, Any]]:
    base = domain.supabase_url.rstrip("/")
    url = f"{base}/rest/v1/posts?select=*"
    key = domain.supabase_service_role_key.get_secret_value()
    resp = requests.get(url, headers={
        "apikey": key,
        "Authorization": f"Bearer {key}",
    }, timeout=30)
    resp.raise_for_status()
    return resp.json()

dolce_posts = fetch_posts(dolce_dom)
genial_posts = fetch_posts(genial_dom)

print("="*60)
print("POST-REMEDIATION AUDIT RESULTS")
print("="*60)
print(f"RecetaDolce Live Published Posts: {len(dolce_posts)}")
print(f"RecetaGenial Live Published Posts: {len(genial_posts)}")

def audit_brand(brand_name, posts, approved_cats, own_bucket, other_bucket, forbidden_slugs=[]):
    print(f"\n--- AUDITING {brand_name.upper()} ({len(posts)} posts) ---")
    placeholders_found = []
    cross_bucket_found = []
    unapproved_cats_found = []
    forbidden_slugs_found = []
    unescaped_newlines = []
    unparsed_pinterest_tags = []
    prompt_leaks = []

    for p in posts:
        slug = p.get("slug")
        raw = json.dumps(p, ensure_ascii=False)
        content = p.get("content") or ""
        cat = p.get("category") or ""

        # Placeholders
        for m in PLACEHOLDER_MARKERS:
            if m in raw.lower():
                placeholders_found.append((slug, m))
                break

        # Cross-bucket
        if other_bucket in raw:
            cross_bucket_found.append(slug)

        # Category
        if cat and cat not in approved_cats:
            unapproved_cats_found.append((slug, cat))

        # Forbidden slugs (e.g. savory on Dolce)
        if slug in forbidden_slugs:
            forbidden_slugs_found.append(slug)

        # Unescaped \n\n
        if r"\n\n" in content:
            unescaped_newlines.append(slug)

        # [PINTEREST_IFRAME]
        if "[PINTEREST_IFRAME]" in content:
            unparsed_pinterest_tags.append(slug)

        # prompt:
        if re.search(r"\bprompt:\s*", content, re.I):
            prompt_leaks.append(slug)

    print(f"  [OK] Placeholder artifacts: {len(placeholders_found)}")
    if placeholders_found:
        print(f"    Sample: {placeholders_found[:5]}")
    print(f"  [OK] Cross-brand storage references: {len(cross_bucket_found)}")
    if cross_bucket_found:
        print(f"    Sample: {cross_bucket_found}")
    print(f"  [OK] Unapproved categories: {len(unapproved_cats_found)}")
    if unapproved_cats_found:
        print(f"    Sample: {unapproved_cats_found[:5]}")
    print(f"  [OK] Forbidden slugs (savory): {len(forbidden_slugs_found)}")
    print(f"  [OK] Unescaped \\n\\n leaks: {len(unescaped_newlines)}")
    print(f"  [OK] Unparsed [PINTEREST_IFRAME] tags: {len(unparsed_pinterest_tags)}")
    print(f"  [OK] Prompt marker leaks: {len(prompt_leaks)}")

    return {
        "placeholders": len(placeholders_found),
        "cross_bucket": len(cross_bucket_found),
        "unapproved_cats": len(unapproved_cats_found),
        "forbidden_slugs": len(forbidden_slugs_found),
        "unescaped_newlines": len(unescaped_newlines),
        "unparsed_pinterest_tags": len(unparsed_pinterest_tags),
        "prompt_leaks": len(prompt_leaks),
    }

dolce_results = audit_brand("RecetaDolce", dolce_posts, DOLCE_APPROVED_CATEGORIES, DOLCE_BUCKET, GENIAL_BUCKET, SAVORY_SLUGS)
genial_results = audit_brand("RecetaGenial", genial_posts, GENIAL_APPROVED_CATEGORIES, GENIAL_BUCKET, DOLCE_BUCKET)

print("\n" + "="*60)
print("AUDIT SUMMARY:")
print(f"Dolce clean: {all(v == 0 for k, v in dolce_results.items() if k != 'unapproved_cats')}")
print(f"Genial clean: {all(v == 0 for k, v in genial_results.items() if k != 'unapproved_cats')}")
print("="*60)
