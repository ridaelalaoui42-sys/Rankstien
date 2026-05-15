"""Branding generator — colors, logo, and theme.json from a niche string.

The provisioner calls this module during ``add-domain`` to materialize:

- ``data/domains/<handle>/branding/theme.json``  — color tokens + font names
- ``data/domains/<handle>/branding/logo.png``    — 1024x1024 minimalist mark

No LLM is required for the palette lookup — it's a niche-keyword → color
mapping with a sane default. The logo IS generated via Pollinations.ai (free,
keyless) using the same pipeline as ``rankstein_mcp_server.create_hero_image_
pollinations``. Logo failures fall back to a Pillow text monogram so the
provisioner never blocks on a third-party outage.

Public API
----------
- ``palette_for(niche: str) -> Palette``
- ``generate_logo(niche, display_name, branding_dir, primary, accent) -> Path``
- ``write_theme_json(branding_dir, palette, logo_filename) -> Path``
- ``provision_branding(handle, niche, display_name, branding_dir) -> dict``
  (the convenience method the provisioner actually calls)
"""

from __future__ import annotations

import json
import logging
import urllib.parse
from dataclasses import dataclass
from pathlib import Path

import requests

logger = logging.getLogger("rankstein.branding")


# ───────────────────────────────────────────────────────────────────────────
# Palette: deterministic niche-keyword lookup
# ───────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Palette:
    """A 4-color palette with sensible foreground/background tokens.

    All values are #RRGGBB hex strings. ``primary`` is the brand-defining hue
    (used for buttons, links, logo accents). ``accent`` complements it (often
    used for CTA buttons, dividers). ``neutral_bg`` and ``neutral_fg`` form
    the body text contrast pair.
    """

    primary: str
    accent: str
    neutral_bg: str = "#FAFAF8"
    neutral_fg: str = "#1a1a1a"


# Niche-keyword → palette. Order matters for substring matching: more specific
# keywords come first. ``Palette`` values were picked for visual harmony, not
# trend-chasing — pairs that pass WCAG AA against neutral_bg/neutral_fg.
_PALETTE_LOOKUP: tuple[tuple[tuple[str, ...], Palette], ...] = (
    # Keto / low-carb / paleo — deep forest + warm gold
    (
        ("keto", "low-carb", "low carb", "paleo", "carnivore"),
        Palette(primary="#3D5A40", accent="#D4AF37"),
    ),
    # Desserts / sweets / pastry — warm pink + cream
    (
        ("dessert", "postres", "sweet", "pastry", "cake", "candy", "chocolate"),
        Palette(primary="#D67B7E", accent="#E8C39E"),
    ),
    # Seafood / pescados (NOT sushi — that goes to asian below)
    (
        ("seafood", "fish recipes", "pescados", "ocean", "marisco"),
        Palette(primary="#1F4E79", accent="#A8C5DA"),
    ),
    # Vegan / vegetarian / salad — sage + warm cream
    (
        ("vegan", "vegetarian", "salad", "ensalada", "plant-based", "raw"),
        Palette(primary="#6A8E5C", accent="#E8DCC4"),
    ),
    # BBQ / grill / smoked / meat — smoke charcoal + ember orange
    (
        ("bbq", "grill", "smoked", "meat", "carne", "steak", "ribs"),
        Palette(primary="#2A2A2A", accent="#E8703A"),
    ),
    # Mediterranean / Spanish / Italian — terracotta + olive
    (
        ("mediterranean", "spanish", "italian", "tapas", "español", "receta"),
        Palette(primary="#C67B3C", accent="#7A8B5C"),
    ),
    # Asian / wok / ramen / curry — cinnabar red + ink
    (
        ("asian", "wok", "ramen", "curry", "japanese", "korean", "thai", "chinese"),
        Palette(primary="#A22B22", accent="#1F1F1F"),
    ),
    # Breakfast / brunch / pancakes — warm honey + cream
    (
        ("breakfast", "brunch", "pancake", "waffle", "omelet"),
        Palette(primary="#E8A857", accent="#F3E0BC"),
    ),
)


_DEFAULT_PALETTE = Palette(primary="#D4AF37", accent="#1a1a1a")


def palette_for(niche: str) -> Palette:
    """Return a deterministic palette for the given niche string.

    Lookup is case-insensitive substring match. Falls back to the default
    "Receta Dolce" gold/charcoal pair if no niche keyword matches.
    """
    normalized = (niche or "").lower()
    for keywords, palette in _PALETTE_LOOKUP:
        if any(k in normalized for k in keywords):
            return palette
    return _DEFAULT_PALETTE


# ───────────────────────────────────────────────────────────────────────────
# Logo via Pollinations.ai (free, keyless), with Pillow text fallback
# ───────────────────────────────────────────────────────────────────────────


_LOGO_SIZE = 1024
_LOGO_MIN_BYTES = 5_000


