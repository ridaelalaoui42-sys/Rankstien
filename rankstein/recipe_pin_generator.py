"""Pinterest Recipe Pin Generator — Multi-Variant & Recipe-Aware.

Supports two official ingredients pin variants and recipe-aware typography/colors:
1. `bright_infographic`: Bright culinary paper aesthetic matching the 2026 viral
   reference standard with circular hero bowl, 3-stat metrics card (clock, flame, people),
   INGREDIENTES ribbon with card, PASO A PASO ribbon with 4 macro-cropped step cards,
   Chef Tip box with lightbulb, middle appetizing callout, thumbnail preview, and branding bar.
2. `full_bleed`: Cinematic full-bleed food hero photography with top floating ivory card,
   dark bottom vignette with highlight backplates, and 2-column ingredients + preparation.

Dependencies: Pillow only.
"""

from __future__ import annotations

import logging
import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont

logger = logging.getLogger("rankstein.recipe_pin")

PIN_W, PIN_H = 1000, 1500
ASSETS_DIR = Path(__file__).resolve().parent / "assets"
FONTS_DIR = ASSETS_DIR / "fonts"
ICONS_DIR = ASSETS_DIR / "icons"
RIBBONS_DIR = ASSETS_DIR / "ribbons"
BADGES_DIR = ASSETS_DIR / "badges"
TEXTURES_DIR = ASSETS_DIR / "textures"
WIN_FONTS = Path("C:/Windows/Fonts")

_FONT_CACHE: dict[tuple[str, int], ImageFont.FreeTypeFont] = {}


def get_font(font_name: str, size: int) -> ImageFont.FreeTypeFont:
    """Load a TrueType font with caching, variable font weight enforcement, and fallbacks."""
    key = (font_name, size)
    if key in _FONT_CACHE:
        return _FONT_CACHE[key]

    for candidate in [FONTS_DIR / font_name, WIN_FONTS / font_name]:
        if candidate.exists():
            try:
                f = ImageFont.truetype(str(candidate), size)
                try:
                    var_names = f.get_variation_names()
                    if var_names:
                        fn_lower = font_name.lower()
                        if "black" in fn_lower:
                            f.set_variation_by_name("Black")
                        elif "extrabold" in fn_lower:
                            f.set_variation_by_name("ExtraBold")
                        elif "bold" in fn_lower:
                            f.set_variation_by_name("Bold")
                        elif "semibold" in fn_lower:
                            f.set_variation_by_name("SemiBold")
                        elif "medium" in fn_lower:
                            f.set_variation_by_name("Medium")
                        elif "regular" in fn_lower:
                            f.set_variation_by_name("Regular")
                        else:
                            f.set_variation_by_name("Bold")
                except (AttributeError, OSError, ValueError) as exc:
                    logger.debug("Failed setting variation on %s: %s", font_name, exc)
                _FONT_CACHE[key] = f
                return f
            except (OSError, ValueError) as exc:
                logger.debug("Could not load font candidate %s: %s", candidate, exc)

    for alt in ["Poppins-Regular.ttf", "Poppins-SemiBold.ttf", "arial.ttf"]:
        alt_p = FONTS_DIR / alt
        if alt_p.exists():
            try:
                f = ImageFont.truetype(str(alt_p), size)
                _FONT_CACHE[key] = f
                return f
            except (OSError, ValueError) as exc:
                logger.debug("Could not load fallback font %s: %s", alt_p, exc)

    f = ImageFont.load_default(size=size)
    _FONT_CACHE[key] = f
    return f


def _font(role: str, size: int) -> ImageFont.FreeTypeFont:
    """Backwards-compatible role-based font accessor."""
    role_map = {
        "title": "DMSerifDisplay-Regular.ttf",
        "section_header": "DMSerifDisplay-Regular.ttf",
        "subtitle": "Poppins-Regular.ttf",
        "header": "Montserrat-Bold.ttf",
        "body": "Poppins-Regular.ttf",
        "body_bold": "Poppins-SemiBold.ttf",
        "script": "Pacifico-Regular.ttf",
        "italic": "DancingScript-Bold.ttf",
        "brand": "Poppins-SemiBold.ttf",
        "cta": "Montserrat-Bold.ttf",
    }
    return get_font(role_map.get(role, "Poppins-Regular.ttf"), size)


# ── Asset Loaders & Visual Compositing Utilities ───────────────────────────


def load_icon(name: str, max_w: int, max_h: int) -> Image.Image:
    p = ICONS_DIR / f"{name}.png"
    im = Image.open(p).convert("RGBA")
    im.thumbnail((max_w, max_h), Image.Resampling.LANCZOS)
    return im


def load_badge(name: str, size: int) -> Image.Image:
    p = BADGES_DIR / f"{name}.png"
    im = Image.open(p).convert("RGBA")
    return im.resize((size, size), Image.Resampling.LANCZOS)


def draw_card_with_shadow(
    canvas: Image.Image,
    box: tuple,
    radius: int,
    fill: tuple,
    outline: tuple | None = None,
    width: int = 1,
    shadow_blur: int = 14,
    shadow_alpha: int = 45,
    shadow_offset: tuple = (0, 6),
) -> None:
    x1, y1, x2, y2 = box
    w = x2 - x1
    h = y2 - y1

    pad = shadow_blur * 2 + 10
    s_w = w + pad * 2
    s_h = h + pad * 2
    shadow_layer = Image.new("RGBA", (s_w, s_h), (0, 0, 0, 0))
    s_draw = ImageDraw.Draw(shadow_layer)
    s_draw.rounded_rectangle(
        (pad, pad, pad + w, pad + h),
        radius=radius,
        fill=(15, 12, 10, shadow_alpha),
    )
    shadow_layer = shadow_layer.filter(ImageFilter.GaussianBlur(shadow_blur))
    canvas.paste(
        shadow_layer,
        (x1 - pad + shadow_offset[0], y1 - pad + shadow_offset[1]),
        shadow_layer,
    )

    draw = ImageDraw.Draw(canvas, "RGBA")
    draw.rounded_rectangle((x1, y1, x2, y2), radius=radius, fill=fill, outline=outline, width=width)


def paste_with_shadow(
    canvas: Image.Image,
    img: Image.Image,
    pos: tuple,
    shadow_blur: int = 8,
    shadow_alpha: int = 75,
    shadow_offset: tuple = (0, 4),
) -> None:
    w, h = img.size
    pad = shadow_blur * 2 + 8
    s_w = w + pad * 2
    s_h = h + pad * 2

    shadow_layer = Image.new("RGBA", (s_w, s_h), (0, 0, 0, 0))
    alpha = img.split()[-1]
    black_sil = Image.new("RGBA", (w, h), (10, 8, 6, shadow_alpha))
    black_sil.putalpha(alpha)
    shadow_layer.paste(black_sil, (pad, pad), black_sil)
    shadow_layer = shadow_layer.filter(ImageFilter.GaussianBlur(shadow_blur))

    canvas.paste(
        shadow_layer,
        (pos[0] - pad + shadow_offset[0], pos[1] - pad + shadow_offset[1]),
        shadow_layer,
    )
    canvas.paste(img, pos, img)


