"""Domain-aware Pinterest variants produced from one accepted food image.

Every accepted source yields the same explicit pair:

1. ``viral_visual`` — an image-led save/click creative.
2. ``recipe_card`` — a readable ingredients and preparation infographic.

Both outputs are deterministic 1000x1500 JPEGs.  The compositor adds all
text; source-image branding or model-rendered text is never reused.
"""

from __future__ import annotations

import logging
import re
import textwrap
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont

PIN_WIDTH = 1000
PIN_HEIGHT = 1500
_FONT_ROOT = Path("C:/Windows/Fonts")
_ASSET_FONTS = Path(__file__).resolve().parent / "assets" / "fonts"
logger = logging.getLogger("rankstein.remaster_variants")


@dataclass(frozen=True)
class DomainPinTheme:
    handle: str
    display_name: str
    public_domain: str
    brand_name: str
    primary: str
    accent: str
    cta: str


@dataclass(frozen=True)
class _RecipeItemLayout:
    text: str
    lines: tuple[str, ...]
    y: int
    height: int


@dataclass(frozen=True)
class _RecipeCardLayout:
    hero_height: int
    content_left: int
    content_right: int
    ingredients_header_y: int
    ingredients_rule_y: int
    ingredient_items: tuple[_RecipeItemLayout, ...]
    preparation_header_y: int
    preparation_rule_y: int
    step_items: tuple[_RecipeItemLayout, ...]
    body_font: ImageFont.FreeTypeFont
    number_font: ImageFont.FreeTypeFont
    section_font: ImageFont.FreeTypeFont
    line_height: int
    tip_lines: tuple[str, ...]
    tip_y: int | None
    tip_height: int
    content_bottom: int


def _theme_for_domain(domain_handle: str) -> DomainPinTheme:
    from rankstein.domain import get_registry

    domain = get_registry().get(domain_handle)
    return DomainPinTheme(
        handle=domain.handle,
        display_name=domain.display_name,
        public_domain=domain.domain,
        brand_name=getattr(domain, "brand_name_short", "") or domain.display_name.upper(),
        primary=getattr(domain, "primary_color", "#C67B3C"),
        accent=getattr(domain, "accent_color", "#2C3E50"),
        cta=getattr(domain, "cta_text", "GUARDA ESTA RECETA"),
    )


def _safe_slug(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value or "")
    normalized = "".join(char for char in normalized if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9]+", "-", normalized.lower()).strip("-") or "recipe"


