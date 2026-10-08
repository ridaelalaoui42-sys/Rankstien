"""Infographic-style Pinterest recipe pin generator — V2 (Premium).

Produces 1000x1500 vertical pins with:
- Blurred hero image as full-bleed background
- Frosted glass / stylized card overlays
- Rich typography with decorative title
- Two-column Ingredientes + Preparación in styled cards
- Hero food photograph (sharp, framed)
- Optional "Tip saludable" card
- Domain-aware branding
- 3 style variants auto-selected by recipe keyword

Dependencies: Pillow only.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger("rankstein.recipe_pin")

PIN_W, PIN_H = 1000, 1500
MARGIN = 35


# ── Style variants ────────────────────────────────────────────────────────


@dataclass(frozen=True)
class PinStyle:
    name: str

    # Background overlay gradient (top RGBA, bottom RGBA)
    overlay_top: tuple[int, int, int, int]
    overlay_bottom: tuple[int, int, int, int]

    # Card styling
    card_bg: tuple[int, int, int, int]  # frosted card fill
    card_border: str  # card border color
    card_shadow: tuple[int, int, int, int]  # drop shadow RGBA
    card_radius: int

    # Title
    title_color: str
    title_shadow: tuple[int, int, int, int]  # text shadow
    subtitle_color: str

    # Column headers
    col_header_bg: str
    col_header_fg: str
    col_header_radius: int

    # Column body
    col_body_fg: str
    col_bullet_color: str
    col_step_number_bg: str
    col_step_number_fg: str

    # Dividers / ornaments
    divider_color: str
    ornament_color: str

    # Tip card
    tip_bg: tuple[int, int, int, int]
    tip_border: str
    tip_header_color: str
    tip_body_color: str

    # Hero photo frame
    hero_border: str
    hero_shadow: tuple[int, int, int, int]

    # Brand / CTA
    brand_color: str
    cta_bg: str
    cta_fg: str
    cta_radius: int

    # Trigger keywords for auto-selection
    trigger_keywords: tuple[str, ...] = field(default_factory=tuple)


STYLE_WARM_PARCHMENT = PinStyle(
    name="warm_parchment",
    overlay_top=(60, 35, 15, 160),
    overlay_bottom=(40, 25, 10, 200),
    card_bg=(255, 250, 240, 210),
    card_border="#C9A96E",
    card_shadow=(40, 25, 10, 100),
    card_radius=14,
    title_color="#FFFFFF",
    title_shadow=(60, 35, 10, 200),
    subtitle_color="#F5E6C8",
    col_header_bg="#8B6914",
    col_header_fg="#FFFFFF",
    col_header_radius=8,
    col_body_fg="#3D2B1F",
    col_bullet_color="#C67B3C",
    col_step_number_bg="#C67B3C",
    col_step_number_fg="#FFFFFF",
    divider_color="#D4AF37",
    ornament_color="#C9A96E",
    tip_bg=(255, 248, 230, 220),
    tip_border="#D4AF37",
    tip_header_color="#8B6914",
    tip_body_color="#5C3310",
    hero_border="#D4AF37",
    hero_shadow=(30, 20, 5, 120),
    brand_color="#F5E6C8",
    cta_bg="#E60023",
    cta_fg="#FFFFFF",
    cta_radius=25,
    trigger_keywords=(
        "pan",
        "bizcocho",
        "tarta",
        "pastel",
        "galleta",
        "horno",
        "tradicional",
        "abuela",
        "casero",
        "clasic",
        "cocina",
        "arroz",
        "tortilla",
        "guiso",
        "estofado",
        "sopa",
        "empanada",
        "croqueta",
        "patata",
        "albondiga",
    ),
)

STYLE_ELEGANT_DARK = PinStyle(
    name="elegant_dark",
    overlay_top=(15, 12, 10, 180),
    overlay_bottom=(10, 8, 5, 220),
    card_bg=(35, 30, 28, 220),
    card_border="#D4AF37",
    card_shadow=(0, 0, 0, 140),
    card_radius=12,
    title_color="#F5E6C8",
    title_shadow=(0, 0, 0, 220),
    subtitle_color="#D4AF37",
    col_header_bg="#D4AF37",
    col_header_fg="#1a1a1a",
    col_header_radius=8,
    col_body_fg="#E8E0D0",
    col_bullet_color="#D4AF37",
    col_step_number_bg="#D4AF37",
    col_step_number_fg="#1a1a1a",
    divider_color="#8B7D3C",
    ornament_color="#D4AF37",
    tip_bg=(50, 45, 38, 230),
    tip_border="#D4AF37",
    tip_header_color="#D4AF37",
    tip_body_color="#E8E0D0",
    hero_border="#D4AF37",
    hero_shadow=(0, 0, 0, 160),
    brand_color="#D4AF37",
    cta_bg="#D4AF37",
    cta_fg="#1a1a1a",
    cta_radius=25,
    trigger_keywords=(
        "chocolate",
        "trufa",
        "brownie",
        "fondant",
        "mousse",
        "gourmet",
        "lujo",
        "premium",
        "noir",
        "cacao",
        "vino",
        "champagne",
        "cocktail",
        "maridaje",
        "wagyu",
        "foie",
        "tartar",
    ),
)

STYLE_FRESH_GREEN = PinStyle(
    name="fresh_green",
    overlay_top=(20, 45, 15, 150),
    overlay_bottom=(15, 35, 10, 190),
    card_bg=(240, 250, 235, 215),
    card_border="#6B8E23",
    card_shadow=(15, 35, 10, 100),
    card_radius=14,
    title_color="#FFFFFF",
    title_shadow=(20, 50, 10, 200),
    subtitle_color="#C8E6B0",
    col_header_bg="#4A7C28",
    col_header_fg="#FFFFFF",
    col_header_radius=8,
    col_body_fg="#2F4F2F",
    col_bullet_color="#4A7C28",
    col_step_number_bg="#4A7C28",
    col_step_number_fg="#FFFFFF",
    divider_color="#8FBC8F",
    ornament_color="#6B8E23",
    tip_bg=(235, 248, 225, 225),
    tip_border="#6B8E23",
    tip_header_color="#2D5016",
    tip_body_color="#2F4F2F",
    hero_border="#6B8E23",
    hero_shadow=(15, 35, 10, 120),
    brand_color="#C8E6B0",
    cta_bg="#E60023",
    cta_fg="#FFFFFF",
    cta_radius=25,
    trigger_keywords=(
        "ensalada",
        "verdura",
        "vegetal",
        "saludable",
        "fresco",
        "aguacate",
        "pepino",
        "tomate",
        "lechuga",
        "espinaca",
        "smoothie",
        "batido",
        "detox",
        "light",
        "integral",
        "mediterraneo",
        "mediterránea",
        "hummus",
        "garbanzo",
        "quinoa",
        "legumbre",
        "lenteja",
    ),
)

ALL_STYLES: tuple[PinStyle, ...] = (
    STYLE_WARM_PARCHMENT,
    STYLE_ELEGANT_DARK,
    STYLE_FRESH_GREEN,
)


def select_variant_for_keyword(keyword: str) -> PinStyle:
    kw = (keyword or "").lower()
    for style in ALL_STYLES:
        if any(trigger in kw for trigger in style.trigger_keywords):
            return style
    return STYLE_WARM_PARCHMENT


# ── Font helpers ──────────────────────────────────────────────────────────

_FONT_CACHE: dict[tuple[str, int], object] = {}
_WIN_FONTS = Path("C:/Windows/Fonts")
_ASSET_FONTS = Path(__file__).resolve().parent / "assets" / "fonts"

_FONT_MAP = {
    "script": (
        _ASSET_FONTS / "DancingScript-Bold.ttf",
        _ASSET_FONTS / "Pacifico-Regular.ttf",
        _ASSET_FONTS / "Caveat-Bold.ttf",
        _ASSET_FONTS / "Playball-Regular.ttf",
        _WIN_FONTS / "BRUSHSCI.TTF",
        _WIN_FONTS / "segoescb.ttf",
    ),
    "title": (
        _ASSET_FONTS / "DancingScript-Bold.ttf",
        _ASSET_FONTS / "Pacifico-Regular.ttf",
        _ASSET_FONTS / "Caveat-Bold.ttf",
        _WIN_FONTS / "georgiab.ttf",
        _WIN_FONTS / "georgia.ttf",
    ),
    "subtitle": (
        _ASSET_FONTS / "Caveat-Bold.ttf",
        _ASSET_FONTS / "DancingScript-Bold.ttf",
        _ASSET_FONTS / "Poppins-SemiBold.ttf",
        _WIN_FONTS / "georgiai.ttf",
    ),
    "header": (
        _ASSET_FONTS / "Poppins-SemiBold.ttf",
        _ASSET_FONTS / "Montserrat-Bold.ttf",
        _WIN_FONTS / "arialbd.ttf",
    ),
    "body": (
        _ASSET_FONTS / "Poppins-Regular.ttf",
        _WIN_FONTS / "arial.ttf",
        _WIN_FONTS / "georgia.ttf",
    ),
    "body_bold": (
        _ASSET_FONTS / "Poppins-SemiBold.ttf",
        _ASSET_FONTS / "Montserrat-Bold.ttf",
        _WIN_FONTS / "arialbd.ttf",
    ),
    "italic": (
        _ASSET_FONTS / "Caveat-Bold.ttf",
        _WIN_FONTS / "georgiai.ttf",
        _WIN_FONTS / "ariali.ttf",
    ),
    "brand": (
        _ASSET_FONTS / "Montserrat-Bold.ttf",
        _ASSET_FONTS / "Poppins-SemiBold.ttf",
        _WIN_FONTS / "arialbd.ttf",
    ),
    "cta": (
        _ASSET_FONTS / "Montserrat-Bold.ttf",
        _ASSET_FONTS / "Poppins-SemiBold.ttf",
        _WIN_FONTS / "arialbd.ttf",
    ),
}


def _font(role: str, size: int):
    from PIL import ImageFont

    key = (role, size)
    if key in _FONT_CACHE:
        return _FONT_CACHE[key]
    for p in _FONT_MAP.get(role, (_WIN_FONTS / "arial.ttf",)):
        try:
            f = ImageFont.truetype(str(p), size)
            _FONT_CACHE[key] = f
            return f
        except OSError:
            continue
    f = ImageFont.load_default(size=max(10, size // 2))
    _FONT_CACHE[key] = f
    return f


# ── Drawing primitives ───────────────────────────────────────────────────


def _rounded_rect(draw, xy, radius, fill=None, outline=None, width=1):
    try:
        draw.rounded_rectangle(xy, radius=radius, fill=fill, outline=outline, width=width)
    except AttributeError:
        draw.rectangle(xy, fill=fill, outline=outline, width=width)


def _draw_card(canvas, draw, xy, radius, fill, border_color, shadow_color, shadow_offset=6):
    """Draw a stylized card with drop shadow, fill, and border."""
    from PIL import Image, ImageFilter
    from PIL import ImageDraw as ID

    x1, y1, x2, y2 = xy
    w, h = x2 - x1, y2 - y1

    # Soft shadow
    if shadow_color[3] > 0:
        sh = Image.new("RGBA", (w + 20, h + 20), (0, 0, 0, 0))
        sh_draw = ID.Draw(sh)
        _rounded_rect(sh_draw, [10, 10, w + 10, h + 10], radius + 2, fill=shadow_color)
        sh = sh.filter(ImageFilter.GaussianBlur(8))
        canvas.paste(sh, (x1 - 10 + shadow_offset, y1 - 10 + shadow_offset), sh)

    # Card fill
    _rounded_rect(draw, xy, radius, fill=fill)

    # Border
    if border_color:
        _rounded_rect(draw, xy, radius, outline=border_color, width=2)


def _gradient_overlay(canvas, top_rgba, bottom_rgba):
    """Apply a vertical gradient overlay on the canvas."""
    from PIL import Image

    overlay = Image.new("RGBA", (PIN_W, PIN_H), (0, 0, 0, 0))
    pixels = overlay.load()
    for y in range(PIN_H):
        t = y / PIN_H
        r = int(top_rgba[0] * (1 - t) + bottom_rgba[0] * t)
        g = int(top_rgba[1] * (1 - t) + bottom_rgba[1] * t)
        b = int(top_rgba[2] * (1 - t) + bottom_rgba[2] * t)
        a = int(top_rgba[3] * (1 - t) + bottom_rgba[3] * t)
        for x in range(PIN_W):
            pixels[x, y] = (r, g, b, a)
    return Image.alpha_composite(canvas, overlay)


def _ornament_line(draw, y, x1, x2, color):
    mid = (x1 + x2) // 2
    draw.line([(x1, y), (mid - 15, y)], fill=color, width=2)
    draw.line([(mid + 15, y), (x2, y)], fill=color, width=2)
    draw.polygon([(mid, y - 5), (mid + 5, y), (mid, y + 5), (mid - 5, y)], fill=color)


def _wrap(text, font, max_w, draw):
    words = text.split()
    lines, cur = [], ""
    for w in words:
        test = f"{cur} {w}".strip()
        if draw.textbbox((0, 0), test, font=font)[2] > max_w and cur:
            lines.append(cur)
            cur = w
        else:
            cur = test
    if cur:
        lines.append(cur)
    return lines


def _text_shadow(draw, xy, text, font, fill, shadow_color, offset=2):
    """Draw text with a soft shadow behind it."""
    x, y = xy
    # Shadow pass
    draw.text((x + offset, y + offset), text, font=font, fill=shadow_color)
    # Main text
    draw.text((x, y), text, font=font, fill=fill)


# ── Main generator ────────────────────────────────────────────────────────


def create_recipe_infographic_pin(
    hero_image_path: str,
    title: str,
    subtitle: str = "",
    ingredients: list[str] | None = None,
    steps: list[str] | None = None,
    tip_text: str = "",
    domain_handle: str = "",
    style_variant: str = "auto",
) -> dict:
    """Generate a premium infographic Pinterest recipe pin (1000x1500).

    Features blurred hero background, frosted glass cards, rich typography,
    and domain-aware branding with 3 auto-selected style variants.
    """
    try:
        from PIL import Image, ImageDraw, ImageFilter

        src = Path(hero_image_path)
        if not src.exists():
            return {"success": False, "error": f"Hero image not found: {hero_image_path}"}

        ingredients = ingredients or []
        steps = steps or []

        # ── Resolve domain branding ─────────────────────────────────
        brand_name = "RECETA GENIAL | 2026"
        cta_text = "¡GUARDA ESTA RECETA!"
        if domain_handle:
            try:
                from rankstein.domain import get_registry

                domain = get_registry().get(domain_handle)
                brand_name = getattr(domain, "brand_name_short", brand_name)
                cta_text = getattr(domain, "cta_text", cta_text)
            except Exception as e:
                logger.warning("Could not resolve domain %r: %s", domain_handle, e)

        # ── Select style ────────────────────────────────────────────
        if style_variant == "auto":
            style = select_variant_for_keyword(title)
        else:
            style = next((s for s in ALL_STYLES if s.name == style_variant), STYLE_WARM_PARCHMENT)

        # ── Load hero and build blurred background ──────────────────
        with Image.open(src) as hero_raw:
            if hero_raw.mode != "RGBA":
                hero_raw = hero_raw.convert("RGBA")

            # Blurred hero fills entire canvas
            bg = hero_raw.resize((PIN_W, PIN_H), Image.Resampling.LANCZOS)
            bg = bg.filter(ImageFilter.GaussianBlur(22))

            # Gradient overlay for depth and readability
            canvas = _gradient_overlay(bg, style.overlay_top, style.overlay_bottom)
            draw = ImageDraw.Draw(canvas)

            # ── Layout calculations ─────────────────────────────────
            y = MARGIN

            # ── TITLE CARD ──────────────────────────────────────────
            title_font = _font("title", 58)
            title_lines = _wrap(title, title_font, PIN_W - MARGIN * 2 - 60, draw)[:3]
            title_line_h = 65
            title_block_h = len(title_lines) * title_line_h
            sub_h = 40 if subtitle else 0
            title_card_h = title_block_h + sub_h + 50

            _draw_card(
                canvas,
                draw,
                [MARGIN, y, PIN_W - MARGIN, y + title_card_h],
                style.card_radius,
                fill=(0, 0, 0, 80),
                border_color=style.ornament_color,
                shadow_color=(0, 0, 0, 0),
            )

            # Ornamental top line
            _ornament_line(draw, y + 18, MARGIN + 60, PIN_W - MARGIN - 60, style.ornament_color)

            # Title text (centered, with shadow)
            ty = y + 30
            for line in title_lines:
                bb = draw.textbbox((0, 0), line, font=title_font)
                tw = bb[2] - bb[0]
                _text_shadow(
                    draw,
                    ((PIN_W - tw) // 2, ty),
                    line,
                    title_font,
                    style.title_color,
                    style.title_shadow,
                )
                ty += title_line_h

            # Subtitle
            if subtitle:
                sub_font = _font("subtitle", 28)
                sub_text = f"· {subtitle} ·"
                sb = draw.textbbox((0, 0), sub_text, font=sub_font)
                sw = sb[2] - sb[0]
                draw.text(((PIN_W - sw) // 2, ty + 2), sub_text, font=sub_font, fill=style.subtitle_color)

            # Bottom ornament
            _ornament_line(
                draw, y + title_card_h - 15, MARGIN + 60, PIN_W - MARGIN - 60, style.ornament_color
            )

            y += title_card_h + 12

            # ── TWO COLUMN CARDS (side by side) ─────────────────────
            col_gap = 14
            col_w = (PIN_W - MARGIN * 2 - col_gap) // 2
            left_x = MARGIN
            right_x = MARGIN + col_w + col_gap

            # Calculate column heights
            header_h = 46
            item_h = 35
            max_ing = min(len(ingredients), 12)
            max_steps = min(len(steps), 8)

            # Ingredients: fixed item height
            ing_content_h = max_ing * item_h + 15
            ing_card_h = header_h + ing_content_h + 24

            # Steps: variable height (multi-line)
            step_font = _font("body", 22)
            step_heights = []
            for s in steps[:max_steps]:
                lines = _wrap(s.strip(), step_font, col_w - 70, draw)
                step_heights.append(max(len(lines[:3]) * 27, 32))
            steps_content_h = sum(step_heights) + 15 if step_heights else 50
            steps_card_h = header_h + steps_content_h + 24

            # Make both cards same height
            col_card_h = max(ing_card_h, steps_card_h)

            # ── Ingredients card ────────────────────────────────────
            _draw_card(
                canvas,
                draw,
                [left_x, y, left_x + col_w, y + col_card_h],
                style.card_radius,
                fill=style.card_bg,
                border_color=style.card_border,
                shadow_color=style.card_shadow,
            )

            # Header bar
            hdr_y = y + 10
            _rounded_rect(
                draw,
                [left_x + 10, hdr_y, left_x + col_w - 10, hdr_y + header_h],
                style.col_header_radius,
                fill=style.col_header_bg,
            )
            hdr_font = _font("header", 24)
            hb = draw.textbbox((0, 0), "INGREDIENTES", font=hdr_font)
            hw = hb[2] - hb[0]
            draw.text(
                (left_x + (col_w - hw) // 2, hdr_y + 10),
                "INGREDIENTES",
                font=hdr_font,
                fill=style.col_header_fg,
            )

            # Ingredient items
            ing_font = _font("body", 23)
            ing_bullet_font = _font("body_bold", 20)
            iy = hdr_y + header_h + 14
            for ing in ingredients[:max_ing]:
                display = ing.strip()
                if len(display) > 34:
                    display = display[:32] + "…"
                # Colored bullet
                draw.text((left_x + 18, iy + 2), "●", font=ing_bullet_font, fill=style.col_bullet_color)
                draw.text((left_x + 42, iy), display, font=ing_font, fill=style.col_body_fg)
                iy += item_h

            # ── Preparación card ────────────────────────────────────
            _draw_card(
                canvas,
                draw,
                [right_x, y, right_x + col_w, y + col_card_h],
                style.card_radius,
                fill=style.card_bg,
                border_color=style.card_border,
                shadow_color=style.card_shadow,
            )

            # Header bar
            _rounded_rect(
                draw,
                [right_x + 10, hdr_y, right_x + col_w - 10, hdr_y + header_h],
                style.col_header_radius,
                fill=style.col_header_bg,
            )
            hb2 = draw.textbbox((0, 0), "PREPARACIÓN", font=hdr_font)
            hw2 = hb2[2] - hb2[0]
            draw.text(
                (right_x + (col_w - hw2) // 2, hdr_y + 10),
                "PREPARACIÓN",
                font=hdr_font,
                fill=style.col_header_fg,
            )

            # Step items with numbered circles
            sy = hdr_y + header_h + 14
            num_font = _font("body_bold", 16)
            for i, step in enumerate(steps[:max_steps]):
                step_text = step.strip()
                step_lines = _wrap(step_text, step_font, col_w - 70, draw)[:3]

                # Numbered circle
                cx = right_x + 26
                cy_c = sy + 12
                draw.ellipse(
                    [cx - 13, cy_c - 13, cx + 13, cy_c + 13],
                    fill=style.col_step_number_bg,
                )
                num = str(i + 1)
                nb = draw.textbbox((0, 0), num, font=num_font)
                nw = nb[2] - nb[0]
                draw.text((cx - nw // 2, cy_c - 9), num, font=num_font, fill=style.col_step_number_fg)

                # Step text
                for j, sl in enumerate(step_lines):
                    draw.text((right_x + 50, sy + j * 27), sl, font=step_font, fill=style.col_body_fg)
                sy += max(len(step_lines) * 27, 32) + 2

            y += col_card_h + 12

            # ── HERO PHOTO (sharp, framed) ──────────────────────────
            hero_w = PIN_W - MARGIN * 2
            remaining_h = PIN_H - y - 12  # space until bottom

            # Reserve space for tip + brand + cta
            tip_reserve = 110 if tip_text else 0
            brand_reserve = 90
            hero_h = remaining_h - tip_reserve - brand_reserve
            hero_h = max(180, min(hero_h, 480))

            # Crop hero to fill target rectangle
            img_ratio = hero_raw.width / hero_raw.height
            target_ratio = hero_w / hero_h
            if img_ratio > target_ratio:
                new_w = int(hero_raw.height * target_ratio)
                left = (hero_raw.width - new_w) // 2
                cropped = hero_raw.crop((left, 0, left + new_w, hero_raw.height))
            else:
                new_h = int(hero_raw.width / target_ratio)
                top = (hero_raw.height - new_h) // 4
                cropped = hero_raw.crop((0, top, hero_raw.width, top + new_h))

            hero_resized = cropped.resize((hero_w, hero_h), Image.Resampling.LANCZOS)

            hx = MARGIN
            hy = y

            # Shadow behind hero
            shadow = Image.new("RGBA", (hero_w + 12, hero_h + 12), style.hero_shadow)
            shadow = shadow.filter(ImageFilter.GaussianBlur(6))
            canvas.paste(shadow, (hx - 3, hy + 3), shadow)

            # White/accent border frame
            frame_pad = 4
            _rounded_rect(
                draw,
                [hx - frame_pad, hy - frame_pad, hx + hero_w + frame_pad, hy + hero_h + frame_pad],
                8,
                outline=style.hero_border,
                width=3,
            )

            # Paste sharp hero
            canvas.paste(hero_resized, (hx, hy), hero_resized)

            # Re-acquire draw after paste
            draw = ImageDraw.Draw(canvas)

            y = hy + hero_h + 12

            # ── TIP CARD ────────────────────────────────────────────
            if tip_text:
                tip_font_hdr = _font("header", 22)
                tip_font_body = _font("italic", 20)
                tip_lines = _wrap(tip_text, tip_font_body, PIN_W - MARGIN * 2 - 70, draw)[:2]
                tip_card_h = 34 + len(tip_lines) * 26 + 14

                _draw_card(
                    canvas,
                    draw,
                    [MARGIN, y, PIN_W - MARGIN, y + tip_card_h],
                    10,
                    fill=style.tip_bg,
                    border_color=style.tip_border,
                    shadow_color=(0, 0, 0, 50),
                    shadow_offset=3,
                )

                # Lightbulb icon + header
                draw.text((MARGIN + 14, y + 8), "💡", font=_font("body", 20))
                draw.text(
                    (MARGIN + 42, y + 8), "Tip saludable:", font=tip_font_hdr, fill=style.tip_header_color
                )

                for i, tl in enumerate(tip_lines):
                    draw.text(
                        (MARGIN + 18, y + 36 + i * 26),
                        tl,
                        font=tip_font_body,
                        fill=style.tip_body_color,
                    )

                y += tip_card_h + 8

            # ── BRAND + CTA ─────────────────────────────────────────
            # Ornamental separator
            _ornament_line(draw, y, MARGIN + 50, PIN_W - MARGIN - 50, style.ornament_color)
            y += 14

            # Brand name
            brand_font = _font("brand", 22)
            brand_display = f"—— {brand_name} ——"
            bb = draw.textbbox((0, 0), brand_display, font=brand_font)
            bw = bb[2] - bb[0]
            draw.text(((PIN_W - bw) // 2, y), brand_display, font=brand_font, fill=style.brand_color)
            y += bb[3] - bb[1] + 10

            # CTA pill button
            cta_font = _font("cta", 22)
            cb = draw.textbbox((0, 0), cta_text, font=cta_font)
            cta_w = cb[2] - cb[0] + 50
            cta_h = cb[3] - cb[1] + 18
            cta_x = (PIN_W - cta_w) // 2
            cta_y = min(y, PIN_H - MARGIN - cta_h - 5)

            # CTA shadow
            _rounded_rect(
                draw,
                [cta_x + 2, cta_y + 2, cta_x + cta_w + 2, cta_y + cta_h + 2],
                style.cta_radius,
                fill=(0, 0, 0, 60),
            )
            _rounded_rect(
                draw,
                [cta_x, cta_y, cta_x + cta_w, cta_y + cta_h],
                style.cta_radius,
                fill=style.cta_bg,
            )
            draw.text(
                ((PIN_W - (cb[2] - cb[0])) // 2, cta_y + 7),
                cta_text,
                font=cta_font,
                fill=style.cta_fg,
            )

        # ── Save ────────────────────────────────────────────────────
        stem = src.stem.replace("-hero", "")
        output_dir = src.parent
        if domain_handle:
            try:
                from rankstein.domain import get_registry

                d = get_registry().get(domain_handle)
                output_dir = d.output_dir
                output_dir.mkdir(parents=True, exist_ok=True)
            except Exception as e:
                logger.debug("Falling back to source image directory for domain %s: %s", domain_handle, e)

        out_path = output_dir / f"{stem}-infographic-pin-{style.name}.jpg"
        canvas.convert("RGB").save(str(out_path), "JPEG", quality=95)

        logger.info(
            "Created infographic pin V2: %s (variant=%s, domain=%s)",
            out_path.name,
            style.name,
            domain_handle or "default",
        )
        return {
            "success": True,
            "output_path": str(out_path),
            "variant_used": style.name,
            "domain": domain_handle or "auto",
            "dimensions": f"{PIN_W}x{PIN_H}",
        }

    except Exception as e:
        logger.error("create_recipe_infographic_pin failed: %s", e, exc_info=True)
        return {"success": False, "error": str(e)}