def create_luxury_arched_ribbon(
    ribbon_name: str,
    text: str,
    target_width: int,
    font_name: str = "DMSerifDisplay-Regular.ttf",
    font_size: int = 48,
    letter_spacing_px: float = 6.0,
    text_color: tuple = (255, 255, 255, 255),
    shadow_color: tuple = (10, 8, 5, 240),
    bold_stroke: int = 2,
    apex_y: float = 52.0,
) -> Image.Image:
    p = RIBBONS_DIR / f"{ribbon_name}.png"
    im = Image.open(p).convert("RGBA")
    orig_w, orig_h = im.size

    font = get_font(font_name, font_size)

    cx = orig_w / 2.0
    R = 1040.0
    cy = apex_y + R

    dummy = Image.new("RGBA", (10, 10), (0, 0, 0, 0))
    d_draw = ImageDraw.Draw(dummy)
    char_widths = []
    for ch in text:
        tb = d_draw.textbbox((0, 0), ch, font=font, stroke_width=bold_stroke)
        char_widths.append(max(1, tb[2] - tb[0]))

    total_w = sum(char_widths) + (len(text) - 1) * letter_spacing_px
    total_angle = total_w / R

    apex_angle = -math.pi / 2.0
    cur_angle = apex_angle - (total_angle / 2.0)

    for i, ch in enumerate(text):
        cw = char_widths[i]
        ch_angle = cur_angle + (cw / 2.0) / R

        px = cx + R * math.cos(ch_angle)
        py = cy + R * math.sin(ch_angle)
        rot_deg = math.degrees(ch_angle + math.pi / 2.0)

        char_box_size = int(font_size * 2.5)
        c_img = Image.new("RGBA", (char_box_size, char_box_size), (0, 0, 0, 0))
        c_draw = ImageDraw.Draw(c_img)

        cb = char_box_size // 2
        # Deep 3D drop shadow
        c_draw.text(
            (cb + 2, cb + 3),
            ch,
            font=font,
            anchor="mm",
            fill=shadow_color,
            stroke_width=bold_stroke,
            stroke_fill=shadow_color,
        )
        # Bold white text
        c_draw.text(
            (cb, cb),
            ch,
            font=font,
            anchor="mm",
            fill=text_color,
            stroke_width=bold_stroke,
            stroke_fill=text_color,
        )

        c_rot = c_img.rotate(-rot_deg, resample=Image.Resampling.BICUBIC)
        im.paste(
            c_rot,
            (int(px - char_box_size / 2.0), int(py - char_box_size / 2.0)),
            c_rot,
        )
        cur_angle += (cw + letter_spacing_px) / R

    target_h = int(orig_h * (target_width / orig_w))
    return im.resize((target_width, target_h), Image.Resampling.LANCZOS)


def wrap_text(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, max_w: int) -> list[str]:
    words = text.strip().split()
    lines = []
    cur = ""
    for w in words:
        cand = f"{cur} {w}".strip()
        if cur and draw.textbbox((0, 0), cand, font=font)[2] > max_w:
            lines.append(cur)
            cur = w
        else:
            cur = cand
    if cur:
        lines.append(cur)
    return lines


# ── Procedural Vector Icons (Zero Missing Glyphs) ──────────────────────────


def draw_vector_leaf(
    draw: ImageDraw.ImageDraw,
    cx: float,
    cy: float,
    size: float,
    color: tuple,
    angle_deg: float = 0,
):
    """Draw a crisp, elegant vector almond leaf."""
    rad = math.radians(angle_deg)
    cos_a, sin_a = math.cos(rad), math.sin(rad)
    pts = []
    for deg in range(0, 181, 15):
        r = math.radians(deg)
        lx = size * math.sin(r) * 0.35
        ly = -size * math.cos(r) * 0.55
        rx = cx + (lx * cos_a - ly * sin_a)
        ry = cy + (lx * sin_a + ly * cos_a)
        pts.append((rx, ry))
    for deg in range(180, -1, -15):
        r = math.radians(deg)
        lx = -size * math.sin(r) * 0.35
        ly = -size * math.cos(r) * 0.55
        rx = cx + (lx * cos_a - ly * sin_a)
        ry = cy + (lx * sin_a + ly * cos_a)
        pts.append((rx, ry))
    if len(pts) > 2:
        draw.polygon(pts, fill=color)


def draw_vector_sprig(
    draw: ImageDraw.ImageDraw,
    cx: float,
    cy: float,
    size: float,
    color: tuple,
):
    """Draw a stylized 3-leaf laurel/herb sprig with stem."""
    draw_vector_leaf(draw, cx - size * 0.45, cy + 2, size * 0.75, color, angle_deg=-38)
    draw_vector_leaf(draw, cx + size * 0.45, cy + 2, size * 0.75, color, angle_deg=38)
    draw_vector_leaf(draw, cx, cy - size * 0.25, size * 0.9, color, angle_deg=0)
    draw.line([(cx, cy + size * 0.5), (cx, cy - size * 0.1)], fill=color, width=2)


def draw_vector_clock(draw: ImageDraw.ImageDraw, cx: float, cy: float, r: float, color: tuple):
    """Draw a crisp vector clock face with hour/minute hands."""
    draw.ellipse((cx - r, cy - r, cx + r, cy + r), outline=color, width=3)
    draw.line([(cx, cy), (cx, cy - r * 0.58)], fill=color, width=3)
    draw.line([(cx, cy), (cx + r * 0.52, cy)], fill=color, width=3)
    draw.ellipse((cx - 2, cy - 2, cx + 2, cy + 2), fill=color)


def draw_vector_flame(draw: ImageDraw.ImageDraw, cx: float, cy: float, size: float, color: tuple):
    """Draw a crisp vector calorie flame with light core."""
    pts = [
        (cx, cy - size * 0.6),
        (cx + size * 0.38, cy - size * 0.1),
        (cx + size * 0.45, cy + size * 0.35),
        (cx + size * 0.25, cy + size * 0.55),
        (cx, cy + size * 0.6),
        (cx - size * 0.25, cy + size * 0.55),
        (cx - size * 0.45, cy + size * 0.35),
        (cx - size * 0.38, cy - size * 0.1),
    ]
    draw.polygon(pts, fill=color)
    inner_pts = [
        (cx, cy - size * 0.1),
        (cx + size * 0.18, cy + size * 0.2),
        (cx, cy + size * 0.45),
        (cx - size * 0.18, cy + size * 0.2),
    ]
    draw.polygon(inner_pts, fill=(255, 255, 255, 220))


def draw_vector_people(draw: ImageDraw.ImageDraw, cx: float, cy: float, size: float, color: tuple):
    """Draw a clean vector silhouette for portions."""
    hr = size * 0.24
    draw.ellipse((cx - hr, cy - size * 0.5, cx + hr, cy - size * 0.5 + 2 * hr), fill=color)
    draw.chord(
        (cx - size * 0.48, cy - size * 0.05, cx + size * 0.48, cy + size * 0.68), start=0, end=180, fill=color
    )


def draw_vector_bulb(draw: ImageDraw.ImageDraw, cx: float, cy: float, size: float, color: tuple):
    """Draw a crisp vector lightbulb with rays for the chef tip."""
    r = size * 0.36
    draw.ellipse((cx - r, cy - size * 0.45, cx + r, cy - size * 0.45 + 2 * r), fill=color)
    draw.rectangle((cx - r * 0.48, cy + r * 0.3, cx + r * 0.48, cy + size * 0.46), fill=color)
    for angle in (-45, 0, 45):
        rad = math.radians(angle)
        x1 = cx + (r + 4) * math.sin(rad)
        y1 = (cy - size * 0.1) - (r + 4) * math.cos(rad)
        x2 = cx + (r + 10) * math.sin(rad)
        y2 = (cy - size * 0.1) - (r + 10) * math.cos(rad)
        draw.line([(x1, y1), (x2, y2)], fill=color, width=2)