def _font(
    size: int,
    *,
    bold: bool = False,
    serif: bool = False,
    script: bool = False,
    sans: bool = False,
) -> ImageFont.FreeTypeFont:
    if script:
        candidates = (
            _ASSET_FONTS / "DancingScript-Bold.ttf",
            _ASSET_FONTS / "Pacifico-Regular.ttf",
            _ASSET_FONTS / "Caveat-Bold.ttf",
            _ASSET_FONTS / "Playball-Regular.ttf",
            _FONT_ROOT / "BRUSHSCI.TTF",
            _FONT_ROOT / "segoescb.ttf",
            _FONT_ROOT / "segoesc.ttf",
        )
    elif serif:
        candidates = (
            (
                _ASSET_FONTS / "DMSerifDisplay-Regular.ttf",
                _ASSET_FONTS / "PlayfairDisplay.ttf",
                _ASSET_FONTS / "Prata-Regular.ttf",
                _FONT_ROOT / "georgiab.ttf",
                _FONT_ROOT / "georgia.ttf",
            )
            if bold
            else (
                _ASSET_FONTS / "DMSerifDisplay-Regular.ttf",
                _ASSET_FONTS / "PlayfairDisplay.ttf",
                _FONT_ROOT / "georgia.ttf",
                _FONT_ROOT / "times.ttf",
            )
        )
    elif sans or not serif:
        candidates = (
            (
                _ASSET_FONTS / "Poppins-SemiBold.ttf",
                _ASSET_FONTS / "Montserrat-Bold.ttf",
                _FONT_ROOT / "arialbd.ttf",
                _FONT_ROOT / "segoeuib.ttf",
            )
            if bold
            else (
                _ASSET_FONTS / "Poppins-Regular.ttf",
                _FONT_ROOT / "arial.ttf",
                _FONT_ROOT / "segoeui.ttf",
            )
        )
    else:
        candidates = (_FONT_ROOT / "arial.ttf",)

    for path in candidates:
        try:
            return ImageFont.truetype(str(path), size)
        except OSError:
            continue
    return ImageFont.load_default(size=max(12, size // 2))


def _hex_rgb(value: str, fallback: tuple[int, int, int]) -> tuple[int, int, int]:
    match = re.fullmatch(r"#?([0-9a-fA-F]{6})", (value or "").strip())
    if not match:
        return fallback
    raw = match.group(1)
    return tuple(int(raw[index : index + 2], 16) for index in (0, 2, 4))


def _contrast_text(background: tuple[int, int, int]) -> tuple[int, int, int]:
    luminance = (0.299 * background[0]) + (0.587 * background[1]) + (0.114 * background[2])
    return (20, 20, 20) if luminance > 165 else (255, 255, 255)


def _cover(image: Image.Image, width: int, height: int, *, focus_y: float = 0.42) -> Image.Image:
    source = image.convert("RGB")
    target_ratio = width / height
    source_ratio = source.width / source.height
    if source_ratio > target_ratio:
        crop_width = max(1, int(source.height * target_ratio))
        left = max(0, (source.width - crop_width) // 2)
        source = source.crop((left, 0, left + crop_width, source.height))
    else:
        crop_height = max(1, int(source.width / target_ratio))
        room = max(0, source.height - crop_height)
        top = max(0, min(room, int(room * focus_y)))
        source = source.crop((0, top, source.width, top + crop_height))
    return source.resize((width, height), Image.Resampling.LANCZOS)


def _fit_lines(
    draw: ImageDraw.ImageDraw,
    text: str,
    *,
    max_width: int,
    max_lines: int,
    preferred_size: int,
    minimum_size: int,
    bold: bool = False,
    serif: bool = False,
    script: bool = False,
    sans: bool = False,
) -> tuple[ImageFont.FreeTypeFont, list[str]]:
    clean = re.sub(r"\s+", " ", text or "").strip()
    for size in range(preferred_size, minimum_size - 1, -2):
        font = _font(size, bold=bold, serif=serif, script=script, sans=sans)
        words = clean.split()
        lines: list[str] = []
        current = ""
        for word in words:
            candidate = f"{current} {word}".strip()
            if current and draw.textbbox((0, 0), candidate, font=font)[2] > max_width:
                lines.append(current)
                current = word
            else:
                current = candidate
        if current:
            lines.append(current)
        if len(lines) <= max_lines:
            return font, lines
    font = _font(minimum_size, bold=bold, serif=serif, script=script, sans=sans)
    wrapped = textwrap.wrap(clean, width=max(16, int(max_width / max(1, minimum_size * 0.55))))
    lines = wrapped[:max_lines]
    if len(wrapped) > max_lines and lines:
        lines[-1] = lines[-1].rstrip(" .") + "…"
    return font, lines


def _draw_centered_lines(
    draw: ImageDraw.ImageDraw,
    lines: list[str],
    font: ImageFont.FreeTypeFont,
    *,
    center_x: int,
    y: int,
    fill: tuple[int, int, int],
    spacing: int,
    shadow: bool = False,
) -> int:
    current_y = y
    for line in lines:
        box = draw.textbbox((0, 0), line, font=font)
        width = box[2] - box[0]
        x = center_x - width // 2
        if shadow:
            draw.text((x + 3, current_y + 4), line, font=font, fill=(0, 0, 0, 145))
        draw.text((x, current_y), line, font=font, fill=fill)
        current_y += (box[3] - box[1]) + spacing
    return current_y


def _save(canvas: Image.Image, output_path: Path) -> dict:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.convert("RGB").save(output_path, "JPEG", quality=94, optimize=True)
    return {
        "success": True,
        "output_path": str(output_path),
        "width": PIN_WIDTH,
        "height": PIN_HEIGHT,
        "size_bytes": output_path.stat().st_size,
    }


def create_viral_visual_pin(
    *,
    source_path: str,
    title: str,
    domain_handle: str,
    pair_id: str,
    output_dir: Path,
    subtitle: str = "",
    cta_text: str = "",
) -> dict:
    """Create the image-led sibling of a remaster pair (visual-first standard: LESS TEXT, MORE IMAGE)."""

    source = Path(source_path)
    if not source.is_file():
        return {"success": False, "error": f"Source image not found: {source_path}"}
    try:
        theme = _theme_for_domain(domain_handle)
        primary = _hex_rgb(theme.primary, (198, 123, 60))
        accent = _hex_rgb(theme.accent, (44, 62, 80))
        with Image.open(source) as raw:
            photo = _cover(raw, PIN_WIDTH, PIN_HEIGHT, focus_y=0.38)
        photo = ImageEnhance.Contrast(photo).enhance(1.05)
        photo = ImageEnhance.Color(photo).enhance(1.06).convert("RGBA")

        # Full-bleed canvas: leaves 70% of food photography completely pure and clear
        overlay = Image.new("RGBA", (PIN_WIDTH, PIN_HEIGHT), (0, 0, 0, 0))
        overlay_draw = ImageDraw.Draw(overlay)
        for y in range(PIN_HEIGHT):
            if y < 110:
                alpha = int(40 * (1 - y / 110))
            elif y > 1020:
                alpha = min(180, int(((y - 1020) / 480) ** 1.35 * 180))
            else:
                alpha = 0
            if alpha > 0:
                overlay_draw.line((0, y, PIN_WIDTH, y), fill=(12, 10, 8, alpha))
        canvas = Image.alpha_composite(photo, overlay)
        draw = ImageDraw.Draw(canvas, "RGBA")

        # Floating brand pill at top (takes <1% of area, preserves 99% of top photo)
        brand_font = _font(22, bold=True, sans=True)
        brand_label = theme.public_domain.upper()
        brand_box = draw.textbbox((0, 0), brand_label, font=brand_font)
        badge_width = brand_box[2] - brand_box[0] + 44
        badge_x = (PIN_WIDTH - badge_width) // 2
        badge_y = 38
        draw.rounded_rectangle(
            (badge_x, badge_y, badge_x + badge_width, badge_y + 40),
            radius=20,
            fill=(15, 15, 15, 160),
            outline=(*primary, 220),
            width=1,
        )
        draw.text(
            (badge_x + 22, badge_y + 9),
            brand_label,
            font=brand_font,
            fill=(255, 255, 255, 240),
        )

        # Lower-third kicker tag (concise, high-impact)
        kicker_font = _font(21, bold=True, sans=True)
        kicker = subtitle.strip().upper() if subtitle else "RECETA CASERA"
        if len(kicker) > 36:
            kicker = kicker[:34] + "…"
        kw = draw.textbbox((0, 0), kicker, font=kicker_font)
        kicker_w = kw[2] - kw[0] + 30
        kicker_x = (PIN_WIDTH - kicker_w) // 2
        kicker_y = 1060
        draw.rounded_rectangle(
            (kicker_x, kicker_y, kicker_x + kicker_w, kicker_y + 34),
            radius=17,
            fill=(*primary, 225),
        )
        draw.text((kicker_x + 15, kicker_y + 7), kicker, font=kicker_font, fill=_contrast_text(primary))

        # Hook-driven title (visual artisanal script with soft shadow over lower-third gradient)
        title_font, title_lines = _fit_lines(
            draw,
            title,
            max_width=880,
            max_lines=2,
            preferred_size=86,
            minimum_size=52,
            bold=True,
            script=True,
        )
        title_end = _draw_centered_lines(
            draw,
            title_lines,
            title_font,
            center_x=PIN_WIDTH // 2,
            y=1120,
            fill=(255, 255, 255),
            spacing=8,
            shadow=True,
        )

        # Minimal save badge / CTA pill
        cta = (
            cta_text.strip().upper()
            if cta_text
            else (theme.cta.strip().upper() if theme.cta else "GUARDAR RECETA")
        )
        if len(cta) > 28:
            cta = "GUARDAR RECETA"
        cta_font = _font(22, bold=True, sans=True)
        cta_box = draw.textbbox((0, 0), cta, font=cta_font)
        cta_width = min(600, cta_box[2] - cta_box[0] + 50)
        cta_y = min(1385, max(1300, title_end + 26))
        cta_x = (PIN_WIDTH - cta_width) // 2
        draw.rounded_rectangle(
            (cta_x, cta_y, cta_x + cta_width, cta_y + 48),
            radius=24,
            fill=(*accent, 225),
            outline=(*primary, 200),
            width=1,
        )
        text_width = cta_box[2] - cta_box[0]
        draw.text(
            ((PIN_WIDTH - text_width) // 2, cta_y + 12),
            cta,
            font=cta_font,
            fill=_contrast_text(accent),
        )

        # Subtle clean domain baseline at very bottom
        footer_font = _font(19, bold=False, sans=True)
        footer = f"{theme.brand_name} • {theme.public_domain}"
        footer_box = draw.textbbox((0, 0), footer, font=footer_font)
        draw.text(
            ((PIN_WIDTH - (footer_box[2] - footer_box[0])) // 2, 1455),
            footer,
            font=footer_font,
            fill=(220, 220, 220, 180),
        )

        output_path = output_dir / f"{_safe_slug(title)}-{pair_id}-viral-visual.jpg"
        result = _save(canvas, output_path)
        result.update({"variant": "viral_visual", "variant_label": "Viral visual"})
        return result
    except Exception as exc:
        return {"success": False, "error": str(exc), "variant": "viral_visual"}


def _clean_recipe_items(values: list[str], *, limit: int) -> list[str]:
    cleaned: list[str] = []
    for value in values:
        text = re.sub(r"\s+", " ", str(value or "")).strip(" -•\t")
        normalized = unicodedata.normalize("NFKD", text)
        normalized = (
            "".join(character for character in normalized if not unicodedata.combining(character))
            .lower()
            .strip(" .")
        )
        if (
            not text
            or re.fullmatch(r"ingrediente(?: principal)?(?: \d+)?", normalized)
            or re.fullmatch(r"paso(?: \d+)?", normalized)
            or normalized in {"mezclar y servir", "cocina la base", "preparar la receta"}
        ):
            continue
        cleaned.append(text)
        if len(cleaned) >= limit:
            break
    return cleaned


def _text_width(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont) -> int:
    box = draw.textbbox((0, 0), text, font=font)
    return box[2] - box[0]


def _wrap_recipe_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    *,
    font: ImageFont.FreeTypeFont,
    max_width: int,
) -> tuple[str, ...]:
    """Wrap all recipe text by rendered pixels without dropping content."""

    clean = re.sub(r"\s+", " ", text or "").strip()
    if not clean:
        return ()

    tokens: list[str] = []
    for word in clean.split():
        if _text_width(draw, word, font) <= max_width:
            tokens.append(word)
            continue

        chunk = ""
        for character in word:
            candidate = f"{chunk}{character}"
            if chunk and _text_width(draw, candidate, font) > max_width:
                tokens.append(chunk)
                chunk = character
            else:
                chunk = candidate
        if chunk:
            tokens.append(chunk)

    lines: list[str] = []
    current = ""
    for token in tokens:
        candidate = f"{current} {token}".strip()
        if current and _text_width(draw, candidate, font) > max_width:
            lines.append(current)
            current = token
        else:
            current = candidate
    if current:
        lines.append(current)
    return tuple(lines)


def _recipe_card_layout(
    draw: ImageDraw.ImageDraw,
    *,
    ingredient_items: list[str],
    step_items: list[str],
    tip_text: str,
) -> _RecipeCardLayout | None:
    """Choose the largest readable layout that keeps all required text on-canvas."""

    content_left = 58
    content_right = 942
    content_bottom = 1376
    ingredient_text_width = content_right - (content_left + 30)
    step_text_width = content_right - (content_left + 57)

    for body_size in range(23, 13, -1):
        body_font = _font(body_size, sans=True)
        number_font = _font(max(16, body_size - 1), bold=True, sans=True)
        section_font = _font(min(30, body_size + 7), bold=True, sans=True)
        sample_box = draw.textbbox((0, 0), "Ágj", font=body_font)
        line_height = max(body_size + 5, sample_box[3] + 3)
        section_box = draw.textbbox((0, 0), "INGREDIENTES", font=section_font)
        section_height = max(section_font.size + 4, section_box[3] + 2)

        ingredient_lines = [
            _wrap_recipe_text(draw, item, font=body_font, max_width=ingredient_text_width)
            for item in ingredient_items
        ]
        step_lines = [
            _wrap_recipe_text(draw, item, font=body_font, max_width=step_text_width) for item in step_items
        ]

        for hero_height in (500, 470, 440, 410, 380, 350, 320):
            y = hero_height + 52
            ingredients_header_y = y
            ingredients_rule_y = y + section_height + 5
            y = ingredients_rule_y + 15

            ingredient_layouts: list[_RecipeItemLayout] = []
            for text, lines in zip(ingredient_items, ingredient_lines, strict=True):
                height = max(24, len(lines) * line_height)
                ingredient_layouts.append(_RecipeItemLayout(text=text, lines=lines, y=y, height=height))
                y += height + 6

            y += 8
            preparation_header_y = y
            preparation_rule_y = y + section_height + 5
            y = preparation_rule_y + 15

            step_layouts: list[_RecipeItemLayout] = []
            for text, lines in zip(step_items, step_lines, strict=True):
                height = max(39, len(lines) * line_height)
                step_layouts.append(_RecipeItemLayout(text=text, lines=lines, y=y, height=height))
                y += height + 7

            if y > content_bottom:
                continue

            clean_tip = re.sub(r"\s+", " ", tip_text or "").strip()
            tip_lines: tuple[str, ...] = ()
            tip_y: int | None = None
            tip_height = 0
            if clean_tip:
                tip_font = _font(max(14, body_size - 1), sans=True)
                candidate_lines = _wrap_recipe_text(
                    draw,
                    f"Consejo: {clean_tip}",
                    font=tip_font,
                    max_width=(content_right - content_left) - 36,
                )
                tip_sample = draw.textbbox((0, 0), "Ágj", font=tip_font)
                tip_line_height = max(tip_font.size + 5, tip_sample[3] + 3)
                candidate_height = len(candidate_lines) * tip_line_height + 28
                candidate_y = y + 3
                if candidate_y + candidate_height <= content_bottom:
                    tip_lines = candidate_lines
                    tip_y = candidate_y
                    tip_height = candidate_height

            return _RecipeCardLayout(
                hero_height=hero_height,
                content_left=content_left,
                content_right=content_right,
                ingredients_header_y=ingredients_header_y,
                ingredients_rule_y=ingredients_rule_y,
                ingredient_items=tuple(ingredient_layouts),
                preparation_header_y=preparation_header_y,
                preparation_rule_y=preparation_rule_y,
                step_items=tuple(step_layouts),
                body_font=body_font,
                number_font=number_font,
                section_font=section_font,
                line_height=line_height,
                tip_lines=tip_lines,
                tip_y=tip_y,
                tip_height=tip_height,
                content_bottom=content_bottom,
            )

    return None


def _footer_layout(
    draw: ImageDraw.ImageDraw,
    *,
    brand_name: str,
    cta: str,
) -> tuple[ImageFont.FreeTypeFont, tuple[str, ...]] | None:
    """Fit optional footer copy in at most two complete centered lines."""

    candidates = (f"{brand_name}  •  {cta}", brand_name)
    for candidate in candidates:
        for size in range(23, 15, -1):
            font = _font(size, bold=True, sans=True)
            lines = _wrap_recipe_text(draw, candidate, font=font, max_width=920)
            if len(lines) <= 2:
                sample_box = draw.textbbox((0, 0), "Ágj", font=font)
                line_height = max(font.size + 4, sample_box[3] + 2)
                if len(lines) * line_height <= 76:
                    return font, lines
    return None


def create_recipe_card_pin(
    *,
    source_path: str,
    title: str,
    ingredients: list[str],
    steps: list[str],
    tip_text: str,
    domain_handle: str,
    pair_id: str,
    output_dir: Path,
    subtitle: str = "",
    card_style: str = "auto",
) -> dict:
    """Create the visual recipe-card sibling matching the 2026 Pinterest reference standard.

    Features:
    - When card_style == 'bright_infographic': Bright culinary paper aesthetic with
      circular food hero, arched ribbons, 3-stat metrics card, and step cards.
    - When card_style in ('classic', 'full_bleed', 'auto'):
      100% full-bleed food hero photography with top floating ivory card,
      cinematic dark espresso bottom vignette, and two-column recipe layout.
    """

    source = Path(source_path)
    if not source.is_file():
        return {"success": False, "error": f"Source image not found: {source_path}"}
    ingredient_items = _clean_recipe_items(ingredients, limit=8)
    step_items = _clean_recipe_items(steps, limit=5)
    if not ingredient_items or not step_items:
        return {
            "success": False,
            "error": "Recipe-card variant requires real recipe ingredients and steps",
            "variant": "recipe_card",
        }

    output_path = output_dir / f"{_safe_slug(title)}-{pair_id}-recipe-card.jpg"

    if card_style == "bright_infographic":
        try:
            from rankstein.recipe_pin_generator import create_bright_infographic_pin

            info_res = create_bright_infographic_pin(
                hero_image_path=str(source),
                title=title,
                subtitle=subtitle,
                ingredients=ingredient_items,
                steps=step_items,
                tip_text=tip_text,
                domain_handle=domain_handle,
                output_dir=output_dir,
                output_path=output_path,
            )
            if info_res.get("success"):
                return {
                    "success": True,
                    "output_path": str(output_path),
                    "variant": "recipe_card",
                    "variant_label": "Recipe card (infographic)",
                    "card_style": "bright_infographic",
                    "width": PIN_WIDTH,
                    "height": PIN_HEIGHT,
                    "hero_height": PIN_HEIGHT,
                    "rendered_ingredients": ingredient_items,
                    "rendered_steps": step_items,
                    "tip_rendered": bool(tip_text),
                    "footer_rendered": True,
                }
        except Exception as exc:
            logger.debug("Bright infographic variant fallback to classic: %s", exc)

    try:
        theme = _theme_for_domain(domain_handle)

        with Image.open(source) as raw:
            photo = _cover(raw, PIN_WIDTH, PIN_HEIGHT, focus_y=0.38)
        photo = ImageEnhance.Contrast(photo).enhance(1.05)
        photo = ImageEnhance.Color(photo).enhance(1.06).convert("RGBA")

        # ── 1. CINEMATIC DARK BOTTOM VIGNETTE ─────────────────────────────────
        overlay = Image.new("RGBA", (PIN_WIDTH, PIN_HEIGHT), (0, 0, 0, 0))
        overlay_draw = ImageDraw.Draw(overlay)
        vignette_start = 840
        vignette_height = PIN_HEIGHT - vignette_start
        for y in range(vignette_start, PIN_HEIGHT):
            progress = (y - vignette_start) / vignette_height
            alpha = int(250 * (progress**1.15))
            overlay_draw.line((0, y, PIN_WIDTH, y), fill=(12, 9, 7, alpha))

        canvas = Image.alpha_composite(photo, overlay)
        draw = ImageDraw.Draw(canvas, "RGBA")

        # ── 2. TOP FLOATING HEADER CARD ───────────────────────────────────────
        card_x1 = 110
        card_x2 = 890
        card_w = card_x2 - card_x1
        card_y1 = 36
        card_radius = 28

        title_clean = re.sub(r"\s+", " ", title.strip())
        title_font = None
        title_lines = []
        for size in (54, 50, 46, 42, 38):
            f = _font(size, bold=True, serif=True)
            words = title_clean.split()
            lines = []
            cur = ""
            for w in words:
                cand = f"{cur} {w}".strip()
                if cur and draw.textbbox((0, 0), cand, font=f)[2] > (card_w - 70):
                    lines.append(cur)
                    cur = w
                else:
                    cur = cand
            if cur:
                lines.append(cur)
            if len(lines) <= 2:
                title_font = f
                title_lines = lines
                break
        if not title_font:
            title_font = _font(36, bold=True, serif=True)
            title_lines = [title_clean]

        sub_font = _font(24, sans=True)
        clean_tip = re.sub(r"\s+", " ", tip_text or "").strip()
        tip_as_sub = clean_tip if 0 < len(clean_tip) <= 70 else ""
        sub_candidate = (
            subtitle.strip() or tip_as_sub or "Receta casera tradicional • Deliciosa y lista en minutos"
        )
        sub_lines = []
        sub_words = sub_candidate.split()
        cur_sub = ""
        for sw in sub_words:
            cand = f"{cur_sub} {sw}".strip()
            if cur_sub and draw.textbbox((0, 0), cand, font=sub_font)[2] > (card_w - 60):
                sub_lines.append(cur_sub)
                cur_sub = sw
            else:
                cur_sub = cand
        if cur_sub:
            sub_lines.append(cur_sub)
        sub_lines = sub_lines[:2]

        title_sample = draw.textbbox((0, 0), "Ágj", font=title_font)
        title_line_h = (title_sample[3] - title_sample[1]) + 8
        title_block_h = len(title_lines) * title_line_h

        sub_sample = draw.textbbox((0, 0), "Ágj", font=sub_font)
        sub_line_h = (sub_sample[3] - sub_sample[1]) + 6
        sub_block_h = len(sub_lines) * sub_line_h

        card_padding_top = 24
        card_gap = 12
        card_padding_bottom = 22
        card_h = card_padding_top + title_block_h + card_gap + sub_block_h + card_padding_bottom
        card_y2 = card_y1 + card_h

        # Soft drop shadow behind card
        shadow_img = Image.new("RGBA", (card_w + 50, card_h + 50), (0, 0, 0, 0))
        s_draw = ImageDraw.Draw(shadow_img)
        s_draw.rounded_rectangle((25, 25, 25 + card_w, 25 + card_h), radius=card_radius, fill=(10, 8, 6, 90))
        shadow_img = shadow_img.filter(ImageFilter.GaussianBlur(12))
        canvas.paste(shadow_img, (card_x1 - 25, card_y1 - 25 + 8), shadow_img)

        draw = ImageDraw.Draw(canvas, "RGBA")

        # Card body (ivory/warm cream)
        card_bg = (248, 242, 233, 250)
        card_border = (226, 216, 202, 190)
        draw.rounded_rectangle(
            (card_x1, card_y1, card_x2, card_y2),
            radius=card_radius,
            fill=card_bg,
            outline=card_border,
            width=1,
        )

        ink_title = (24, 20, 18)
        cur_y = card_y1 + card_padding_top
        for line in title_lines:
            tb = draw.textbbox((0, 0), line, font=title_font)
            tw = tb[2] - tb[0]
            tx = (PIN_WIDTH - tw) // 2
            draw.text((tx, cur_y), line, font=title_font, fill=ink_title)
            cur_y += title_line_h

        ink_sub = (70, 65, 60)
        cur_y += card_gap - 6
        for line in sub_lines:
            sb = draw.textbbox((0, 0), line, font=sub_font)
            sw = sb[2] - sb[0]
            sx = (PIN_WIDTH - sw) // 2
            draw.text((sx, cur_y), line, font=sub_font, fill=ink_sub)
            cur_y += sub_line_h

        # ── 3. BOTTOM TWO-COLUMN RECIPE SECTION ───────────────────────────────
        col_y_start = 950
        col_left_x1 = 55
        col_left_w = 415
        col_left_x2 = col_left_x1 + col_left_w

        col_right_x1 = 505
        col_right_w = 435
        col_right_x2 = col_right_x1 + col_right_w

        # ── A. SOFT BLURRED HIGHLIGHT BACKPLATE UNDER COLUMNS ─────────────────
        highlight_img = Image.new("RGBA", (PIN_WIDTH, PIN_HEIGHT), (0, 0, 0, 0))
        h_draw = ImageDraw.Draw(highlight_img)
        h_draw.rounded_rectangle(
            (col_left_x1 - 15, col_y_start - 10, col_left_x2 + 15, 1435),
            radius=24,
            fill=(8, 6, 5, 140),
        )
        h_draw.rounded_rectangle(
            (col_right_x1 - 15, col_y_start - 10, col_right_x2 + 15, 1435),
            radius=24,
            fill=(8, 6, 5, 140),
        )
        highlight_img = highlight_img.filter(ImageFilter.GaussianBlur(18))
        canvas = Image.alpha_composite(canvas, highlight_img)

        # ── B. TEXT GLOW / BLURRED HIGHLIGHT LAYER DIRECTLY UNDER TEXT ────────
        from rankstein.recipe_pin_generator import get_recipe_theme_colors

        palette = get_recipe_theme_colors(f"{title} {' '.join(ingredient_items)}")
        header_font = _font(44, bold=True, serif=True)
        header_color = palette.header
        accent_color = palette.accent

        glow_layer = Image.new("RGBA", (PIN_WIDTH, PIN_HEIGHT), (0, 0, 0, 0))
        glow_draw = ImageDraw.Draw(glow_layer)

        for dx, dy in ((-2, 0), (2, 0), (0, -2), (0, 2), (-1, -1), (1, 1), (0, 0)):
            glow_draw.text(
                (col_left_x1 + dx, col_y_start + dy),
                "Ingredientes:",
                font=header_font,
                fill=(0, 0, 0, 255),
            )
            glow_draw.text(
                (col_right_x1 + dx, col_y_start + dy),
                "Preparación:",
                font=header_font,
                fill=(0, 0, 0, 255),
            )

        header_box = draw.textbbox((0, 0), "Ingredientes:", font=header_font)
        header_h = header_box[3] - header_box[1]

        ing_font = _font(21, bold=True, sans=True)
        bullet_font = _font(22, bold=True, sans=True)
        ing_y = col_y_start + header_h + 16
        ing_line_h = 29

        ing_rendered_items: list[tuple[int, int, tuple[str, ...]]] = []
        for item in ingredient_items[:8]:
            lines = _wrap_recipe_text(draw, item, font=ing_font, max_width=col_left_w - 30)
            if not lines:
                continue
            ing_rendered_items.append((col_left_x1, ing_y, lines))
            for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 2), (0, 0)):
                glow_draw.text((col_left_x1 + dx, ing_y + dy + 1), "•", font=bullet_font, fill=(0, 0, 0, 255))
                cur_line_y = ing_y
                for line in lines:
                    glow_draw.text(
                        (col_left_x1 + 22 + dx, cur_line_y + dy + 1),
                        line,
                        font=ing_font,
                        fill=(0, 0, 0, 255),
                    )
                    cur_line_y += ing_line_h
            ing_y += len(lines) * ing_line_h + 3

        step_font = _font(20, bold=False, sans=True)
        step_num_font = _font(20, bold=True, sans=True)
        step_y = col_y_start + header_h + 16
        step_line_h = 28

        step_rendered_items: list[tuple[int, int, str, int, tuple[str, ...]]] = []
        for idx, step in enumerate(step_items[:5], 1):
            prefix = f"{idx}. "
            p_box = draw.textbbox((0, 0), prefix, font=step_num_font)
            p_w = p_box[2] - p_box[0]
            indent_w = col_right_w - p_w - 8
            lines = _wrap_recipe_text(draw, step, font=step_font, max_width=indent_w)
            if not lines:
                continue
            step_rendered_items.append((col_right_x1, step_y, prefix, p_w, lines))
            for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 2), (0, 0)):
                glow_draw.text(
                    (col_right_x1 + dx, step_y + dy + 1),
                    prefix,
                    font=step_num_font,
                    fill=(0, 0, 0, 255),
                )
                cur_s_y = step_y
                for s_line in lines:
                    glow_draw.text(
                        (col_right_x1 + p_w + 4 + dx, cur_s_y + dy + 1),
                        s_line,
                        font=step_font,
                        fill=(0, 0, 0, 255),
                    )
                    cur_s_y += step_line_h
            step_y += len(lines) * step_line_h + 8

        glow_blurred = glow_layer.filter(ImageFilter.GaussianBlur(4))
        canvas = Image.alpha_composite(canvas, glow_blurred)

        # ── C. RENDER CRISP TOP TEXT OVER BLURRED HIGHLIGHT ───────────────────
        draw = ImageDraw.Draw(canvas, "RGBA")

        draw.text((col_left_x1, col_y_start), "Ingredientes:", font=header_font, fill=header_color)
        draw.text((col_right_x1, col_y_start), "Preparación:", font=header_font, fill=header_color)

        for x_pos, y_pos, lines in ing_rendered_items:
            draw.text((x_pos, y_pos), "•", font=bullet_font, fill=accent_color)
            c_y = y_pos
            for line in lines:
                draw.text((x_pos + 22, c_y), line, font=ing_font, fill=(255, 255, 255))
                c_y += ing_line_h

        for x_pos, y_pos, prefix, p_w, lines in step_rendered_items:
            draw.text((x_pos, y_pos), prefix, font=step_num_font, fill=accent_color)
            c_y = y_pos
            for line in lines:
                draw.text((x_pos + p_w + 4, c_y), line, font=step_font, fill=(255, 255, 255))
                c_y += step_line_h

        # ── 4. SUBTLE FOOTER BRANDING ─────────────────────────────────────────
        footer_font = _font(19, sans=True)
        footer_text = f"{theme.public_domain}"
        fb = draw.textbbox((0, 0), footer_text, font=footer_font)
        fw = fb[2] - fb[0]
        draw.text(((PIN_WIDTH - fw) // 2 + 1, 1461), footer_text, font=footer_font, fill=(0, 0, 0, 180))
        draw.text(((PIN_WIDTH - fw) // 2, 1460), footer_text, font=footer_font, fill=(230, 225, 215, 190))

        output_path = output_dir / f"{_safe_slug(title)}-{pair_id}-recipe-card.jpg"
        result = _save(canvas, output_path)
        result.update(
            {
                "variant": "recipe_card",
                "variant_label": "Recipe card",
                "hero_height": PIN_HEIGHT,
                "rendered_ingredients": ingredient_items,
                "rendered_steps": step_items,
                "tip_rendered": False,
                "footer_rendered": True,
            }
        )
        return result
    except Exception as exc:
        return {"success": False, "error": str(exc), "variant": "recipe_card"}
