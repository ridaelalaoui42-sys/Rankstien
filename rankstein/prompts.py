"""Prompt builders for RankStein recipe content and image generation."""

from __future__ import annotations

import re
import unicodedata
from typing import Any

IMAGE_NEGATIVE_PROMPT = (
    "blurry, low resolution, distorted food, artificial plastic texture, extra limbs or hands, "
    "unreadable text, misspelled words, watermark, logo, brand name, fake URL, cluttered table, "
    "harsh flash, over-saturated colors, cropped main dish, duplicate plates, impossible ingredients"
)

DEFAULT_IMAGE_SCRAPE_BLOCKED_TERMS = [
    "outfit",
    "moda",
    "nails",
    "unas",
    "uñas",
    "makeup",
    "maquillaje",
    "hair",
    "cabello",
    "tattoo",
    "decor",
    "wedding",
    "boda",
    "meme",
    "quote",
    "frase",
    "wallpaper",
    "fitness",
    "workout",
    "gym",
    "before after",
    "meal plan",
    "diet plan",
]

IMAGE_SCRAPE_STOPWORDS = {
    "con",
    "sin",
    "para",
    "por",
    "las",
    "los",
    "una",
    "uno",
    "unas",
    "unos",
    "del",
    "de",
    "la",
    "el",
    "al",
    "estilo",
    "receta",
    "recetas",
    "facil",
    "faciles",
    "casera",
    "casero",
    "rapida",
    "rapido",
}

GENERIC_IMAGE_SCRAPE_TERMS = {
    "aire",
    "aperitivo",
    "aperitivos",
    "asada",
    "asado",
    "comida",
    "cocina",
    "ensalada",
    "ensaladas",
    "freidora",
    "frita",
    "frito",
    "horno",
    "olla",
    "plato",
    "postre",
    "postres",
    "receta",
    "recetas",
    "tarta",
    "tartas",
}

# Words that make an article title appealing but do not identify the food in
# the photograph.  Keeping these out of the scrape identity prevents long-tail
# editorial titles (especially seasonal ones) from turning into weak Pinterest
# queries such as "cremosa fin ano".
IMAGE_SCRAPE_NOISE_TERMS = {
    "ano",
    "anos",
    "celebracion",
    "celebraciones",
    "clasica",
    "clasico",
    "cremosa",
    "cremoso",
    "crujiente",
    "crujientes",
    "deliciosa",
    "delicioso",
    "especial",
    "fiesta",
    "fiestas",
    "fin",
    "irresistible",
    "navidad",
    "navidena",
    "navideno",
    "nuevo",
    "perfecta",
    "perfecto",
    "tradicional",
    "viral",
}

# Common recipe heads are useful in a search query but usually should not be
# the required ingredient match.  The latter is carried by ``core_terms``.
IMAGE_SCRAPE_DISH_TERMS = GENERIC_IMAGE_SCRAPE_TERMS | {
    "arroz",
    "bizcocho",
    "carne",
    "croqueta",
    "croquetas",
    "galleta",
    "galletas",
    "helado",
    "pasta",
    "pastel",
    "pizza",
    "pollo",
    "salsa",
    "sopa",
    "tortilla",
}

RECIPE_KEYWORD_TERMS = {
    "aceituna",
    "aceitunas",
    "aperitivo",
    "aperitivos",
    "arroz",
    "bacalao",
    "berenjena",
    "bizcocho",
    "bocados",
    "calabacin",
    "carne",
    "cena",
    "cenas",
    "chocolate",
    "cocina",
    "croqueta",
    "croquetas",
    "ensalada",
    "fresa",
    "fresas",
    "galleta",
    "galletas",
    "garbanzo",
    "garbanzos",
    "helado",
    "huevo",
    "huevos",
    "lenteja",
    "lentejas",
    "limon",
    "mascarpone",
    "paella",
    "pasta",
    "pastel",
    "pasteles",
    "pescado",
    "pimiento",
    "pimientos",
    "pistacho",
    "pizza",
    "pollo",
    "postre",
    "postres",
    "queso",
    "receta",
    "recetas",
    "salmon",
    "salsa",
    "sopa",
    "tarta",
    "tartas",
    "tomate",
    "tortilla",
    "tostas",
    "ventresca",
}