def draw_ribbon_banner(
    draw: ImageDraw.ImageDraw,
    xy: tuple[int, int, int, int],
    bg_color: tuple[int, int, int],
    text: str,
    font: ImageFont.FreeTypeFont,
    text_color: tuple[int, int, int] = (255, 255, 255),
):
    """Draw a rounded ribbon banner pill with laurel sprigs flanking the text."""
    x1, y1, x2, y2 = xy
    h = y2 - y1
    w = x2 - x1
    r = h // 2
    draw.rounded_rectangle((x1, y1, x2, y2), radius=r, fill=bg_color)
    draw.rounded_rectangle(
        (x1 + 3, y1 + 3, x2 - 3, y2 - 3), radius=r - 2, outline=(255, 255, 255, 80), width=1
    )

    tb = draw.textbbox((0, 0), text, font=font)
    tw = tb[2] - tb[0]
    th = tb[3] - tb[1]
    tx = x1 + (w - tw) // 2
    ty = y1 + (h - th) // 2 - 2
    draw.text((tx, ty), text, font=font, fill=text_color)

    sprig_color = (255, 255, 255, 235)
    draw_vector_sprig(draw, tx - 32, y1 + h // 2 - 1, 24, sprig_color)
    draw_vector_sprig(draw, tx + tw + 32, y1 + h // 2 - 1, 24, sprig_color)


# ── Recipe-Aware Themes & Palettes ─────────────────────────────────────────


@dataclass(frozen=True)
class RecipeThemePalette:
    name: str
    primary_ribbon: tuple[int, int, int]
    accent_pill: tuple[int, int, int]
    title_dark: tuple[int, int, int]
    font_title_base: str
    font_title_accent: str
    font_ribbon: str
    font_flair: str
    kicker_default: str
    badge_lines: tuple[str, ...]
    hashtag_bar: str
    label: str = ""
    # Backwards compatibility properties
    header: tuple[int, int, int] = field(init=False)
    accent: tuple[int, int, int] = field(init=False)

    def __post_init__(self):
        # header and accent map to primary and accent for legacy callers
        object.__setattr__(self, "header", self.accent_pill)
        object.__setattr__(self, "accent", self.primary_ribbon)


THEMES: dict[str, RecipeThemePalette] = {
    "ensalada": RecipeThemePalette(
        name="ensalada_saludable",
        primary_ribbon=(78, 125, 40),  # Garden Green
        accent_pill=(232, 99, 26),  # Carrot Orange
        title_dark=(42, 68, 30),  # Forest Green
        font_title_base="DMSerifDisplay-Regular.ttf",
        font_title_accent="Pacifico-Regular.ttf",
        font_ribbon="Montserrat-Bold.ttf",
        font_flair="Pacifico-Regular.ttf",
        kicker_default="¡Una combinación fresca y deliciosa!",
        badge_lines=("FRESCA,", "SALUDABLE Y", "LLENA DE", "SABOR"),
        hashtag_bar="#EnsaladaSaludable • #RecetaFácil • #ComidaFresca",
        label="Huerta & Ensaladas",
    ),
    "postre": RecipeThemePalette(
        name="postre_reposteria",
        primary_ribbon=(190, 24, 75),  # Berry Ruby
        accent_pill=(217, 119, 6),  # Warm Honey Caramel
        title_dark=(76, 5, 25),  # Cacao Burgundy
        font_title_base="AbrilFatface-Regular.ttf",
        font_title_accent="DancingScript-Bold.ttf",
        font_ribbon="DMSerifDisplay-Regular.ttf",
        font_flair="DancingScript-Bold.ttf",
        kicker_default="¡Irresistible, dulce y delicioso!",
        badge_lines=("DULCE,", "CREMOSA Y", "MUY FÁCIL", "DE HACER"),
        hashtag_bar="#PostreCasero • #ReposteríaFácil • #DulcesDeliciosos",
        label="Repostería & Dulces",
    ),
    "chocolate": RecipeThemePalette(
        name="chocolate_cacao",
        primary_ribbon=(107, 62, 38),  # Rich Espresso Cacao
        accent_pill=(217, 119, 6),  # Golden Caramel
        title_dark=(45, 24, 16),  # Dark Mocha
        font_title_base="DMSerifDisplay-Regular.ttf",
        font_title_accent="Lobster-Regular.ttf",
        font_ribbon="Montserrat-Bold.ttf",
        font_flair="Lobster-Regular.ttf",
        kicker_default="¡Puro chocolate para momentos especiales!",
        badge_lines=("INTENSO,", "CREMOSO Y", "100% CACAO", "GOURMET"),
        hashtag_bar="#ChocolateLover • #PostreDeChocolate • #Repostería",
        label="Chocolate & Cacao",
    ),
    "arroz": RecipeThemePalette(
        name="arroz_paella",
        primary_ribbon=(194, 65, 12),  # Saffron Terracotta
        accent_pill=(229, 139, 0),  # Saffron Gold
        title_dark=(75, 28, 10),  # Deep Terracotta
        font_title_base="AbrilFatface-Regular.ttf",
        font_title_accent="Playball-Regular.ttf",
        font_ribbon="Montserrat-Bold.ttf",
        font_flair="Playball-Regular.ttf",
        kicker_default="¡Tradición mediterránea en cada bocado!",
        badge_lines=("TRADICIONAL,", "SABROSA Y", "EN SU PUNTO", "PERFECTO"),
        hashtag_bar="#ArrozTradicional • #PaellaCasera • #SaborEspañol",
        label="Azafrán & Arroces",
    ),
    "carne": RecipeThemePalette(
        name="carne_asados",
        primary_ribbon=(153, 27, 27),  # Roast Crimson
        accent_pill=(234, 88, 12),  # Flame Ember Orange
        title_dark=(69, 10, 10),  # Smokey Maroon
        font_title_base="Montserrat-Bold.ttf",
        font_title_accent="AbrilFatface-Regular.ttf",
        font_ribbon="Montserrat-Bold.ttf",
        font_flair="Caveat-Bold.ttf",
        kicker_default="¡Jugosa, tierna y llena de sabor!",
        badge_lines=("JUGOSA,", "CRUJIENTE Y", "DELICIOSA", "AL HORNO"),
        hashtag_bar="#CarneAlHorno • #RecetaCasera • #CocinaTradicional",
        label="Carnes & Asados",
    ),
    "pescado": RecipeThemePalette(
        name="pescado_marisco",
        primary_ribbon=(8, 145, 178),  # Coastal Aqua Marine
        accent_pill=(244, 63, 94),  # Coral Rose
        title_dark=(12, 74, 110),  # Deep Marine Navy
        font_title_base="Cinzel[wght].ttf",
        font_title_accent="Lora-Italic[wght].ttf",
        font_ribbon="Montserrat-Bold.ttf",
        font_flair="DancingScript-Bold.ttf",
        kicker_default="¡Fresco, ligero y con aroma a mar!",
        badge_lines=("FRESCO,", "LIGERO Y", "100% MARINO", "DELICIOSO"),
        hashtag_bar="#PescadoFresco • #Mariscos • #CocinaMediterránea",
        label="Pescados & Mariscos",
    ),
    "pasta": RecipeThemePalette(
        name="pasta_italiana",
        primary_ribbon=(220, 38, 38),  # Pomodoro Red
        accent_pill=(22, 163, 74),  # Basil Green
        title_dark=(69, 10, 10),  # Chianti Wine
        font_title_base="PlayfairDisplay.ttf",
        font_title_accent="Lobster-Regular.ttf",
        font_ribbon="Montserrat-Bold.ttf",
        font_flair="Pacifico-Regular.ttf",
        kicker_default="¡El auténtico sabor de la cocina italiana!",
        badge_lines=("AL DENTE,", "CREMOSA Y", "LLENA DE", "SABOR"),
        hashtag_bar="#PastaCasera • #CocinaItaliana • #RecetaFácil",
        label="Pastas & Pomodoro",
    ),
    "gourmet": RecipeThemePalette(
        name="champagne_gold",
        primary_ribbon=(161, 98, 7),  # Gourmet Amber Gold
        accent_pill=(217, 119, 6),  # Champagne Ochre
        title_dark=(31, 41, 55),  # Truffle Slate
        font_title_base="Prata-Regular.ttf",
        font_title_accent="CormorantGaramond-Italic[wght].ttf",
        font_ribbon="Cinzel[wght].ttf",
        font_flair="CormorantGaramond-Italic[wght].ttf",
        kicker_default="¡Cocina gourmet fácil en tu propia casa!",
        badge_lines=("GOURMET,", "ELEGANTE Y", "PERFECTA", "DE SABOR"),
        hashtag_bar="#CocinaGourmet • #RecetasDeChef • #AltaCocina",
        label="Cocina Gourmet",
    ),
}


def get_recipe_theme_colors(text_to_match: str) -> RecipeThemePalette:
    """Detect recipe category and return its complete theme palette and typography suite."""
    t = (text_to_match or "").lower()

    if any(k in t for k in ("chocolate", "cacao", "trufa", "brownie", "mousse", "fondant")):
        return THEMES["chocolate"]
    if any(
        k in t
        for k in (
            "ensalada",
            "verdura",
            "aguacate",
            "quinoa",
            "kale",
            "gazpacho",
            "saludable",
            "verde",
            "detox",
            "pepino",
            "lechuga",
        )
    ):
        return THEMES["ensalada"]
    if any(
        k in t
        for k in (
            "postre",
            "tarta",
            "pastel",
            "bizcocho",
            "galleta",
            "dulce",
            "crema",
            "flan",
            "cheesecake",
            "fresa",
            "fruta",
        )
    ):
        return THEMES["postre"]
    if any(
        k in t
        for k in (
            "arroz",
            "paella",
            "risotto",
            "azafran",
            "azafrán",
            "fideua",
            "guiso",
            "estofado",
            "lenteja",
            "garbanzo",
            "potaje",
        )
    ):
        return THEMES["arroz"]
    if any(
        k in t
        for k in (
            "carne",
            "pollo",
            "ternera",
            "cerdo",
            "asado",
            "bbq",
            "solomillo",
            "costilla",
            "alitas",
            "hamburguesa",
            "albondiga",
        )
    ):
        return THEMES["carne"]
    if any(
        k in t
        for k in (
            "pescado",
            "marisco",
            "salmon",
            "salmón",
            "atun",
            "atún",
            "merluza",
            "bacalao",
            "gamba",
            "pulpo",
            "calamar",
            "ceviche",
        )
    ):
        return THEMES["pescado"]
    if any(
        k in t
        for k in (
            "pasta",
            "pizza",
            "espagueti",
            "macarron",
            "macarrón",
            "lasana",
            "lasaña",
            "tomate",
            "pomodoro",
            "ravioli",
            "gnocchi",
        )
    ):
        return THEMES["pasta"]

    return THEMES["gourmet"]


# ── Title Typography Fitting ───────────────────────────────────────────────


def _fit_title_line(
    draw: ImageDraw.ImageDraw,
    text: str,
    font_name: str,
    max_width: int,
    preferred_size: int,
    min_size: int = 34,
) -> tuple[ImageFont.FreeTypeFont, list[str]]:
    """Fit a title line strictly within max_width, scaling or wrapping into at most 2 lines."""
    for size in range(preferred_size, min_size - 1, -2):
        f = get_font(font_name, size)
        tb = draw.textbbox((0, 0), text, font=f)
        if (tb[2] - tb[0]) <= max_width:
            return f, [text]
    # Split words if still exceeding max_width
    words = text.split()
    if len(words) > 1:
        half = len(words) // 2
        l1 = " ".join(words[:half])
        l2 = " ".join(words[half:])
        f = get_font(font_name, min_size)
        return f, [l1, l2]
    f = get_font(font_name, min_size)
    return f, [text]


THEME_RIBBON_MAP = {
    "ensalada_saludable": "arch_ribbon_green",
    "postre_reposteria": "arch_ribbon_burgundy",
    "chocolate_cacao": "arch_ribbon_burgundy",
    "arroz_paella": "arch_ribbon_gold",
    "carne_asados": "arch_ribbon_burgundy",
    "pescado_marisco": "arch_ribbon_green",
    "pasta_italiana": "arch_ribbon_terracotta",
    "champagne_gold": "arch_ribbon_gold",
}

THEME_BADGE_MAP = {
    "ensalada_saludable": "badge_laurel_gourmet",
    "postre_reposteria": "badge_wax_seal",
    "chocolate_cacao": "badge_wax_seal",
    "arroz_paella": "badge_stamp_star",
    "carne_asados": "badge_stamp_star",
    "pescado_marisco": "badge_rosette_gold",
    "pasta_italiana": "badge_stamp_star",
    "champagne_gold": "badge_laurel_gourmet",
}


def _infer_step_action(step_text: str, default_action: str) -> str:
    st = step_text.lower()
    if any(k in st for k in ("pela", "corta", "picar", "lava", "limpia", "trocea", "prepara")):
        return "PREPARAR"
    if any(
        k in st
        for k in (
            "cocina",
            "hierve",
            "hornea",
            "funde",
            "saltea",
            "fríe",
            "frie",
            "fuego",
            "calienta",
            "dora",
        )
    ):
        return "COCINAR"
    if any(
        k in st
        for k in ("mezcla", "integra", "remueve", "añade", "incorpora", "bate", "vierte", "agrega", "junta")
    ):
        return "INTEGRAR"
    if any(k in st for k in ("sirve", "refrigera", "decora", "emplata", "presenta", "reposa", "disfruta")):
        return "SERVIR"
    return default_action


# ── Variant 1: Bright Culinary Paper Infographic Pin ───────────────────────


def create_bright_infographic_pin(
    hero_image_path: str,
    title: str,
    subtitle: str = "",
    ingredients: list[str] | None = None,
    steps: list[str] | None = None,
    tip_text: str = "",
    prep_time: str = "20 min",
    calories: str = "220 kcal",
    servings: str = "4 porc.",
    domain_handle: str = "",
    output_dir: Path | None = None,
    output_path: Path | str | None = None,
) -> dict[str, Any]:
    """Generate Variant 1 of the ingredients pin: Bright Culinary Paper Infographic.

    Features:
    - Ambient blurred hero dish photo blended with genuine tactile parchment texture
    - Top-left bounded title block with kicker pill, flair script, and multi-font headline
    - Top-right 490px circular food bowl hero photograph with drop shadow & authentic stamp badge
    - Middle-left INGREDIENTES arched ribbon over rounded card with clean padding and bullets
    - Middle-right 3-stat METRICS CARD with high-resolution culinary icons (timer, flame, cutlery)
    - Centered PASO A PASO arched ribbon banner in dedicated vertical band
    - 2x2 process grid for the 4 steps: numbered 3D circular badges, culinary action icons,
      horizontally centered action titles, and multi-line body text without repeated images
    - Bottom: Chef Tip box (with 40x44 bulb icon and collision-free text) and Social Proof Guarantee CTA
    - Bottom: Full-width themed hashtag/domain branding bar.
    """
    from rankstein.remaster_variants import _cover

    src = Path(hero_image_path)
    if not src.exists():
        return {"success": False, "error": f"Hero image not found: {hero_image_path}"}

    ing_list = list(ingredients) if ingredients else []
    if not ing_list:
        ing_list = [
            "Ingredientes frescos seleccionados",
            "Especias y condimentos al gusto",
            "Aceite de oliva virgen extra",
        ]

    steps_list = list(steps) if steps else []
    default_fallbacks = [
        "Prepara y organiza todos los ingredientes frescos en recipientes limpios.",
        "Cocina a temperatura adecuada cuidando los tiempos de preparación.",
        "Integra suavemente los componentes para unir texturas y potenciar el sabor.",
        "Sirve recién preparado y decora al gusto para disfrutar al máximo.",
    ]
    while len(steps_list) < 4:
        steps_list.append(default_fallbacks[len(steps_list)])

    # Domain resolution
    domain_text = "recetagenial.com"
    if domain_handle:
        try:
            from rankstein.domain import get_registry

            d = get_registry().get(domain_handle)
            domain_text = getattr(d, "domain", domain_text)
        except Exception as exc:
            logger.debug("Could not resolve domain handle %s: %s", domain_handle, exc)

    theme = get_recipe_theme_colors(f"{title} {' '.join(ing_list)}")

    c_primary = theme.primary_ribbon
    c_accent = theme.accent_pill
    c_title = theme.title_dark
    c_card_bg = (255, 255, 255, 252)
    c_card_border = (226, 218, 205, 255)
    c_meta_bg = (255, 255, 255, 252)

    c_ink_bold = (26, 22, 18, 255)  # Deep espresso charcoal
    c_ink_med = (50, 42, 35, 255)  # Rich readable dark brown

    ribbon_name = THEME_RIBBON_MAP.get(theme.name, "arch_ribbon_gold")
    badge_name = THEME_BADGE_MAP.get(theme.name, "badge_stamp_star")

    # 1. LUXURY BACKGROUND: Ambient Blurred Hero + Tactile Parchment Paper Texture
    with Image.open(src) as raw_hero:
        bg_food = _cover(raw_hero, PIN_W, PIN_H, focus_y=0.45)
        bg_food = bg_food.filter(ImageFilter.GaussianBlur(40))
        bg_food = ImageEnhance.Color(bg_food).enhance(0.22)
        bg_food = ImageEnhance.Brightness(bg_food).enhance(1.15)

        tex_path = TEXTURES_DIR / "paper_parchment.jpg"
        if tex_path.exists():
            with Image.open(tex_path) as paper_raw:
                paper_tex = _cover(paper_raw, PIN_W, PIN_H)
                canvas = Image.blend(paper_tex, bg_food, alpha=0.35).convert("RGBA")
        else:
            base_cream = Image.new("RGB", (PIN_W, PIN_H), (252, 249, 242))
            canvas = Image.blend(base_cream, bg_food, alpha=0.25).convert("RGBA")

    draw = ImageDraw.Draw(canvas, "RGBA")

    # Outer decorative border
    draw.rounded_rectangle((22, 22, PIN_W - 22, PIN_H - 22), radius=28, outline=(225, 218, 204, 255), width=2)

    # 2. TOP SECTION: Hero Bowl Photo (Right) & Title Block (Left)
    hero_size = 490
    hero_x = PIN_W - hero_size - 28
    hero_y = 28
    with Image.open(src) as h_img:
        hero_sq = _cover(h_img, hero_size, hero_size, focus_y=0.42).convert("RGBA")

    mask = Image.new("L", (hero_size, hero_size), 0)
    mask_draw = ImageDraw.Draw(mask)
    mask_draw.ellipse((0, 0, hero_size, hero_size), fill=255)

    shadow_size = hero_size + 48
    shadow = Image.new("RGBA", (shadow_size, shadow_size), (0, 0, 0, 0))
    s_draw = ImageDraw.Draw(shadow)
    s_draw.ellipse((24, 24, shadow_size - 24, shadow_size - 24), fill=(20, 15, 10, 110))
    shadow = shadow.filter(ImageFilter.GaussianBlur(20))

    canvas.paste(shadow, (hero_x - 24, hero_y - 24 + 10), shadow)
    canvas.paste(hero_sq, (hero_x, hero_y), mask)
    draw.ellipse(
        (hero_x, hero_y, hero_x + hero_size, hero_y + hero_size), outline=(255, 255, 255, 255), width=8
    )
    draw.ellipse(
        (hero_x + 4, hero_y + 4, hero_x + hero_size - 4, hero_y + hero_size - 4),
        outline=(*c_primary, 255),
        width=2,
    )

    # Overlapping Badge Stamp
    badge_im = load_badge(badge_name, 160)
    badge_x = hero_x - 30
    badge_y = hero_y + hero_size - 135
    paste_with_shadow(
        canvas, badge_im, (badge_x, badge_y), shadow_blur=10, shadow_alpha=90, shadow_offset=(0, 6)
    )

    # Left Title Block: STRICTLY bounded to max_title_w = 380px so ZERO text collides with hero bowl or badge
    max_title_w = 380
    cur_y = 42

    # Kicker Pill
    f_kicker = get_font("Montserrat-Bold.ttf", 16)
    kicker_label = subtitle.strip().upper() if subtitle and len(subtitle) < 35 else "RECETA CASERA Y FÁCIL"
    kw = draw.textbbox((0, 0), kicker_label, font=f_kicker)
    pill_w = kw[2] - kw[0] + 44
    draw_card_with_shadow(
        canvas,
        (50, cur_y, 50 + pill_w, cur_y + 36),
        radius=18,
        fill=(*c_accent, 255),
        shadow_blur=6,
        shadow_alpha=50,
        shadow_offset=(0, 2),
    )
    draw.text((72 + 1, cur_y + 9 + 1), kicker_label, font=f_kicker, fill=(0, 0, 0, 130))
    draw.text((72, cur_y + 9), kicker_label, font=f_kicker, fill=(255, 255, 255, 255))
    cur_y += 52

    # Flair Script
    f_flair = get_font(theme.font_flair, 30)
    flair_lines = wrap_text(draw, theme.kicker_default, f_flair, max_title_w)
    for fl in flair_lines:
        draw.text((50 + 1, cur_y + 1), fl, font=f_flair, fill=(255, 255, 255, 180))
        draw.text((50, cur_y), fl, font=f_flair, fill=(*c_accent, 255))
        cur_y += 36
    cur_y += 8

    # Title Line 1 & Line 2
    dish_match = re.match(
        r"^(ensalada de|tarta de|pastel de|bizcocho de|arroz con|paella de|guiso de|sopa de|crema de|pollo al|solomillo de|lomo de)\s+(.*)$",
        title.strip(),
        re.IGNORECASE,
    )
    if dish_match:
        l1 = dish_match.group(1).title()
        l2 = dish_match.group(2).strip().title()
    else:
        title_words = title.strip().split()
        mid = max(1, len(title_words) // 2)
        l1 = " ".join(title_words[:mid])
        l2 = " ".join(title_words[mid:])

    f_t1, l1_lines = _fit_title_line(draw, l1, theme.font_title_base, max_title_w, 45, 28)
    for line in l1_lines:
        draw.text((50 + 1, cur_y + 2), line, font=f_t1, fill=(0, 0, 0, 70))
        draw.text((50, cur_y), line, font=f_t1, fill=(*c_title, 255))
        cur_y += f_t1.size + 6

    if l2:
        f_t2, l2_lines = _fit_title_line(draw, l2, theme.font_title_accent, max_title_w, 42, 26)
        for line in l2_lines:
            draw.text((50 + 1, cur_y + 2), line, font=f_t2, fill=(0, 0, 0, 70))
            draw.text((50, cur_y), line, font=f_t2, fill=(*c_primary, 255))
            cur_y += f_t2.size + 6

    cur_y += 14
    # Description
    f_desc = get_font("Poppins-Regular.ttf", 16)
    desc_raw = (
        "¡Una combinación fresca, deliciosa y tradicional que no puedes perderte! Perfecta para compartir."
    )
    desc_lines = wrap_text(draw, desc_raw, f_desc, max_title_w)
    for dl in desc_lines[:3]:
        draw.text((50 + 1, cur_y + 1), dl, font=f_desc, fill=(255, 255, 255, 160))
        draw.text((50, cur_y), dl, font=f_desc, fill=c_ink_bold)
        cur_y += 24

    # 3. MIDDLE SECTION: INGREDIENTES & METRICS [y: 535 to 835]
    mid_y = 535
    card_w = 430
    ing_card_h = 285
    ing_card_y = mid_y + 35

    # Draw Ingredients Card First
    draw_card_with_shadow(
        canvas,
        (45, ing_card_y, 45 + card_w, ing_card_y + ing_card_h),
        radius=20,
        fill=c_card_bg,
        outline=c_card_border,
        width=1,
        shadow_blur=14,
        shadow_alpha=45,
        shadow_offset=(0, 6),
    )

    # Arched Ribbon: Paste ON TOP of card header (zero clipping, zero occlusion)
    ribbon_w = 440
    ribbon_ing = create_luxury_arched_ribbon(
        ribbon_name,
        "INGREDIENTES",
        target_width=ribbon_w,
        font_name="DMSerifDisplay-Regular.ttf",
        font_size=48,
        letter_spacing_px=6.0,
        apex_y=52.0,
    )
    ribbon_ing_x = 45 + (card_w - ribbon_w) // 2
    ribbon_ing_h = ribbon_ing.height
    paste_with_shadow(
        canvas, ribbon_ing, (ribbon_ing_x, mid_y), shadow_blur=8, shadow_alpha=80, shadow_offset=(0, 4)
    )

    # Ingredients Text: Starts strictly BELOW ribbon tails (mid_y + ribbon_ing_h + 14 = 652)
    cur_ing_y = mid_y + ribbon_ing_h + 14
    f_ing = get_font("Poppins-SemiBold.ttf", 18)
    for item in ing_list[:5]:
        draw.text((64, cur_ing_y - 2), "•", font=get_font("Montserrat-Bold.ttf", 22), fill=(*c_accent, 255))
        draw.text((86, cur_ing_y), item, font=f_ing, fill=c_ink_bold)
        cur_ing_y += 35

    # Metrics Card
    meta_x = 495
    meta_w = PIN_W - meta_x - 45
    meta_y = ing_card_y
    meta_h = ing_card_h

    draw_card_with_shadow(
        canvas,
        (meta_x, meta_y, meta_x + meta_w, meta_y + meta_h),
        radius=20,
        fill=c_meta_bg,
        outline=c_card_border,
        width=1,
        shadow_blur=14,
        shadow_alpha=45,
        shadow_offset=(0, 6),
    )

    col_w = meta_w // 3
    f_meta_lbl = get_font("Montserrat-Bold.ttf", 13)
    f_meta_val = get_font("Montserrat-Bold.ttf", 20)

    # Col 1: Prep Time
    timer_icon = load_icon("timer", 46, 46)
    cx1 = meta_x + col_w // 2
    paste_with_shadow(
        canvas,
        timer_icon,
        (cx1 - timer_icon.width // 2, meta_y + 16),
        shadow_blur=4,
        shadow_alpha=50,
        shadow_offset=(0, 2),
    )
    draw.text(
        (cx1 - 42, meta_y + 70), "TIEMPO DE\nPREPARACIÓN", font=f_meta_lbl, fill=c_ink_bold, align="center"
    )

    pill_box1 = (cx1 - (col_w - 24) // 2, meta_y + 122, cx1 + (col_w - 24) // 2, meta_y + 164)
    draw_card_with_shadow(
        canvas,
        pill_box1,
        radius=14,
        fill=(*c_accent, 255),
        shadow_blur=5,
        shadow_alpha=60,
        shadow_offset=(0, 2),
    )
    tb1 = draw.textbbox((0, 0), prep_time, font=f_meta_val)
    draw.text(
        (cx1 - (tb1[2] - tb1[0]) // 2 + 1, meta_y + 130 + 1), prep_time, font=f_meta_val, fill=(0, 0, 0, 130)
    )
    draw.text(
        (cx1 - (tb1[2] - tb1[0]) // 2, meta_y + 130), prep_time, font=f_meta_val, fill=(255, 255, 255, 255)
    )

    # Col 2: Calories
    flame_icon = load_icon("flame", 42, 48)
    cx2 = meta_x + col_w + col_w // 2
    paste_with_shadow(
        canvas,
        flame_icon,
        (cx2 - flame_icon.width // 2, meta_y + 14),
        shadow_blur=4,
        shadow_alpha=50,
        shadow_offset=(0, 2),
    )
    draw.text((cx2 - 34, meta_y + 78), "CALORÍAS", font=f_meta_lbl, fill=c_ink_bold, align="center")

    pill_box2 = (cx2 - (col_w - 24) // 2, meta_y + 122, cx2 + (col_w - 24) // 2, meta_y + 164)
    draw_card_with_shadow(
        canvas,
        pill_box2,
        radius=14,
        fill=(*c_accent, 255),
        shadow_blur=5,
        shadow_alpha=60,
        shadow_offset=(0, 2),
    )
    tb2 = draw.textbbox((0, 0), calories, font=f_meta_val)
    draw.text(
        (cx2 - (tb2[2] - tb2[0]) // 2 + 1, meta_y + 130 + 1), calories, font=f_meta_val, fill=(0, 0, 0, 130)
    )
    draw.text(
        (cx2 - (tb2[2] - tb2[0]) // 2, meta_y + 130), calories, font=f_meta_val, fill=(255, 255, 255, 255)
    )

    # Col 3: Servings
    cutlery_icon = load_icon("cutlery", 42, 48)
    cx3 = meta_x + 2 * col_w + col_w // 2
    paste_with_shadow(
        canvas,
        cutlery_icon,
        (cx3 - cutlery_icon.width // 2, meta_y + 14),
        shadow_blur=4,
        shadow_alpha=50,
        shadow_offset=(0, 2),
    )
    draw.text((cx3 - 38, meta_y + 78), "PORCIONES", font=f_meta_lbl, fill=c_ink_bold, align="center")

    pill_box3 = (cx3 - (col_w - 24) // 2, meta_y + 122, cx3 + (col_w - 24) // 2, meta_y + 164)
    draw_card_with_shadow(
        canvas,
        pill_box3,
        radius=14,
        fill=(*c_accent, 255),
        shadow_blur=5,
        shadow_alpha=60,
        shadow_offset=(0, 2),
    )
    tb3 = draw.textbbox((0, 0), servings, font=f_meta_val)
    draw.text(
        (cx3 - (tb3[2] - tb3[0]) // 2 + 1, meta_y + 130 + 1), servings, font=f_meta_val, fill=(0, 0, 0, 130)
    )
    draw.text(
        (cx3 - (tb3[2] - tb3[0]) // 2, meta_y + 130), servings, font=f_meta_val, fill=(255, 255, 255, 255)
    )

    # Divider & Sprig Callout
    draw.line(
        [(meta_x + 20, meta_y + 188), (meta_x + meta_w - 20, meta_y + 188)],
        fill=(225, 215, 200, 255),
        width=1,
    )
    sprig_icon = load_icon("sprig", 36, 36)
    canvas.paste(sprig_icon, (meta_x + 28, meta_y + 208), sprig_icon)
    draw.text(
        (meta_x + 72, meta_y + 206),
        "100% Casero & Tradicional",
        font=get_font("Poppins-SemiBold.ttf", 17),
        fill=(*c_primary, 255),
    )
    draw.text(
        (meta_x + 72, meta_y + 232),
        "Paso a paso fácil y garantizado",
        font=get_font("Poppins-Regular.ttf", 15),
        fill=c_ink_bold,
    )

    # 4. PASO A PASO RIBBON (Completely Isolated Band) [y: 875 to 975]
    steps_ribbon_y = 875
    ribbon_step_w = 460
    ribbon_steps = create_luxury_arched_ribbon(
        ribbon_name,
        "PASO A PASO",
        target_width=ribbon_step_w,
        font_name="DMSerifDisplay-Regular.ttf",
        font_size=48,
        letter_spacing_px=6.0,
        apex_y=52.0,
    )
    ribbon_steps_x = (PIN_W - ribbon_step_w) // 2
    paste_with_shadow(
        canvas,
        ribbon_steps,
        (ribbon_steps_x, steps_ribbon_y),
        shadow_blur=8,
        shadow_alpha=80,
        shadow_offset=(0, 4),
    )

    # 5. STEP CARDS (2x2 Grid: Zero Repeated Images, Spacious Reading) [y: 995 to 1245]
    step_grid_y = 995
    grid_w = (PIN_W - 90 - 18) // 2  # 446px
    grid_h = 118  # 118px per card
    f_step_num = get_font("Montserrat-Bold.ttf", 19)
    f_step_kw = get_font("Montserrat-Bold.ttf", 14)
    f_step_txt = get_font("Poppins-Regular.ttf", 15)

    action_defaults = [
        ("PREPARAR", "chef_hat"),
        ("COCINAR", "flame"),
        ("INTEGRAR", "sprig"),
        ("SERVIR", "cutlery"),
    ]

    for idx, (step_txt, (default_kw, icon_name)) in enumerate(
        zip(steps_list[:4], action_defaults, strict=False), 1
    ):
        col = (idx - 1) % 2
        row = (idx - 1) // 2
        gx = 45 + col * (grid_w + 18)
        gy = step_grid_y + row * (grid_h + 14)

        draw_card_with_shadow(
            canvas,
            (gx, gy, gx + grid_w, gy + grid_h),
            radius=18,
            fill=c_card_bg,
            outline=c_card_border,
            width=1,
            shadow_blur=10,
            shadow_alpha=40,
            shadow_offset=(0, 5),
        )

        # Left badge column
        badge_r = 17
        bx = gx + 15
        by = gy + 15
        draw.ellipse((bx + 1, by + 1, bx + 2 * badge_r + 1, by + 2 * badge_r + 1), fill=(0, 0, 0, 50))
        draw.ellipse((bx, by, bx + 2 * badge_r, by + 2 * badge_r), fill=(*c_accent, 255))
        draw.ellipse((bx, by, bx + 2 * badge_r, by + 2 * badge_r), outline=(255, 255, 255, 255), width=2)
        nb = draw.textbbox((0, 0), str(idx), font=f_step_num)
        draw.text(
            (bx + badge_r - (nb[2] - nb[0]) // 2, by + badge_r - (nb[3] - nb[1]) // 2 - 1),
            str(idx),
            font=f_step_num,
            fill=(255, 255, 255, 255),
        )

        # Utensil icon under badge
        act_icon = load_icon(icon_name, 26, 26)
        canvas.paste(act_icon, (bx + 4, by + 2 * badge_r + 12), act_icon)

        # Action Title: Centered horizontally in each card (NO 'PASO 1:' prefix)
        action_kw = _infer_step_action(step_txt, default_kw)
        kw_box = draw.textbbox((0, 0), action_kw, font=f_step_kw)
        kw_w = kw_box[2] - kw_box[0]
        title_x = gx + (grid_w - kw_w) // 2
        draw.text((title_x, gy + 14), action_kw, font=f_step_kw, fill=(*c_primary, 255))

        st_lines = wrap_text(draw, step_txt, f_step_txt, grid_w - 78)
        sy = gy + 38
        for sl in st_lines[:3]:
            draw.text((gx + 64, sy), sl, font=f_step_txt, fill=c_ink_bold)
            sy += 22

    # 6. BOTTOM SECTION: Chef Tip (Left) & Guarantee CTA (Right) [y: 1265 to 1410]
    bot_y = 1265
    tip_w = 446
    tip_h = 145

    # Left: Chef Tip Card (ZERO OVERLAP with bulb icon!)
    draw_card_with_shadow(
        canvas,
        (45, bot_y, 45 + tip_w, bot_y + tip_h),
        radius=18,
        fill=(255, 252, 246, 252),
        outline=(220, 212, 198, 255),
        width=1,
        shadow_blur=12,
        shadow_alpha=40,
        shadow_offset=(0, 5),
    )

    # Bulb icon placed cleanly in upper-left
    bulb_icon = load_icon("bulb", 40, 44)
    paste_with_shadow(
        canvas, bulb_icon, (60, bot_y + 14), shadow_blur=4, shadow_alpha=50, shadow_offset=(0, 2)
    )

    # Title beside the bulb icon
    f_tip_title = get_font(theme.font_title_base, 24)
    draw.text((112 + 1, bot_y + 18 + 1), "Consejo del Chef:", font=f_tip_title, fill=(255, 255, 255, 180))
    draw.text((112, bot_y + 18), "Consejo del Chef:", font=f_tip_title, fill=(*c_primary, 255))

    # Body text starts strictly at y = bot_y + 68, COMPLETELY BELOW the bulb icon (no overlap!)
    f_tip_txt = get_font("Poppins-Regular.ttf", 15)
    clean_tip = (
        tip_text.strip()
        if tip_text
        else "Añade hierbas frescas picadas justo antes de servir para potenciar el aroma y la frescura."
    )
    tip_lines = wrap_text(draw, clean_tip, f_tip_txt, tip_w - 40)
    ty = bot_y + 68
    for tl in tip_lines[:3]:
        draw.text((60, ty), tl, font=f_tip_txt, fill=c_ink_bold)
        ty += 23

    # Right: Social Proof & CTA Card
    callout_x = 45 + tip_w + 18
    callout_w = tip_w
    draw_card_with_shadow(
        canvas,
        (callout_x, bot_y, callout_x + callout_w, bot_y + tip_h),
        radius=18,
        fill=(255, 255, 255, 252),
        outline=c_card_border,
        width=1,
        shadow_blur=12,
        shadow_alpha=40,
        shadow_offset=(0, 5),
    )

    badge_star = load_badge("badge_stamp_star", 56)
    canvas.paste(badge_star, (callout_x + 16, bot_y + 16), badge_star)

    f_flair_bot = get_font(theme.font_flair, 22)
    draw.text((callout_x + 84, bot_y + 16), "¡Receta 100% probada!", font=f_flair_bot, fill=(*c_accent, 255))
    draw.text(
        (callout_x + 84, bot_y + 42),
        "Fácil, deliciosa y garantizada.",
        font=get_font("Poppins-Regular.ttf", 14),
        fill=c_ink_med,
    )

    # CTA Button Pill
    cta_w = callout_w - 32
    draw_card_with_shadow(
        canvas,
        (callout_x + 16, bot_y + 80, callout_x + 16 + cta_w, bot_y + 126),
        radius=14,
        fill=(*c_primary, 255),
        shadow_blur=6,
        shadow_alpha=60,
        shadow_offset=(0, 2),
    )
    db = draw.textbbox((0, 0), "¡LISTA PARA SERVIR Y DISFRUTAR!", font=get_font("Montserrat-Bold.ttf", 14))
    draw.text(
        (callout_x + 16 + (cta_w - (db[2] - db[0])) // 2 + 1, bot_y + 94 + 1),
        "¡LISTA PARA SERVIR Y DISFRUTAR!",
        font=get_font("Montserrat-Bold.ttf", 14),
        fill=(0, 0, 0, 100),
    )
    draw.text(
        (callout_x + 16 + (cta_w - (db[2] - db[0])) // 2, bot_y + 94),
        "¡LISTA PARA SERVIR Y DISFRUTAR!",
        font=get_font("Montserrat-Bold.ttf", 14),
        fill=(255, 255, 255, 255),
    )

    # 7. FOOTER BRANDING BAR [y: 1432 to 1480]
    bar_y = 1432
    draw_card_with_shadow(
        canvas,
        (35, bar_y, PIN_W - 35, bar_y + 48),
        radius=25,
        fill=(*c_title, 255),
        shadow_blur=8,
        shadow_alpha=60,
        shadow_offset=(0, 3),
    )
    f_footer = get_font("Poppins-SemiBold.ttf", 18)
    footer_text = f"{theme.hashtag_bar}  •  {domain_text}"
    ftb = draw.textbbox((0, 0), footer_text, font=f_footer)
    draw.text(
        ((PIN_W - (ftb[2] - ftb[0])) // 2, bar_y + 13), footer_text, font=f_footer, fill=(255, 255, 255, 255)
    )

    # Save
    stem = src.stem.replace("-hero", "")
    target_dir = output_dir or src.parent
    target_dir.mkdir(parents=True, exist_ok=True)
    out_path = Path(output_path) if output_path else (target_dir / f"{stem}-infographic-pin-bright.jpg")
    canvas.convert("RGB").save(str(out_path), "JPEG", quality=95)

    return {
        "success": True,
        "output_path": str(out_path),
        "variant_used": "bright_infographic",
        "theme": theme.name,
        "dimensions": f"{PIN_W}x{PIN_H}",
    }


# ── Variant 2: Full-Bleed Cinematic Recipe Card ─────────────────────────────


def create_full_bleed_recipe_pin(
    hero_image_path: str,
    title: str,
    subtitle: str = "",
    ingredients: list[str] | None = None,
    steps: list[str] | None = None,
    tip_text: str = "",
    domain_handle: str = "",
    output_dir: Path | None = None,
    output_path: Path | str | None = None,
) -> dict[str, Any]:
    """Generate Variant 2 of the ingredients pin: Full-Bleed Cinematic Recipe Card."""
    from rankstein.remaster_variants import _cover

    src = Path(hero_image_path)
    if not src.exists():
        return {"success": False, "error": f"Hero image not found: {hero_image_path}"}

    ingredients = ingredients or []
    steps = steps or []

    palette = get_recipe_theme_colors(f"{title} {' '.join(ingredients)}")

    domain_text = "recetagenial.com"
    if domain_handle:
        try:
            from rankstein.domain import get_registry

            d = get_registry().get(domain_handle)
            domain_text = getattr(d, "domain", domain_text)
        except Exception as exc:
            logger.debug("Could not resolve domain handle %s: %s", domain_handle, exc)

    with Image.open(src) as hero_raw:
        photo = _cover(hero_raw, PIN_W, PIN_H, focus_y=0.38)
    photo = ImageEnhance.Contrast(photo).enhance(1.05)
    photo = ImageEnhance.Color(photo).enhance(1.06).convert("RGBA")

    # Dark bottom vignette
    overlay = Image.new("RGBA", (PIN_W, PIN_H), (0, 0, 0, 0))
    overlay_draw = ImageDraw.Draw(overlay)
    vignette_start = 840
    vignette_height = PIN_H - vignette_start
    for y in range(vignette_start, PIN_H):
        progress = (y - vignette_start) / vignette_height
        alpha = int(250 * (progress**1.15))
        overlay_draw.line((0, y, PIN_W, y), fill=(12, 9, 7, alpha))

    canvas = Image.alpha_composite(photo, overlay)
    draw = ImageDraw.Draw(canvas, "RGBA")

    # Top floating card
    card_x1 = 110
    card_x2 = 890
    card_w = card_x2 - card_x1
    card_y1 = 36
    card_radius = 28

    f_title = get_font(palette.font_title_base, 46)
    title_words = title.strip().split()
    t_lines = []
    c_line = ""
    for w in title_words:
        cand = f"{c_line} {w}".strip()
        if c_line and draw.textbbox((0, 0), cand, font=f_title)[2] > (card_w - 70):
            t_lines.append(c_line)
            c_line = w
        else:
            c_line = cand
    if c_line:
        t_lines.append(c_line)
    t_lines = t_lines[:2]

    f_sub = get_font("Poppins-Regular.ttf", 22)
    sub_text = subtitle.strip() or "Receta casera tradicional • Deliciosa y lista en minutos"
    sub_words = sub_text.split()
    s_lines = []
    c_sub = ""
    for sw in sub_words:
        cand = f"{c_sub} {sw}".strip()
        if c_sub and draw.textbbox((0, 0), cand, font=f_sub)[2] > (card_w - 60):
            s_lines.append(c_sub)
            c_sub = sw
        else:
            c_sub = cand
    if c_sub:
        s_lines.append(c_sub)
    s_lines = s_lines[:2]

    t_h = len(t_lines) * 54
    s_h = len(s_lines) * 32
    card_h = 24 + t_h + 10 + s_h + 20
    card_y2 = card_y1 + card_h

    # Card shadow
    sh_img = Image.new("RGBA", (card_w + 40, card_h + 40), (0, 0, 0, 0))
    s_draw = ImageDraw.Draw(sh_img)
    s_draw.rounded_rectangle((20, 20, 20 + card_w, 20 + card_h), radius=card_radius, fill=(10, 8, 6, 90))
    sh_img = sh_img.filter(ImageFilter.GaussianBlur(12))
    canvas.paste(sh_img, (card_x1 - 20, card_y1 - 20 + 8), sh_img)

    draw = ImageDraw.Draw(canvas, "RGBA")
    draw.rounded_rectangle(
        (card_x1, card_y1, card_x2, card_y2),
        radius=card_radius,
        fill=(248, 242, 233, 250),
        outline=(226, 216, 202, 190),
        width=1,
    )

    cur_y = card_y1 + 24
    for line in t_lines:
        tb = draw.textbbox((0, 0), line, font=f_title)
        draw.text(((PIN_W - (tb[2] - tb[0])) // 2, cur_y), line, font=f_title, fill=palette.title_dark)
        cur_y += 54
    cur_y += 6
    for line in s_lines:
        sb = draw.textbbox((0, 0), line, font=f_sub)
        draw.text(((PIN_W - (sb[2] - sb[0])) // 2, cur_y), line, font=f_sub, fill=(70, 65, 60))
        cur_y += 32

    # Two columns at bottom
    col_y_start = 950
    col_left_x1, col_left_w = 55, 415
    col_right_x1, col_right_w = 505, 435

    highlight_img = Image.new("RGBA", (PIN_W, PIN_H), (0, 0, 0, 0))
    h_draw = ImageDraw.Draw(highlight_img)
    h_draw.rounded_rectangle(
        (col_left_x1 - 15, col_y_start - 10, col_left_x1 + col_left_w + 15, 1435),
        radius=24,
        fill=(8, 6, 5, 140),
    )
    h_draw.rounded_rectangle(
        (col_right_x1 - 15, col_y_start - 10, col_right_x1 + col_right_w + 15, 1435),
        radius=24,
        fill=(8, 6, 5, 140),
    )
    highlight_img = highlight_img.filter(ImageFilter.GaussianBlur(18))
    canvas = Image.alpha_composite(canvas, highlight_img)

    draw = ImageDraw.Draw(canvas, "RGBA")
    f_header = get_font(palette.font_title_base, 44)
    draw.text((col_left_x1, col_y_start), "Ingredientes:", font=f_header, fill=palette.accent_pill)
    draw.text((col_right_x1, col_y_start), "Preparación:", font=f_header, fill=palette.accent_pill)

    f_ing = get_font("Poppins-SemiBold.ttf", 21)
    f_step = get_font("Poppins-Regular.ttf", 20)
    f_step_num = get_font("Montserrat-Bold.ttf", 20)

    # Ingredients
    ing_y = col_y_start + 60
    for item in ingredients[:8]:
        draw.text((col_left_x1, ing_y), "•", font=f_ing, fill=palette.accent_pill)
        words = item.strip().split()
        lines, cur = [], ""
        for w in words:
            cand = f"{cur} {w}".strip()
            if cur and draw.textbbox((0, 0), cand, font=f_ing)[2] > (col_left_w - 30):
                lines.append(cur)
                cur = w
            else:
                cur = cand
        if cur:
            lines.append(cur)
        for line in lines:
            draw.text((col_left_x1 + 22, ing_y), line, font=f_ing, fill=(255, 255, 255))
            ing_y += 29
        ing_y += 3

    # Steps
    step_y = col_y_start + 60
    for idx, step in enumerate(steps[:5], 1):
        prefix = f"{idx}. "
        draw.text((col_right_x1, step_y), prefix, font=f_step_num, fill=palette.accent_pill)
        words = step.strip().split()
        lines, cur = [], ""
        for w in words:
            cand = f"{cur} {w}".strip()
            if cur and draw.textbbox((0, 0), cand, font=f_step)[2] > (col_right_w - 35):
                lines.append(cur)
                cur = w
            else:
                cur = cand
        if cur:
            lines.append(cur)
        for line in lines:
            draw.text((col_right_x1 + 26, step_y), line, font=f_step, fill=(255, 255, 255))
            step_y += 28
        step_y += 8

    # Footer
    f_footer = get_font("Poppins-SemiBold.ttf", 19)
    fb = draw.textbbox((0, 0), domain_text, font=f_footer)
    draw.text(((PIN_W - (fb[2] - fb[0])) // 2, 1460), domain_text, font=f_footer, fill=(230, 225, 215, 190))

    stem = src.stem.replace("-hero", "")
    target_dir = output_dir or src.parent
    target_dir.mkdir(parents=True, exist_ok=True)
    out_path = Path(output_path) if output_path else (target_dir / f"{stem}-infographic-pin-fullbleed.jpg")
    canvas.convert("RGB").save(str(out_path), "JPEG", quality=95)

    return {
        "success": True,
        "output_path": str(out_path),
        "variant_used": "full_bleed",
        "theme": palette.name,
        "dimensions": f"{PIN_W}x{PIN_H}",
    }


# ── Unified Public Generator ───────────────────────────────────────────────


def create_recipe_infographic_pin(
    hero_image_path: str,
    title: str,
    subtitle: str = "",
    ingredients: list[str] | None = None,
    steps: list[str] | None = None,
    tip_text: str = "",
    domain_handle: str = "",
    style_variant: str = "auto",
) -> dict[str, Any]:
    """Generate a Pinterest recipe pin (1000x1500).

    Supports both ingredients pin variants:
    - `bright_infographic`: Bright culinary paper aesthetic matching user reference.
    - `full_bleed`: Full-bleed food hero image with cinematic bottom vignette.
    - `auto`: Uses `bright_infographic` standard.
    """
    try:
        src = Path(hero_image_path)
        if not src.exists():
            return {"success": False, "error": f"Hero image not found: {hero_image_path}"}

        output_dir = src.parent
        if domain_handle:
            try:
                from rankstein.domain import get_registry

                d = get_registry().get(domain_handle)
                output_dir = d.output_dir
            except Exception as exc:
                logger.debug("Could not resolve domain handle %s: %s", domain_handle, exc)

        if style_variant in ("full_bleed", "warm_parchment", "classic"):
            return create_full_bleed_recipe_pin(
                hero_image_path=hero_image_path,
                title=title,
                subtitle=subtitle,
                ingredients=ingredients,
                steps=steps,
                tip_text=tip_text,
                domain_handle=domain_handle,
                output_dir=output_dir,
            )

        # Default to bright infographic
        return create_bright_infographic_pin(
            hero_image_path=hero_image_path,
            title=title,
            subtitle=subtitle,
            ingredients=ingredients,
            steps=steps,
            tip_text=tip_text,
            domain_handle=domain_handle,
            output_dir=output_dir,
        )

    except Exception as e:
        logger.error("create_recipe_infographic_pin failed: %s", e, exc_info=True)
        return {"success": False, "error": str(e)}
