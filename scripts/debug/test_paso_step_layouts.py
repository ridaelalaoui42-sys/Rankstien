import math
from pathlib import Path
import sys
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

BRAIN_DIR = Path(r"C:\Users\REDX420\.gemini\antigravity\brain\4def31ef-1cbb-4e58-b00a-3c4bea3fd439")
ASSETS_DIR = Path(__file__).resolve().parents[2] / "rankstein" / "assets"
ICONS_DIR = ASSETS_DIR / "icons"
RIBBONS_DIR = ASSETS_DIR / "ribbons"
BADGES_DIR = ASSETS_DIR / "badges"
TEXTURES_DIR = ASSETS_DIR / "textures"
FONTS_DIR = ASSETS_DIR / "fonts"

from rankstein.remaster_variants import _cover
from rankstein.recipe_pin_generator import (
    PIN_W, PIN_H,
    _fit_title_line,
    THEMES, RecipeThemePalette
)

_FONT_CACHE = {}

def get_font(font_name: str, size: int) -> ImageFont.FreeTypeFont:
    """Fixed font loader that enforces proper bold axes on variable fonts."""
    key = (font_name, size)
    if key in _FONT_CACHE:
        return _FONT_CACHE[key]
    
    cand = FONTS_DIR / font_name
    if cand.exists():
        try:
            f = ImageFont.truetype(str(cand), size)
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
            except Exception:
                pass
            _FONT_CACHE[key] = f
            return f
        except Exception:
            pass
            
    f = ImageFont.load_default(size=size)
    _FONT_CACHE[key] = f
    return f

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
    outline: tuple = None,
    width: int = 1,
    shadow_blur: int = 14,
    shadow_alpha: int = 45,
    shadow_offset: tuple = (0, 6),
):
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
):
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
    font_size: int = 50,
    letter_spacing_px: float = 6.0,
    text_color: tuple = (255, 255, 255, 255),
    shadow_color: tuple = (10, 8, 5, 240),
    bold_stroke: int = 2,
    apex_y: float = 52.0,
) -> Image.Image:
    """Create a luxury arched ribbon with mathematically curved, bold, centered arc text."""
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