def generate_logo(
    niche: str,
    display_name: str,
    branding_dir: Path,
    primary: str,
    accent: str,
    *,
    timeout_seconds: int = 90,
) -> Path:
    """Generate a 1024x1024 minimalist logo PNG. Returns the saved path.

    Order of attempts:
    1. Pollinations.ai with a niche-aware editorial prompt
    2. Pillow text-monogram fallback if Pollinations errors or returns junk
    """
    branding_dir.mkdir(parents=True, exist_ok=True)
    out = branding_dir / "logo.png"

    prompt = (
        f"minimalist editorial logo for a {niche} blog called {display_name}, "
        f"vector style, white background, {primary} accent, {accent} highlight, "
        "no text, clean, modern, magazine-quality, high-resolution"
    )
    encoded = urllib.parse.quote(prompt, safe="")
    url = f"https://image.pollinations.ai/prompt/{encoded}"
    params = {
        "width": _LOGO_SIZE,
        "height": _LOGO_SIZE,
        "nologo": "true",
        "model": "flux",
        "enhance": "true",
    }

    try:
        logger.info("Pollinations logo prompt: %s", prompt[:100])
        resp = requests.get(url, params=params, timeout=timeout_seconds, allow_redirects=True)
        resp.raise_for_status()
        data = resp.content
        if len(data) >= _LOGO_MIN_BYTES:
            out.write_bytes(data)
            logger.info("Logo saved (Pollinations): %s (%d bytes)", out, len(data))
            return out
        logger.warning(
            "Pollinations returned suspiciously small payload (%d bytes); using fallback",
            len(data),
        )
    except Exception as e:
        logger.warning("Pollinations logo failed: %s; using Pillow fallback", e)

    return _pillow_monogram_fallback(display_name, out, primary, accent)


def _pillow_monogram_fallback(display_name: str, out: Path, primary: str, accent: str) -> Path:
    """Last-resort logo: a 1024x1024 monogram circle with the brand initials."""
    from PIL import Image, ImageDraw, ImageFont

    img = Image.new("RGB", (_LOGO_SIZE, _LOGO_SIZE), color="#FFFFFF")
    draw = ImageDraw.Draw(img)
    # Filled circle in primary color
    margin = 80
    draw.ellipse(
        (margin, margin, _LOGO_SIZE - margin, _LOGO_SIZE - margin),
        fill=primary,
    )
    # Inner ring in accent
    draw.ellipse(
        (margin + 30, margin + 30, _LOGO_SIZE - margin - 30, _LOGO_SIZE - margin - 30),
        outline=accent,
        width=12,
    )
    # Initials
    initials = "".join(w[0].upper() for w in display_name.split() if w)[:2] or "RS"
    try:
        font = ImageFont.truetype("georgia.ttf", 380)
    except OSError:
        font = ImageFont.load_default(size=300)
    bbox = draw.textbbox((0, 0), initials, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    draw.text(
        ((_LOGO_SIZE - tw) // 2 - bbox[0], (_LOGO_SIZE - th) // 2 - bbox[1] - 30),
        initials,
        font=font,
        fill="#FFFFFF",
    )
    img.save(out, "PNG")
    logger.info("Logo saved (Pillow fallback): %s", out)
    return out


# ───────────────────────────────────────────────────────────────────────────
# theme.json
# ───────────────────────────────────────────────────────────────────────────


def write_theme_json(branding_dir: Path, palette: Palette, logo_filename: str = "logo.png") -> Path:
    """Write ``branding/theme.json`` with color tokens + font names."""
    theme = {
        "primary": palette.primary,
        "accent": palette.accent,
        "neutral_bg": palette.neutral_bg,
        "neutral_fg": palette.neutral_fg,
        "font_heading": "Georgia",
        "font_body": "Arial",
        "logo_path": logo_filename,
    }
    branding_dir.mkdir(parents=True, exist_ok=True)
    out = branding_dir / "theme.json"
    out.write_text(json.dumps(theme, indent=2), encoding="utf-8")
    logger.info("theme.json written: %s", out)
    return out


# ───────────────────────────────────────────────────────────────────────────
# One-shot convenience for the provisioner
# ───────────────────────────────────────────────────────────────────────────


def provision_branding(
    *,
    handle: str,
    niche: str,
    display_name: str,
    branding_dir: Path,
) -> dict:
    """Run the full branding provisioning step. Returns a summary dict
    suitable for embedding in the domain manifest."""
    palette = palette_for(niche)
    logo_path = generate_logo(niche, display_name, branding_dir, palette.primary, palette.accent)
    theme_path = write_theme_json(branding_dir, palette, logo_filename=logo_path.name)
    logger.info("Branding provisioned for %r: %s", handle, branding_dir)
    return {
        "handle": handle,
        "primary_color": palette.primary,
        "accent_color": palette.accent,
        "logo_path": str(logo_path),
        "theme_path": str(theme_path),
    }
