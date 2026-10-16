"""Verify RankStein -> OmniRoute -> TokenHarbor article generation path.

Safely calls _call_omniroute_for_article (no publish, no DB writes) with a
real Domain and a small Spanish source snippet, and reports whether the
gateway returns article JSON that passes the quality gate.

Usage:
    python scripts/debug/verify_omniroute_tokenharbor.py [--handle recetadolce] [--keyword "..."]
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from backend.scripts.turbo_articles import (
    _call_omniroute_for_article,
    _openrouter_article_quality_check,
)
from rankstein.domain import get_registry

SOURCE_SNIPPET = (
    "Receta de tarta de fresas y nata: 500 ml de nata para montar muy fría, "
    "250 g de fresas frescas, 100 g de azúcar, 1 base de bizcocho genovés de 24 cm, "
    "1 sobre de cuajada, 2 cucharaditas de extracto de vainilla. "
    "Montar la nata con el azúcar hasta que forme picos suaves. Triturar la mitad de las fresas "
    "con la cuajada y el extracto de vainilla; incorporar con movimientos envolventes a la nata. "
    "Colocar la base de bizcocho en el molde, verter la crema y alisar. "
    "Refrigerar al menos 4 horas. Decorar con las fresas restantes laminadas justo antes de servir. "
    "Conservar en nevera hasta 48 horas."
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--handle", default="recetadolce")
    parser.add_argument("--keyword", default="tarta de fresas y nata")
    args = parser.parse_args()

    registry = get_registry()
    try:
        domain = registry.get(args.handle)
    except KeyError:
        domain = registry.default
    print(f"Domain: {domain.handle} ({domain.domain}) niche={domain.niche}")
    print(f"Gateway URL: {os.environ.get('RANKSTEIN_OMNIROUTE_URL', '<unset>')}")
    print(f"Model: {os.environ.get('RANKSTEIN_OMNIROUTE_MODEL', '<unset>')}")
    print(f"API key set: {bool(os.environ.get('RANKSTEIN_OMNIROUTE_API_KEY'))}")
    print(f"Fallback enabled: {os.environ.get('RANKSTEIN_ENABLE_OMNIROUTE_FALLBACK', '1')}")
    print()

    article = asyncio.run(
        _call_omniroute_for_article(
            args.keyword,
            domain,
            source_material=SOURCE_SNIPPET,
        )
    )
    if not article:
        print("RESULT: FAILED - _call_omniroute_for_article returned None")
        return 1

    quality = _openrouter_article_quality_check(article)
    schema = article.get("recipe_schema") or {}
    ingredients = schema.get("recipeIngredient") or []
    instructions = schema.get("recipeInstructions") or []
    content = article.get("content", "")
    print("RESULT: SUCCESS")
    print(f"  quality gate passed: {quality}")
    print(f"  title: {article.get('title', '')!r}")
    print(f"  content chars: {len(content)}")
    print(f"  recipe_schema ingredients: {len(ingredients)}")
    print(f"  recipe_schema instructions: {len(instructions)}")
    print(f"  faq_schema entries: {len(article.get('faq_schema') or [])}")
    print(f"  category: {article.get('category', '')!r}")
    return 0 if (quality and content and len(ingredients) >= 6 and len(instructions) >= 6) else 2


if __name__ == "__main__":
    raise SystemExit(main())