def render_culinary_pin_v7(
    hero_path: str,
    title: str,
    category: str,
    badge_name: str,
    ribbon_name: str,
    out_name: str,
    ingredients: list[str],
    steps: list[str],
    tip_text: str,
    steps_layout: str = "vertical_cards",  # "vertical_cards" or "grid_2x2"
    prep_time: str = "20 min",
    calories: str = "240 kcal",
    servings: str = "4 porc.",
    domain_text: str = "recetagenial.com",
):
    theme = THEMES.get(category, THEMES["ensalada"])
    c_primary = theme.primary_ribbon
    c_accent = theme.accent_pill
    c_title = theme.title_dark
    c_card_bg = (255, 255, 255, 252)
    c_card_border = (226, 218, 205, 255)
    c_meta_bg = (255, 255, 255, 252)
    
    # 100% High-contrast RGBA colors
    c_ink_bold = (26, 22, 18, 255)         # Deep espresso charcoal
    c_ink_med = (45, 38, 32, 255)          # Rich readable dark brown
    
    src = Path(hero_path)

    # 1. LUXURY BACKGROUND: Hero Food Image Blurred across whole pin with minimal saturation + Parchment paper
    with Image.open(src) as raw_hero:
        bg_food = _cover(raw_hero, PIN_W, PIN_H, focus_y=0.45)
        bg_food = bg_food.filter(ImageFilter.GaussianBlur(40))
        # Minimal saturation: 0.22 gives subtle warm culinary tones without overpowering
        bg_food = ImageEnhance.Color(bg_food).enhance(0.22)
        bg_food = ImageEnhance.Brightness(bg_food).enhance(1.16)
        
        tex_path = TEXTURES_DIR / "paper_parchment.jpg"
        if tex_path.exists():
            paper_tex = _cover(Image.open(tex_path), PIN_W, PIN_H)
            canvas = Image.blend(paper_tex, bg_food, alpha=0.35).convert("RGBA")
        else:
            base_cream = Image.new("RGB", (PIN_W, PIN_H), (252, 249, 242))
            canvas = Image.blend(base_cream, bg_food, alpha=0.25).convert("RGBA")

    draw = ImageDraw.Draw(canvas, "RGBA")

    # 2. Outer decorative border
    draw.rounded_rectangle((22, 22, PIN_W - 22, PIN_H - 22), radius=28, outline=(225, 218, 204, 255), width=2)

    # 3. BIGGER Hero Bowl Photo (530x530)
    hero_size = 530
    with Image.open(src) as h_img:
        hero_sq = _cover(h_img, hero_size, hero_size, focus_y=0.42).convert("RGBA")

    mask = Image.new("L", (hero_size, hero_size), 0)
    mask_draw = ImageDraw.Draw(mask)
    mask_draw.ellipse((0, 0, hero_size, hero_size), fill=255)

    shadow_size = hero_size + 50
    shadow = Image.new("RGBA", (shadow_size, shadow_size), (0, 0, 0, 0))
    s_draw = ImageDraw.Draw(shadow)
    s_draw.ellipse((25, 25, shadow_size - 25, shadow_size - 25), fill=(20, 15, 10, 110))
    shadow = shadow.filter(ImageFilter.GaussianBlur(22))
    
    hero_x = PIN_W - hero_size - 28
    hero_y = 28
    canvas.paste(shadow, (hero_x - 25, hero_y - 25 + 10), shadow)
    canvas.paste(hero_sq, (hero_x, hero_y), mask)
    draw.ellipse((hero_x, hero_y, hero_x + hero_size, hero_y + hero_size), outline=(255, 255, 255, 255), width=8)
    draw.ellipse((hero_x + 4, hero_y + 4, hero_x + hero_size - 4, hero_y + hero_size - 4), outline=(*c_primary, 255), width=2)

    # Culinary Badge Stamp overlapping bowl
    badge_im = load_badge(badge_name, 175)
    badge_x = hero_x - 30
    badge_y = hero_y + hero_size - 145
    paste_with_shadow(canvas, badge_im, (badge_x, badge_y), shadow_blur=10, shadow_alpha=90, shadow_offset=(0, 6))

    # 4. Top Left Text Block (Strictly bounded so it never collides with hero circle)
    max_title_w = hero_x - 55 - 10  # Plentiful clearance before hero bowl
    cur_y = 42

    # Kicker Pill
    f_kicker = get_font("Montserrat-Bold.ttf", 16)
    kicker_label = "RECETA CASERA Y FÁCIL"
    kw = draw.textbbox((0, 0), kicker_label, font=f_kicker)
    pill_w = kw[2] - kw[0] + 46
    
    draw_card_with_shadow(
        canvas,
        (50, cur_y, 50 + pill_w, cur_y + 36),
        radius=18,
        fill=(*c_accent, 255),
        shadow_blur=6,
        shadow_alpha=50,
        shadow_offset=(0, 2),
    )
    draw.text((73 + 1, cur_y + 9 + 1), kicker_label, font=f_kicker, fill=(0, 0, 0, 130))
    draw.text((73, cur_y + 9), kicker_label, font=f_kicker, fill=(255, 255, 255, 255))
    cur_y += 52

    # Flair Script
    f_flair = get_font(theme.font_flair, 32)
    flair_text = theme.kicker_default
    # Wrap flair if too long for max_title_w
    if draw.textbbox((0, 0), flair_text, font=f_flair)[2] > max_title_w:
        fw = flair_text.split()
        flair_l1 = " ".join(fw[:len(fw)//2])
        flair_l2 = " ".join(fw[len(fw)//2:])
        draw.text((50 + 1, cur_y + 1), flair_l1, font=f_flair, fill=(255, 255, 255, 180))
        draw.text((50, cur_y), flair_l1, font=f_flair, fill=(*c_accent, 255))
        cur_y += 36
        draw.text((50 + 1, cur_y + 1), flair_l2, font=f_flair, fill=(255, 255, 255, 180))
        draw.text((50, cur_y), flair_l2, font=f_flair, fill=(*c_accent, 255))
        cur_y += 44
    else:
        draw.text((50 + 1, cur_y + 1), flair_text, font=f_flair, fill=(255, 255, 255, 180))
        draw.text((50, cur_y), flair_text, font=f_flair, fill=(*c_accent, 255))
        cur_y += 48

    # Title Line 1 & Line 2
    title_words = title.strip().split()
    mid = len(title_words) // 2
    l1 = " ".join(title_words[:mid])
    l2 = " ".join(title_words[mid:])

    f_t1, l1_lines = _fit_title_line(draw, l1, theme.font_title_base, max_title_w, 46, 30)
    for line in l1_lines:
        draw.text((50 + 1, cur_y + 2), line, font=f_t1, fill=(0, 0, 0, 70))
        draw.text((50, cur_y), line, font=f_t1, fill=(*c_title, 255))
        cur_y += f_t1.size + 6

    if l2:
        f_t2, l2_lines = _fit_title_line(draw, l2, theme.font_title_accent, max_title_w, 44, 28)
        for line in l2_lines:
            draw.text((50 + 1, cur_y + 2), line, font=f_t2, fill=(0, 0, 0, 70))
            draw.text((50, cur_y), line, font=f_t2, fill=(*c_primary, 255))
            cur_y += f_t2.size + 6

    cur_y += 12
    # Description
    f_desc = get_font("Poppins-Regular.ttf", 16)
    desc_lines = [
        "¡Una combinación fresca, deliciosa y tradicional",
        "que no puedes perderte! Perfecta para compartir."
    ]
    for dl in desc_lines:
        draw.text((50 + 1, cur_y + 1), dl, font=f_desc, fill=(255, 255, 255, 160))
        draw.text((50, cur_y), dl, font=f_desc, fill=c_ink_bold)
        cur_y += 24

    # 5. Middle Section: INGREDIENTES & METRICS (NO RIBBON OVERLAP)
    # The ribbon has its own clean space and does not hide or overlap any text
    mid_y = 565
    ribbon_w = 440
    card_w = 425
    
    # 5a. Arched Ribbon for INGREDIENTES
    ribbon_ing = create_luxury_arched_ribbon(
        ribbon_name,
        "INGREDIENTES",
        target_width=ribbon_w,
        font_name="DMSerifDisplay-Regular.ttf",
        font_size=50,
        letter_spacing_px=6.0,
        apex_y=52.0,
    )
    ribbon_ing_x = 45 + (card_w - ribbon_w) // 2
    ribbon_ing_h = ribbon_ing.height
    
    # Ingredients card begins below the ribbon apex so the ribbon sits on top as an elegant crest
    ing_card_y = mid_y + 35
    ing_card_h = 245
    
    # Draw card FIRST
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
    
    # Paste ribbon ON TOP OF card header
    paste_with_shadow(canvas, ribbon_ing, (ribbon_ing_x, mid_y), shadow_blur=8, shadow_alpha=80, shadow_offset=(0, 4))
    
    # TEXT STARTS SAFELY BELOW THE RIBBON TAILS (ribbon tails end around mid_y + ribbon_ing_h)
    # This guarantees the ribbon NEVER hides or touches any text!
    cur_ing_y = mid_y + ribbon_ing_h + 10
    f_ing = get_font("Poppins-SemiBold.ttf", 19)
    for item in ingredients[:5]:
        draw.text((64, cur_ing_y - 2), "•", font=get_font("Montserrat-Bold.ttf", 24), fill=(*c_accent, 255))
        draw.text((88, cur_ing_y), item, font=f_ing, fill=c_ink_bold)
        cur_ing_y += 36

    # 5b. METRICS CARD
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
    # BOLD, HIGH CONTRAST LABELS (Montserrat-Bold with axis fix)
    f_meta_lbl = get_font("Montserrat-Bold.ttf", 13)
    f_meta_val = get_font("Montserrat-Bold.ttf", 20)

    # Timer
    timer_icon = load_icon("timer", 46, 46)
    cx1 = meta_x + col_w // 2
    paste_with_shadow(canvas, timer_icon, (cx1 - timer_icon.width // 2, meta_y + 14), shadow_blur=4, shadow_alpha=50, shadow_offset=(0, 2))
    draw.text((cx1 - 42, meta_y + 66), "TIEMPO DE\nPREPARACIÓN", font=f_meta_lbl, fill=c_ink_bold, align="center")
    
    pill_box1 = (cx1 - (col_w - 24) // 2, meta_y + 118, cx1 + (col_w - 24) // 2, meta_y + 160)
    draw_card_with_shadow(canvas, pill_box1, radius=14, fill=(*c_accent, 255), shadow_blur=5, shadow_alpha=60, shadow_offset=(0, 2))
    tb1 = draw.textbbox((0, 0), prep_time, font=f_meta_val)
    draw.text((cx1 - (tb1[2] - tb1[0]) // 2 + 1, meta_y + 126 + 1), prep_time, font=f_meta_val, fill=(0, 0, 0, 130))
    draw.text((cx1 - (tb1[2] - tb1[0]) // 2, meta_y + 126), prep_time, font=f_meta_val, fill=(255, 255, 255, 255))

    # Flame
    flame_icon = load_icon("flame", 42, 48)
    cx2 = meta_x + col_w + col_w // 2
    paste_with_shadow(canvas, flame_icon, (cx2 - flame_icon.width // 2, meta_y + 12), shadow_blur=4, shadow_alpha=50, shadow_offset=(0, 2))
    draw.text((cx2 - 34, meta_y + 74), "CALORÍAS", font=f_meta_lbl, fill=c_ink_bold, align="center")
    
    pill_box2 = (cx2 - (col_w - 24) // 2, meta_y + 118, cx2 + (col_w - 24) // 2, meta_y + 160)
    draw_card_with_shadow(canvas, pill_box2, radius=14, fill=(*c_accent, 255), shadow_blur=5, shadow_alpha=60, shadow_offset=(0, 2))
    tb2 = draw.textbbox((0, 0), calories, font=f_meta_val)
    draw.text((cx2 - (tb2[2] - tb2[0]) // 2 + 1, meta_y + 126 + 1), calories, font=f_meta_val, fill=(0, 0, 0, 130))
    draw.text((cx2 - (tb2[2] - tb2[0]) // 2, meta_y + 126), calories, font=f_meta_val, fill=(255, 255, 255, 255))

    # Cutlery
    cutlery_icon = load_icon("cutlery", 42, 48)
    cx3 = meta_x + 2 * col_w + col_w // 2
    paste_with_shadow(canvas, cutlery_icon, (cx3 - cutlery_icon.width // 2, meta_y + 12), shadow_blur=4, shadow_alpha=50, shadow_offset=(0, 2))
    draw.text((cx3 - 38, meta_y + 74), "PORCIONES", font=f_meta_lbl, fill=c_ink_bold, align="center")
    
    pill_box3 = (cx3 - (col_w - 24) // 2, meta_y + 118, cx3 + (col_w - 24) // 2, meta_y + 160)
    draw_card_with_shadow(canvas, pill_box3, radius=14, fill=(*c_accent, 255), shadow_blur=5, shadow_alpha=60, shadow_offset=(0, 2))
    tb3 = draw.textbbox((0, 0), servings, font=f_meta_val)
    draw.text((cx3 - (tb3[2] - tb3[0]) // 2 + 1, meta_y + 126 + 1), servings, font=f_meta_val, fill=(0, 0, 0, 130))
    draw.text((cx3 - (tb3[2] - tb3[0]) // 2, meta_y + 126), servings, font=f_meta_val, fill=(255, 255, 255, 255))

    # Divider & Sprig Callout
    draw.line([(meta_x + 20, meta_y + 178), (meta_x + meta_w - 20, meta_y + 178)], fill=(225, 215, 200, 255), width=1)
    sprig_icon = load_icon("sprig", 36, 36)
    canvas.paste(sprig_icon, (meta_x + 28, meta_y + 194), sprig_icon)
    draw.text((meta_x + 72, meta_y + 192), "100% Casero & Tradicional", font=get_font("Poppins-SemiBold.ttf", 17), fill=(*c_primary, 255))
    draw.text((meta_x + 72, meta_y + 216), "Paso a paso fácil y garantizado", font=get_font("Poppins-Regular.ttf", 15), fill=c_ink_bold)

    # 6. PASO A PASO SECTION (REPLACED REPEATED IMAGES PERMANENTLY & PERFECT RIBBON CLEARANCE)
    steps_y = 885
    ribbon_step_w = 480
    ribbon_steps = create_luxury_arched_ribbon(
        ribbon_name,
        "PASO A PASO",
        target_width=ribbon_step_w,
        font_name="DMSerifDisplay-Regular.ttf",
        font_size=50,
        letter_spacing_px=6.0,
        apex_y=52.0,
    )
    ribbon_steps_x = (PIN_W - ribbon_step_w) // 2
    ribbon_steps_h = ribbon_steps.height
    
    # Paste PASO A PASO ribbon in its OWN dedicated space
    paste_with_shadow(canvas, ribbon_steps, (ribbon_steps_x, steps_y), shadow_blur=8, shadow_alpha=80, shadow_offset=(0, 4))

    # Step cards start strictly BELOW the ribbon tails!
    step_grid_y = steps_y + ribbon_steps_h + 12

    action_titles = [
        ("PREPARAR", "chef_hat"),
        ("COCINAR", "flame"),
        ("INTEGRAR", "sprig"),
        ("SERVIR", "cutlery"),
    ]

    if steps_layout == "vertical_cards":
        # 4 SIDE-BY-SIDE VERTICAL PROCESS CARDS (ZERO REPEATED IMAGES)
        # Each card has a luxury circular badge, action icon, step keyword, and spacious recipe text
        step_card_w = (PIN_W - 90 - 3 * 16) // 4
        step_card_h = 245
        f_step_num = get_font("Montserrat-Bold.ttf", 18)
        f_step_kw = get_font("Montserrat-Bold.ttf", 13)
        f_step_txt = get_font("Poppins-Medium.ttf", 15)

        for idx, (step_txt, (action_kw, icon_name)) in enumerate(zip(steps[:4], action_titles), 1):
            sc_x = 45 + (idx - 1) * (step_card_w + 16)
            
            # Card container with soft shadow
            draw_card_with_shadow(
                canvas,
                (sc_x, step_grid_y, sc_x + step_card_w, step_grid_y + step_card_h),
                radius=18,
                fill=c_card_bg,
                outline=c_card_border,
                width=1,
                shadow_blur=10,
                shadow_alpha=40,
                shadow_offset=(0, 5),
            )

            # Elegant Top Header Header Pill with Step Action & Icon
            header_h = 58
            draw.rounded_rectangle(
                (sc_x, step_grid_y, sc_x + step_card_w, step_grid_y + header_h),
                radius=18,
                fill=(248, 245, 238, 255),
            )
            draw.rectangle(
                (sc_x, step_grid_y + header_h - 18, sc_x + step_card_w, step_grid_y + header_h),
                fill=(248, 245, 238, 255),
            )
            draw.line([(sc_x, step_grid_y + header_h), (sc_x + step_card_w, step_grid_y + header_h)], fill=(225, 218, 204, 255), width=1)

            # Step Number Badge (Circular badge with drop shadow)
            badge_r = 16
            bx = sc_x + 14
            by = step_grid_y + 12
            draw.ellipse((bx + 1, by + 1, bx + 2 * badge_r + 1, by + 2 * badge_r + 1), fill=(0, 0, 0, 50))
            draw.ellipse((bx, by, bx + 2 * badge_r, by + 2 * badge_r), fill=(*c_accent, 255))
            draw.ellipse((bx, by, bx + 2 * badge_r, by + 2 * badge_r), outline=(255, 255, 255, 255), width=2)
            nb = draw.textbbox((0, 0), str(idx), font=f_step_num)
            draw.text((bx + badge_r - (nb[2] - nb[0]) // 2, by + badge_r - (nb[3] - nb[1]) // 2 - 1), str(idx), font=f_step_num, fill=(255, 255, 255, 255))

            # Action Keyword & Utensil Icon
            act_icon = load_icon(icon_name, 26, 26)
            canvas.paste(act_icon, (sc_x + 2 * badge_r + 22, by + 3), act_icon)
            draw.text((sc_x + 2 * badge_r + 52, by + 7), action_kw, font=f_step_kw, fill=(*c_primary, 255))

            # Step Instruction Text (Spacious, beautifully wrapped)
            words = step_txt.split()
            st_lines = []
            cur_st = ""
            for w in words:
                cand = f"{cur_st} {w}".strip()
                if cur_st and draw.textbbox((0, 0), cand, font=f_step_txt)[2] > (step_card_w - 22):
                    st_lines.append(cur_st)
                    cur_st = w
                else:
                    cur_st = cand
            if cur_st:
                st_lines.append(cur_st)

            st_y = step_grid_y + header_h + 14
            for sl in st_lines[:6]:
                draw.text((sc_x + 12, st_y), sl, font=f_step_txt, fill=c_ink_bold)
                st_y += 24

    elif steps_layout == "grid_2x2":
        # 2x2 LUXURY PROCESS GRID (440px wide each)
        grid_w = (PIN_W - 90 - 18) // 2
        grid_h = 118
        f_step_num = get_font("Montserrat-Bold.ttf", 20)
        f_step_kw = get_font("Montserrat-Bold.ttf", 15)
        f_step_txt = get_font("Poppins-Regular.ttf", 15)

        for idx, (step_txt, (action_kw, icon_name)) in enumerate(zip(steps[:4], action_titles), 1):
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
            badge_r = 18
            bx = gx + 16
            by = gy + 16
            draw.ellipse((bx + 1, by + 1, bx + 2 * badge_r + 1, by + 2 * badge_r + 1), fill=(0, 0, 0, 50))
            draw.ellipse((bx, by, bx + 2 * badge_r, by + 2 * badge_r), fill=(*c_accent, 255))
            draw.ellipse((bx, by, bx + 2 * badge_r, by + 2 * badge_r), outline=(255, 255, 255, 255), width=2)
            nb = draw.textbbox((0, 0), str(idx), font=f_step_num)
            draw.text((bx + badge_r - (nb[2] - nb[0]) // 2, by + badge_r - (nb[3] - nb[1]) // 2 - 1), str(idx), font=f_step_num, fill=(255, 255, 255, 255))

            # Utensil icon under badge
            act_icon = load_icon(icon_name, 28, 28)
            canvas.paste(act_icon, (bx + 4, by + 2 * badge_r + 10), act_icon)

            # Right content: Action Title + Instructions
            draw.text((gx + 66, gy + 14), f"PASO {idx}: {action_kw}", font=f_step_kw, fill=(*c_primary, 255))
            
            words = step_txt.split()
            st_lines = []
            cur_st = ""
            for w in words:
                cand = f"{cur_st} {w}".strip()
                if cur_st and draw.textbbox((0, 0), cand, font=f_step_txt)[2] > (grid_w - 82):
                    st_lines.append(cur_st)
                    cur_st = w
                else:
                    cur_st = cand
            if cur_st:
                st_lines.append(cur_st)

            sy = gy + 42
            for sl in st_lines[:3]:
                draw.text((gx + 66, sy), sl, font=f_step_txt, fill=c_ink_bold)
                sy += 23

    # 7. CHEF TIP & FINAL CALLOUT (BOTTOM SECTION)
    bot_y = 1265 if steps_layout == "grid_2x2" else 1265
    tip_w = 435
    tip_h = 145
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
    
    bulb_icon = load_icon("bulb", 46, 52)
    paste_with_shadow(canvas, bulb_icon, (60, bot_y + 16), shadow_blur=4, shadow_alpha=50, shadow_offset=(0, 2))
    
    f_tip_title = get_font(theme.font_title_base, 24)
    draw.text((118 + 1, bot_y + 18 + 1), "Consejo del Chef:", font=f_tip_title, fill=(255, 255, 255, 180))
    draw.text((118, bot_y + 18), "Consejo del Chef:", font=f_tip_title, fill=(*c_primary, 255))

    f_tip_txt = get_font("Poppins-Regular.ttf", 15)
    tip_words = tip_text.split()
    tip_lines = []
    cur_t = ""
    for tw in tip_words:
        cand = f"{cur_t} {tw}".strip()
        if cur_t and draw.textbbox((0, 0), cand, font=f_tip_txt)[2] > (tip_w - 40):
            tip_lines.append(cur_t)
            cur_t = tw
        else:
            cur_t = cand
    if cur_t:
        tip_lines.append(cur_t)

    ty = bot_y + 58
    for tl in tip_lines[:3]:
        draw.text((65, ty), tl, font=f_tip_txt, fill=c_ink_bold)
        ty += 24

    # Bottom Right Card: Authentic Social Proof & CTA (Replaces repeated dish photo thumbnail)
    callout_x = 505
    callout_w = PIN_W - callout_x - 45
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

    badge_star = load_badge("badge_stamp_star", 64)
    canvas.paste(badge_star, (callout_x + 18, bot_y + 18), badge_star)

    f_flair_bot = get_font(theme.font_flair, 22)
    draw.text((callout_x + 92, bot_y + 18), "¡Receta 100% probada!", font=f_flair_bot, fill=(*c_accent, 255))
    draw.text((callout_x + 92, bot_y + 44), "Fácil, casera y garantizada.", font=get_font("Poppins-Regular.ttf", 14), fill=c_ink_med)

    # Big "¡DISFRUTA!" Button Pill
    cta_w = callout_w - 36
    draw_card_with_shadow(
        canvas,
        (callout_x + 18, bot_y + 82, callout_x + 18 + cta_w, bot_y + 126),
        radius=14,
        fill=(*c_primary, 255),
        shadow_blur=6,
        shadow_alpha=60,
        shadow_offset=(0, 2),
    )
    db = draw.textbbox((0, 0), "¡LISTA PARA SERVIR Y DISFRUTAR!", font=get_font("Montserrat-Bold.ttf", 15))
    draw.text((callout_x + 18 + (cta_w - (db[2] - db[0])) // 2 + 1, bot_y + 94 + 1), "¡LISTA PARA SERVIR Y DISFRUTAR!", font=get_font("Montserrat-Bold.ttf", 15), fill=(0, 0, 0, 100))
    draw.text((callout_x + 18 + (cta_w - (db[2] - db[0])) // 2, bot_y + 94), "¡LISTA PARA SERVIR Y DISFRUTAR!", font=get_font("Montserrat-Bold.ttf", 15), fill=(255, 255, 255, 255))

    # 8. Branding bar
    bar_y = 1430
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
    draw.text(((PIN_W - (ftb[2] - ftb[0])) // 2, bar_y + 13), footer_text, font=f_footer, fill=(255, 255, 255, 255))

    out_p = BRAIN_DIR / out_name
    canvas.convert("RGB").save(out_p, "JPEG", quality=95)
    print(f"Rendered: {out_p}")

if __name__ == "__main__":
    hero_ensalada = "nanobanana-output/ensalada-de-manzana-cremosa-y-refrescante-hero.jpg"
    hero_arroz = "nanobanana-output/arroz-con-leche-cremoso-en-vaso-hero.jpg"
    
    # 1. Ensalada with Vertical Cards
    render_culinary_pin_v7(
        hero_path=hero_ensalada,
        title="Ensalada de Zanahoria con Manzana, Piña y Yogur",
        category="ensalada",
        badge_name="badge_laurel_gourmet",
        ribbon_name="arch_ribbon_green",
        out_name="pin_ensalada_v7_cards.jpg",
        steps_layout="vertical_cards",
        ingredients=[
            "2 zanahorias medianas ralladas",
            "1 manzana verde en cubitos",
            "1 taza de piña fresca en trozos",
            "1/2 taza de yogur natural cremoso",
            "1 cucharada de miel de flores",
        ],
        steps=[
            "Pela y ralla las zanahorias. Corta la manzana y la piña en trozos pequeños homogéneos.",
            "En un bol mediano, mezcla el yogur natural con la miel hasta obtener una crema suave.",
            "Vierte el aderezo sobre las frutas en un bol amplio y mezcla con movimientos envolventes.",
            "Refrigera durante 30 minutos antes de servir para intensificar la frescura y sabores.",
        ],
        tip_text="Añade un puñado de nueces tostadas justo antes de servir para aportar un toque crujiente irresistible.",
        prep_time="15 min",
        calories="150 kcal",
        servings="4 porc.",
        domain_text="recetagenial.com",
    )
    
    # 2. Arroz with 2x2 Grid
    render_culinary_pin_v7(
        hero_path=hero_arroz,
        title="Arroz con Leche Tradicional y Canela en Rama",
        category="arroz",
        badge_name="badge_stamp_star",
        ribbon_name="arch_ribbon_gold",
        out_name="pin_arroz_v7_grid.jpg",
        steps_layout="grid_2x2",
        ingredients=[
            "1 litro de leche entera fresca",
            "100 g de arroz redondo especial",
            "70 g de azúcar blanco fino",
            "1 rama de canela de Ceilán",
            "Piel de limón sin parte blanca",
        ],
        steps=[
            "Coloca la leche en una cacerola con la rama de canela y la piel de limón. Lleva a ebullición suave.",
            "Incorpora el arroz y cocina a fuego muy lento durante 40 minutos removiendo con frecuencia.",
            "Añade el azúcar en los últimos 5 minutos de cocción para conseguir una textura súper melosa.",
            "Retira la canela y la piel de limón. Vierte en recipientes individuales y espolvorea canela molida.",
        ],
        tip_text="Remover constantemente libera el almidón del arroz para lograr una textura ultra cremosa.",
        prep_time="45 min",
        calories="190 kcal",
        servings="6 porc.",
        domain_text="recetadolce.com",
    )

    # 3. Arroz with Vertical Cards (so we can compare both layout styles side by side)
    render_culinary_pin_v7(
        hero_path=hero_arroz,
        title="Arroz con Leche Tradicional y Canela en Rama",
        category="arroz",
        badge_name="badge_stamp_star",
        ribbon_name="arch_ribbon_gold",
        out_name="pin_arroz_v7_cards.jpg",
        steps_layout="vertical_cards",
        ingredients=[
            "1 litro de leche entera fresca",
            "100 g de arroz redondo especial",
            "70 g de azúcar blanco fino",
            "1 rama de canela de Ceilán",
            "Piel de limón sin parte blanca",
        ],
        steps=[
            "Coloca la leche en una cacerola con la rama de canela y piel de limón a ebullición.",
            "Incorpora el arroz y cocina a fuego muy lento durante 40 min removiendo a menudo.",
            "Añade el azúcar en los últimos 5 minutos para conseguir textura melosa y sedosa.",
            "Retira la canela y limón. Vierte en cuencos y espolvorea canela molida al gusto.",
        ],
        tip_text="Remover constantemente libera el almidón del arroz para lograr una textura ultra cremosa.",
        prep_time="45 min",
        calories="190 kcal",
        servings="6 porc.",
        domain_text="recetadolce.com",
    )