NON_RECIPE_KEYWORD_TERMS = {
    "aesthetic",
    "colors",
    "colores",
    "colour",
    "decor",
    "decorated",
    "decoracion",
    "fashion",
    "hair",
    "makeup",
    "nails",
    "outfit",
    "tattoo",
    "wallpaper",
    "wedding",
}


ASSET_RATIOS = {
    "hero": "16:9",
    "inline": "4:3",
    "pinterest_pin": "2:3",
    "og": "1200x630",
}


def _domain_value(domain: Any, name: str, fallback: str = "") -> str:
    value = getattr(domain, name, fallback) if domain is not None else fallback
    return str(value or fallback).strip()


def _domain_brand_notes(domain: Any) -> str:
    if domain is None:
        return "RankStein recipe site; Spanish food audience; polished but practical."
    display = _domain_value(domain, "display_name", _domain_value(domain, "handle", "RankStein"))
    niche = _domain_value(domain, "niche", "Spanish recipes")
    return f"{display}; niche: {niche}; Spanish food audience; polished but practical."


def _repair_mojibake(value: str) -> str:
    text = str(value or "")
    for _ in range(2):
        if not any(marker in text for marker in ("Ã", "Â", "â")):
            break
        try:
            repaired = text.encode("latin1").decode("utf-8")
        except UnicodeError:
            break
        if repaired == text:
            break
        text = repaired
    return text


def _ascii_search_text(value: str) -> str:
    """Normalize generated scraper text for stable CLI and URL search handling."""

    normalized = unicodedata.normalize("NFKD", _repair_mojibake(value))
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii")
    return re.sub(r"\s+", " ", ascii_text).strip()


def _scrape_tokens(value: str) -> list[str]:
    normalized = _ascii_search_text(value).lower()
    return [
        tok
        for tok in re.split(r"[^a-z0-9]+", normalized)
        if len(tok) >= 3 and tok not in IMAGE_SCRAPE_STOPWORDS
    ]


def is_recipe_aware_keyword(keyword: str, *, domain: Any = None) -> bool:
    """Reject scraped UI/design phrases before they can become recipe work."""

    normalized = _ascii_search_text(keyword).lower()
    if re.search(r"\bwith\b.+\bon top\b", normalized):
        return False
    tokens = set(_scrape_tokens(keyword))
    if not tokens or tokens & NON_RECIPE_KEYWORD_TERMS:
        return False
    if len(tokens) == 1 and tokens <= {"chocolate", "pastel", "postre", "tarta"}:
        return False

    recipe_terms = set(RECIPE_KEYWORD_TERMS)
    if domain is not None:
        recipe_terms.update(_scrape_tokens(_domain_value(domain, "niche")))
        categories = getattr(domain, "categories", []) or []
        for category in categories if isinstance(categories, (list, tuple)) else [categories]:
            recipe_terms.update(_scrape_tokens(str(category)))

    return bool(tokens & recipe_terms)


def recipe_alt_text(keyword: str, *, asset_type: str = "hero") -> str:
    dish = (keyword or "receta casera").strip()
    if asset_type == "pinterest_pin":
        return f"Pin vertical de la receta {dish} con el plato terminado como protagonista."
    if asset_type == "inline":
        return f"Imagen de apoyo de {dish} durante la preparacion de la receta."
    return f"Plato terminado de {dish} servido de forma apetecible y realista."


def build_recipe_image_prompt(
    keyword: str,
    *,
    domain: Any = None,
    asset_type: str = "hero",
    category: str = "",
    destination_url: str = "",
    account_handle: str = "",
    overlay_concept: str = "",
) -> str:
    """Build an executable visual prompt following the RankStein image contract."""

    asset = asset_type if asset_type in ASSET_RATIOS else "hero"
    ratio = ASSET_RATIOS[asset]
    dish = (keyword or "receta espanola casera").strip()
    category_note = f" Category: {category.strip()}." if category else ""
    account_note = f" Pinterest account handle: {account_handle.strip()}." if account_handle else ""
    url_note = f" Destination URL for metadata only: {destination_url.strip()}." if destination_url else ""
    overlay_note = (
        f" Reserve clean negative space for this short overlay concept: {overlay_concept.strip()}."
        if overlay_concept
        else ""
    )

    if asset == "pinterest_pin":
        composition = (
            "Vertical 2:3 Pinterest food image, visual-first composition maximizing food visibility (>90%), "
            "finished dish large in frame with intense appetite appeal, macro textures (crispy, molten, creamy, or glistening), "
            "warm natural side lighting, one clear hook angle, reserved clean space for a subtle downstream text overlay, no rendered URL, "
            "and enough edge margin for safe mobile cropping."
        )
    elif asset == "inline":
        composition = (
            "Inline recipe support image, one clear cooking state or serving detail from this exact recipe, "
            "no multi-step collage, natural kitchen context kept secondary."
        )
    elif asset == "og":
        composition = (
            "Open Graph food image, finished dish centered with enough margin for responsive cropping, "
            "website-share friendly composition, readable at small preview sizes."
        )
    else:
        composition = (
            "Hero image for a recipe article, finished dish as the primary subject, 16:9 landscape framing, "
            "sharp and inspectable on a food blog, with the whole plated recipe visible."
        )

    return (
        f"Photorealistic editorial food photography of the finished dish: {dish}. "
        f"{composition} Aspect ratio: {ratio}.{category_note} "
        "Use realistic Spanish recipe styling, natural side window light, believable shadows, "
        "clean plate or rustic ceramic, appetizing texture, plausible garnish, and 1-2 relevant props. "
        "Show one finished, edible dish that clearly matches the recipe name, ingredients, cooking method, "
        "and category. Avoid random ingredient piles, hands, utensils blocking the plate, impossible plating, "
        "AI-perfect symmetry, fake steam, plastic gloss, and generic stock-food substitutions. "
        "The food must be specific enough that a reader can recognize the intended recipe immediately. "
        f"Brand context: {_domain_brand_notes(domain)}.{overlay_note}{account_note}{url_note} "
        "No embedded text, no logos, no watermark, no fake UI, no raw-ingredient montage unless explicitly requested. "
        f"Avoid: {IMAGE_NEGATIVE_PROMPT}."
    )


def build_recipe_visual_brief(
    keyword: str,
    *,
    domain: Any = None,
    asset_type: str = "hero",
    category: str = "",
    destination_url: str = "",
    account_handle: str = "",
    overlay_concept: str = "",
) -> dict[str, str]:
    """Return the structured visual brief used by agents and dashboards."""

    asset = asset_type if asset_type in ASSET_RATIOS else "hero"
    return {
        "asset_type": asset,
        "domain_handle": _domain_value(domain, "handle", ""),
        "keyword": (keyword or "").strip(),
        "category": category.strip(),
        "aspect_ratio": ASSET_RATIOS[asset],
        "prompt": build_recipe_image_prompt(
            keyword,
            domain=domain,
            asset_type=asset,
            category=category,
            destination_url=destination_url,
            account_handle=account_handle,
            overlay_concept=overlay_concept,
        ),
        "negative_prompt": IMAGE_NEGATIVE_PROMPT,
        "overlay_text": overlay_concept.strip(),
        "alt_text": recipe_alt_text(keyword, asset_type=asset),
        "brand_notes": _domain_brand_notes(domain),
        "destination_url": destination_url.strip(),
    }


def recipe_generation_visual_requirements(keyword: str, domain: Any) -> str:
    """Prompt appendix for LLM article JSON generation."""

    hero = build_recipe_visual_brief(keyword, domain=domain, asset_type="hero")
    pin = build_recipe_visual_brief(
        keyword,
        domain=domain,
        asset_type="pinterest_pin",
        overlay_concept="guardar receta",
    )
    return (
        "VISUAL BRIEF REQUIREMENTS:\n"
        "  hero_image_prompt (str): Use this exact level of specificity for the final dish hero image. "
        "The prompt must identify the finished recipe, visible texture, plating, garnish, light, crop, "
        "and at least one dish-specific visual cue from the actual ingredients. "
        f"Must include: {hero['prompt']}\n"
        "  pinterest_pin_prompt (str): Vertical 2:3 prompt for the same finished dish, with safe negative space "
        "for later overlay text and no rendered text inside the generated image. "
        f"Must include: {pin['prompt']}\n"
        f"  image_negative_prompt (str): {IMAGE_NEGATIVE_PROMPT}\n"
        "  image_alt must be Spanish alt text describing the finished dish, not a keyword list.\n"
    )


def build_recipe_image_scrape_brief(
    keyword: str,
    *,
    domain: Any = None,
    category: str = "",
    locale: str = "es",
) -> dict[str, Any]:
    """Build the generated scrape brief passed into Pinterest image scraping."""

    keyword_text = _ascii_search_text(keyword or "").lower()
    keyword_terms = _scrape_tokens(keyword_text)
    identity_terms = [term for term in keyword_terms if term not in IMAGE_SCRAPE_NOISE_TERMS]
    core_terms = [term for term in identity_terms if term not in GENERIC_IMAGE_SCRAPE_TERMS]
    if not core_terms:
        core_terms = identity_terms

    dish_term = next((term for term in identity_terms if term in IMAGE_SCRAPE_DISH_TERMS), "")
    focus_terms = [term for term in core_terms if term != dish_term][:2]
    if dish_term and focus_terms:
        normalized_title = f" {_ascii_search_text(keyword or '').lower()} "
        first_focus = re.escape(focus_terms[0])
        uses_de = bool(re.search(rf"\bde(?:\s+[a-z0-9]+){{0,2}}\s+{first_focus}\b", normalized_title))
        connector = " de " if uses_de else " "
        search_identity = f"{dish_term}{connector}{' '.join(focus_terms)}"
    elif identity_terms:
        search_identity = " ".join(identity_terms[:4])
    else:
        search_identity = keyword_text

    # Cooking constraints are part of the dish identity, not incidental title
    # noise. Keep them in every generated query, before it reaches the scraper.
    dish_modifier = "sin horno" if re.search(r"\bsin\s+horno\b", keyword_text) else ""
    if dish_modifier and dish_modifier not in search_identity:
        search_identity = f"{search_identity} {dish_modifier}".strip()

    terms = list(identity_terms)
    if category:
        terms.extend(term for term in _scrape_tokens(category) if term not in IMAGE_SCRAPE_NOISE_TERMS)
    display = _domain_value(domain, "display_name", "")
    compact_terms = " ".join(part for part in (dish_term, *focus_terms) if part)
    if dish_modifier and dish_modifier not in compact_terms:
        compact_terms = f"{compact_terms} {dish_modifier}".strip()
    query_variants = [
        search_identity,
        compact_terms,
        f"receta {search_identity}".strip(),
        f"{search_identity} ingredientes".strip(),
        f"{search_identity} paso a paso".strip(),
    ]
    deduplicated_queries = list(dict.fromkeys(item for item in query_variants if item))

    return {
        "keyword": (keyword or "").strip(),
        "search_query": search_identity,
        "search_queries": deduplicated_queries,
        "core_terms": sorted(set(core_terms)),
        "min_core_matches": min(2, len(set(core_terms))),
        "expected_terms": sorted({term.strip().lower() for term in terms if len(term.strip()) >= 3}),
        "blocked_terms": DEFAULT_IMAGE_SCRAPE_BLOCKED_TERMS,
        "locale": locale,
        "domain_handle": _domain_value(domain, "handle", ""),
        "brand_notes": display or _domain_brand_notes(domain),
    }
