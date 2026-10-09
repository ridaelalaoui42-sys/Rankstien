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
    get_font, _fit_title_line,
    THEMES, RecipeThemePalette
)

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
    """Draw a luxury rounded card with smooth Gaussian drop shadow underneath."""
    x1, y1, x2, y2 = box
    w = x2 - x1
    h = y2 - y1
    
    # 1. Soft blurred drop shadow
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
    
    # 2. Crisp card body
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
    """Paste an RGBA image onto canvas with soft drop shadow underneath."""
    w, h = img.size
    pad = shadow_blur * 2 + 8
    s_w = w + pad * 2
    s_h = h + pad * 2
    
    shadow_layer = Image.new("RGBA", (s_w, s_h), (0, 0, 0, 0))
    # Extract alpha from img to create exact silhouette shadow
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
    font_size: int = 52,
    letter_spacing_px: float = 6.0,
    text_color: tuple = (255, 255, 255, 255),
    shadow_color: tuple = (10, 8, 5, 240),
    bold_stroke: int = 2,
    apex_y: float = 50.0,
) -> Image.Image:
    """Create a luxury arched ribbon with mathematically curved, bold, centered arc text."""
    p = RIBBONS_DIR / f"{ribbon_name}.png"
    im = Image.open(p).convert("RGBA")
    orig_w, orig_h = im.size
    
    font = get_font(font_name, font_size)
    
    # Render arc text at native resolution (940px wide) before resizing
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
    
    # Scale down to target_width preserving aspect ratio
    target_h = int(orig_h * (target_width / orig_w))
    return im.resize((target_width, target_h), Image.Resampling.LANCZOS)

def render_culinary_infographic_pin_v6(
    hero_path: str,
    title: str,
    category: str,
    badge_name: str,
    ribbon_name: str,
    out_name: str,
    ingredients: list[str],
    steps: list[str],
    tip_text: str,
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
    
    # High-contrast 4-tuple colors (RGBA)
    c_ink_bold = (28, 24, 20, 255)         # Deep espresso charcoal
    c_ink_med = (45, 38, 32, 255)          # Rich dark readable tone
    
    src = Path(hero_path)

    # 1. LUXURY BACKGROUND: Hero Food Image Blurred across whole pin with minimal saturation + Parchment paper
    with Image.open(src) as raw_hero:
        # Full-cover of food image over entire 1000x1500 canvas
        bg_food = _cover(raw_hero, PIN_W, PIN_H, focus_y=0.45)
        # Heavy blur for soft ambient culinary atmosphere
        bg_food = bg_food.filter(ImageFilter.GaussianBlur(40))
        # Minimal saturation so it doesn't overpower, gives delicate pastel ambient tones
        bg_food = ImageEnhance.Color(bg_food).enhance(0.22)
        # Soft brightness boost
        bg_food = ImageEnhance.Brightness(bg_food).enhance(1.16)
        
        # Load paper parchment texture
        tex_path = TEXTURES_DIR / "paper_parchment.jpg"
        if tex_path.exists():
            paper_tex = _cover(Image.open(tex_path), PIN_W, PIN_H)
            # Blend blurred food background with tactile paper texture (36% food color, 64% paper texture)
            canvas = Image.blend(paper_tex, bg_food, alpha=0.36).convert("RGBA")
        else:
            base_cream = Image.new("RGB", (PIN_W, PIN_H), (252, 249, 242))
            canvas = Image.blend(base_cream, bg_food, alpha=0.25).convert("RGBA")

    draw = ImageDraw.Draw(canvas, "RGBA")

    # 2. Outer decorative border
    draw.rounded_rectangle((22, 22, PIN_W - 22, PIN_H - 22), radius=28, outline=(225, 218, 204, 255), width=2)

    # 3. Kicker Pill with generous padding & soft drop shadow
    cur_y = 44
    f_kicker = get_font("Montserrat-Bold.ttf", 16)
    kicker_label = "RECETA CASERA Y FÁCIL"
    kw = draw.textbbox((0, 0), kicker_label, font=f_kicker)
    pill_w = kw[2] - kw[0] + 46
    
    # Soft shadow under pill
    draw_card_with_shadow(
        canvas,
        (50, cur_y, 50 + pill_w, cur_y + 36),
        radius=18,
        fill=(*c_accent, 255),
        shadow_blur=6,
        shadow_alpha=50,
        shadow_offset=(0, 2),
    )
    # Bold white text with dark drop shadow
    draw.text((73 + 1, cur_y + 9 + 1), kicker_label, font=f_kicker, fill=(0, 0, 0, 120))
    draw.text((73, cur_y + 9), kicker_label, font=f_kicker, fill=(255, 255, 255, 255))
    cur_y += 54

    # 4. Artisanal Flair Script with soft shadow
    f_flair = get_font(theme.font_flair, 36)
    flair_text = theme.kicker_default
    draw.text((50 + 1, cur_y + 1), flair_text, font=f_flair, fill=(255, 255, 255, 180))
    draw.text((50, cur_y), flair_text, font=f_flair, fill=(*c_accent, 255))
    cur_y += 50

    # 5. Multi-Line Title (Two-tone recipe typography with crisp text shadow)
    max_title_w = 385
    title_words = title.strip().split()
    mid = len(title_words) // 2
    l1 = " ".join(title_words[:mid])
    l2 = " ".join(title_words[mid:])

    f_t1, l1_lines = _fit_title_line(draw, l1, theme.font_title_base, max_title_w, 50, 32)
    for line in l1_lines:
        # Subtle dark text shadow for 100% legibility
        draw.text((50 + 1, cur_y + 2), line, font=f_t1, fill=(0, 0, 0, 60))
        draw.text((50, cur_y), line, font=f_t1, fill=(*c_title, 255))
        cur_y += f_t1.size + 6

    if l2:
        f_t2, l2_lines = _fit_title_line(draw, l2, theme.font_title_accent, max_title_w, 48, 30)
        for line in l2_lines:
            draw.text((50 + 1, cur_y + 2), line, font=f_t2, fill=(0, 0, 0, 60))
            draw.text((50, cur_y), line, font=f_t2, fill=(*c_primary, 255))
            cur_y += f_t2.size + 6

    cur_y += 14
    # Description with high contrast and subtle highlight
    f_desc = get_font("Poppins-Regular.ttf", 17)
    for dl in ["¡Una combinación fresca, deliciosa y tradicional", "que no puedes perderte! Perfecta para compartir."]:
        draw.text((50 + 1, cur_y + 1), dl, font=f_desc, fill=(255, 255, 255, 160))
        draw.text((50, cur_y), dl, font=f_desc, fill=c_ink_bold)
        cur_y += 26

    # 6. BIGGER Hero Bowl Photo (540x540) with Soft Drop Shadow & Luxury Stamp Badge
    hero_size = 540
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
    
    hero_x = PIN_W - hero_size - 26
    hero_y = 26
    canvas.paste(shadow, (hero_x - 25, hero_y - 25 + 10), shadow)
    canvas.paste(hero_sq, (hero_x, hero_y), mask)
    draw.ellipse((hero_x, hero_y, hero_x + hero_size, hero_y + hero_size), outline=(255, 255, 255, 255), width=8)
    draw.ellipse((hero_x + 4, hero_y + 4, hero_x + hero_size - 4, hero_y + hero_size - 4), outline=(*c_primary, 255), width=2)

    # Real Culinary Badge Stamp overlapping the bowl at bottom left of bowl
    badge_im = load_badge(badge_name, 180)
    badge_x = hero_x - 35
    badge_y = hero_y + hero_size - 150
    paste_with_shadow(canvas, badge_im, (badge_x, badge_y), shadow_blur=10, shadow_alpha=90, shadow_offset=(0, 6))

    # 7. Middle Row: INGREDIENTES CARD & METRICS CARD
    mid_y = 575
    card_w = 425
    ing_card_h = 245
    ing_card_y = mid_y + 40  # Card starts under ribbon apex

    # DRAW INGREDIENTS CARD FIRST (with luxury soft drop shadow)
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

    # PASTE ARCHED RIBBON ON TOP OF CARD (ribbon crowns the card, NO clipping!)
    ribbon_w = 450
    ribbon_ing = create_luxury_arched_ribbon(
        ribbon_name,
        "INGREDIENTES",
        target_width=ribbon_w,
        font_name="DMSerifDisplay-Regular.ttf",
        font_size=52,
        letter_spacing_px=6.0,
        apex_y=50.0,
    )
    # Centered over the card, sitting on top of the card's top edge
    ribbon_x = 45 + (card_w - ribbon_w) // 2
    paste_with_shadow(canvas, ribbon_ing, (ribbon_x, mid_y), shadow_blur=8, shadow_alpha=80, shadow_offset=(0, 4))

    # Ingredients items inside card
    f_ing = get_font("Poppins-SemiBold.ttf", 20)
    cur_ing_y = ing_card_y + 36
    for item in ingredients[:5]:
        draw.text((64, cur_ing_y - 2), "•", font=get_font("Montserrat-Bold.ttf", 26), fill=(*c_accent, 255))
        draw.text((88, cur_ing_y), item, font=f_ing, fill=c_ink_bold)
        cur_ing_y += 39

    # METRICS CARD (DRAW WITH LUXURY SHADOW)
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
    # BOLD, DARK, HIGH CONTRAST LABELS (Montserrat-Bold at 13pt)
    f_meta_lbl = get_font("Montserrat-Bold.ttf", 13)
    f_meta_val = get_font("Montserrat-Bold.ttf", 20)

    # 1. Timer
    timer_icon = load_icon("timer", 46, 46)
    cx1 = meta_x + col_w // 2
    paste_with_shadow(canvas, timer_icon, (cx1 - timer_icon.width // 2, meta_y + 14), shadow_blur=4, shadow_alpha=50, shadow_offset=(0, 2))
    
    draw.text((cx1 - 42, meta_y + 66), "TIEMPO DE\nPREPARACIÓN", font=f_meta_lbl, fill=c_ink_bold, align="center")
    
    # Value pill with drop shadow
    pill_box1 = (cx1 - (col_w - 24) // 2, meta_y + 118, cx1 + (col_w - 24) // 2, meta_y + 160)
    draw_card_with_shadow(canvas, pill_box1, radius=14, fill=(*c_accent, 255), shadow_blur=5, shadow_alpha=60, shadow_offset=(0, 2))
    tb1 = draw.textbbox((0, 0), prep_time, font=f_meta_val)
    draw.text((cx1 - (tb1[2] - tb1[0]) // 2 + 1, meta_y + 126 + 1), prep_time, font=f_meta_val, fill=(0, 0, 0, 130))
    draw.text((cx1 - (tb1[2] - tb1[0]) // 2, meta_y + 126), prep_time, font=f_meta_val, fill=(255, 255, 255, 255))

    # 2. Flame
    flame_icon = load_icon("flame", 42, 48)
    cx2 = meta_x + col_w + col_w // 2
    paste_with_shadow(canvas, flame_icon, (cx2 - flame_icon.width // 2, meta_y + 12), shadow_blur=4, shadow_alpha=50, shadow_offset=(0, 2))
    
    draw.text((cx2 - 34, meta_y + 74), "CALORÍAS", font=f_meta_lbl, fill=c_ink_bold, align="center")
    
    pill_box2 = (cx2 - (col_w - 24) // 2, meta_y + 118, cx2 + (col_w - 24) // 2, meta_y + 160)
    draw_card_with_shadow(canvas, pill_box2, radius=14, fill=(*c_accent, 255), shadow_blur=5, shadow_alpha=60, shadow_offset=(0, 2))
    tb2 = draw.textbbox((0, 0), calories, font=f_meta_val)
    draw.text((cx2 - (tb2[2] - tb2[0]) // 2 + 1, meta_y + 126 + 1), calories, font=f_meta_val, fill=(0, 0, 0, 130))
    draw.text((cx2 - (tb2[2] - tb2[0]) // 2, meta_y + 126), calories, font=f_meta_val, fill=(255, 255, 255, 255))

    # 3. Cutlery
    cutlery_icon = load_icon("cutlery", 42, 48)
    cx3 = meta_x + 2 * col_w + col_w // 2
    paste_with_shadow(canvas, cutlery_icon, (cx3 - cutlery_icon.width // 2, meta_y + 12), shadow_blur=4, shadow_alpha=50, shadow_offset=(0, 2))
    
    draw.text((cx3 - 38, meta_y + 74), "PORCIONES", font=f_meta_lbl, fill=c_ink_bold, align="center")
    
    pill_box3 = (cx3 - (col_w - 24) // 2, meta_y + 118, cx3 + (col_w - 24) // 2, meta_y + 160)
    draw_card_with_shadow(canvas, pill_box3, radius=14, fill=(*c_accent, 255), shadow_blur=5, shadow_alpha=60, shadow_offset=(0, 2))
    tb3 = draw.textbbox((0, 0), servings, font=f_meta_val)
    draw.text((cx3 - (tb3[2] - tb3[0]) // 2 + 1, meta_y + 126 + 1), servings, font=f_meta_val, fill=(0, 0, 0, 130))
    draw.text((cx3 - (tb3[2] - tb3[0]) // 2, meta_y + 126), servings, font=f_meta_val, fill=(255, 255, 255, 255))

    # Sprig & High Contrast Callout
    draw.line([(meta_x + 20, meta_y + 178), (meta_x + meta_w - 20, meta_y + 178)], fill=(225, 215, 200, 255), width=1)
    sprig_icon = load_icon("sprig", 36, 36)
    canvas.paste(sprig_icon, (meta_x + 28, meta_y + 194), sprig_icon)
    draw.text((meta_x + 72, meta_y + 192), "100% Casero & Tradicional", font=get_font("Poppins-SemiBold.ttf", 17), fill=(*c_primary, 255))
    draw.text((meta_x + 72, meta_y + 216), "Paso a paso fácil y garantizado", font=get_font("Poppins-Regular.ttf", 15), fill=c_ink_bold)

    # 8. PASO A PASO Arched Ribbon & Step Cards
    steps_y = 890
    step_grid_y = steps_y + 85   # Step cards start safely below ribbon arch
    step_card_w = (PIN_W - 90 - 3 * 16) // 4
    step_card_h = 245

    # 8a. Draw 4 step cards FIRST (with luxury soft shadows)
    f_step_num = get_font("Montserrat-Bold.ttf", 20)
    f_step_txt = get_font("Poppins-SemiBold.ttf", 15)
    crop_focuses = [0.2, 0.4, 0.6, 0.8]

    with Image.open(src) as h_img:
        for idx, step_txt in enumerate(steps[:4], 1):
            sc_x = 45 + (idx - 1) * (step_card_w + 16)
            draw_card_with_shadow(
                canvas,
                (sc_x, step_grid_y, sc_x + step_card_w, step_grid_y + step_card_h),
                radius=16,
                fill=c_card_bg,
                outline=c_card_border,
                width=1,
                shadow_blur=10,
                shadow_alpha=40,
                shadow_offset=(0, 5),
            )

            thumb_h = 112
            step_thumb = _cover(h_img, step_card_w, thumb_h, focus_y=crop_focuses[idx - 1]).convert("RGBA")
            t_mask = Image.new("L", (step_card_w, thumb_h), 0)
            t_mdraw = ImageDraw.Draw(t_mask)
            t_mdraw.rounded_rectangle((0, 0, step_card_w, thumb_h), radius=16, fill=255)
            t_mdraw.rectangle((0, thumb_h - 16, step_card_w, thumb_h), fill=255)
            canvas.paste(step_thumb, (sc_x, step_grid_y), t_mask)

            # Circular badge with drop shadow
            badge_r = 17
            draw.ellipse((sc_x + 9, step_grid_y + 9, sc_x + 9 + 2 * badge_r, step_grid_y + 9 + 2 * badge_r), fill=(0, 0, 0, 60))
            draw.ellipse((sc_x + 8, step_grid_y + 8, sc_x + 8 + 2 * badge_r, step_grid_y + 8 + 2 * badge_r), fill=(*c_accent, 255))
            draw.ellipse((sc_x + 8, step_grid_y + 8, sc_x + 8 + 2 * badge_r, step_grid_y + 8 + 2 * badge_r), outline=(255, 255, 255, 255), width=2)
            nb = draw.textbbox((0, 0), str(idx), font=f_step_num)
            draw.text((sc_x + 8 + badge_r - (nb[2] - nb[0]) // 2 + 1, step_grid_y + 8 + badge_r - (nb[3] - nb[1]) // 2), str(idx), font=f_step_num, fill=(0, 0, 0, 100))
            draw.text((sc_x + 8 + badge_r - (nb[2] - nb[0]) // 2, step_grid_y + 8 + badge_r - (nb[3] - nb[1]) // 2 - 1), str(idx), font=f_step_num, fill=(255, 255, 255, 255))

            words = step_txt.split()
            st_lines = []
            cur_st = ""
            for w in words:
                cand = f"{cur_st} {w}".strip()
                if cur_st and draw.textbbox((0, 0), cand, font=f_step_txt)[2] > (step_card_w - 20):
                    st_lines.append(cur_st)
                    cur_st = w
                else:
                    cur_st = cand
            if cur_st:
                st_lines.append(cur_st)

            st_y = step_grid_y + thumb_h + 10
            for sl in st_lines[:5]:
                draw.text((sc_x + 10, st_y), sl, font=f_step_txt, fill=c_ink_bold)
                st_y += 20

    # 8b. PASTE PASO A PASO RIBBON ON TOP (ZERO CLIPPING!)
    ribbon_step_w = 480
    ribbon_steps = create_luxury_arched_ribbon(
        ribbon_name,
        "PASO A PASO",
        target_width=ribbon_step_w,
        font_name="DMSerifDisplay-Regular.ttf",
        font_size=52,
        letter_spacing_px=6.0,
        apex_y=50.0,
    )
    ribbon_steps_x = (PIN_W - ribbon_step_w) // 2
    paste_with_shadow(canvas, ribbon_steps, (ribbon_steps_x, steps_y), shadow_blur=8, shadow_alpha=80, shadow_offset=(0, 4))

    # 9. Chef Tip Box (with soft shadow)
    bot_y = 1205
    tip_w = 425
    tip_h = 185
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
    
    f_tip_title = get_font(theme.font_title_base, 25)
    draw.text((118 + 1, bot_y + 22 + 1), "Consejo del Chef:", font=f_tip_title, fill=(255, 255, 255, 180))
    draw.text((118, bot_y + 22), "Consejo del Chef:", font=f_tip_title, fill=(*c_primary, 255))

    f_tip_txt = get_font("Poppins-Regular.ttf", 17)
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

    ty = bot_y + 70
    for tl in tip_lines[:4]:
        draw.text((65, ty), tl, font=f_tip_txt, fill=c_ink_bold)
        ty += 26

    # Bottom Flair + Mini Photo
    f_flair_bot = get_font(theme.font_flair, 25)
    draw.text((495, bot_y + 26), "¡Deliciosa, casera y perfecta", font=f_flair_bot, fill=(*c_accent, 255))
    draw.text((495, bot_y + 64), "para cualquier ocasión!", font=f_flair_bot, fill=(*c_accent, 255))
    sprig_bot = load_icon("sprig", 32, 32)
    canvas.paste(sprig_bot, (498, bot_y + 118), sprig_bot)
    draw.text((538, bot_y + 118), "Lista en pocos minutos", font=get_font("Poppins-SemiBold.ttf", 18), fill=(*c_primary, 255))

    mini_thumb_size = 185
    mini_x = PIN_W - mini_thumb_size - 45
    with Image.open(src) as h_img:
        mini_thumb = _cover(h_img, mini_thumb_size, mini_thumb_size, focus_y=0.5).convert("RGBA")
    mini_mask = Image.new("L", (mini_thumb_size, mini_thumb_size), 0)
    mini_mask_draw = ImageDraw.Draw(mini_mask)
    mini_mask_draw.rounded_rectangle((0, 0, mini_thumb_size, mini_thumb_size), radius=22, fill=255)
    
    # Shadow under mini thumb
    draw_card_with_shadow(
        canvas,
        (mini_x, bot_y, mini_x + mini_thumb_size, bot_y + mini_thumb_size),
        radius=22,
        fill=(255, 255, 255, 255),
        shadow_blur=10,
        shadow_alpha=50,
        shadow_offset=(0, 4),
    )
    canvas.paste(mini_thumb, (mini_x, bot_y), mini_mask)
    draw.rounded_rectangle((mini_x, bot_y, mini_x + mini_thumb_size, bot_y + mini_thumb_size), radius=22, outline=(255, 255, 255, 255), width=4)

    # ¡DISFRUTA! pill button
    draw_card_with_shadow(
        canvas,
        (mini_x + 15, bot_y + mini_thumb_size - 38, mini_x + mini_thumb_size - 15, bot_y + mini_thumb_size - 6),
        radius=12,
        fill=(*c_primary, 255),
        shadow_blur=4,
        shadow_alpha=60,
        shadow_offset=(0, 2),
    )
    db = draw.textbbox((0, 0), "¡DISFRUTA!", font=get_font("Montserrat-Bold.ttf", 16))
    draw.text((mini_x + mini_thumb_size // 2 - (db[2] - db[0]) // 2 + 1, bot_y + mini_thumb_size - 32 + 1), "¡DISFRUTA!", font=get_font("Montserrat-Bold.ttf", 16), fill=(0, 0, 0, 100))
    draw.text((mini_x + mini_thumb_size // 2 - (db[2] - db[0]) // 2, bot_y + mini_thumb_size - 32), "¡DISFRUTA!", font=get_font("Montserrat-Bold.ttf", 16), fill=(255, 255, 255, 255))

    # 10. Branding bar
    bar_y = 1425
    draw_card_with_shadow(
        canvas,
        (35, bar_y, PIN_W - 35, bar_y + 50),
        radius=25,
        fill=(*c_title, 255),
        shadow_blur=8,
        shadow_alpha=60,
        shadow_offset=(0, 3),
    )
    f_footer = get_font("Poppins-SemiBold.ttf", 19)
    footer_text = f"{theme.hashtag_bar}  •  {domain_text}"
    ftb = draw.textbbox((0, 0), footer_text, font=f_footer)
    draw.text(((PIN_W - (ftb[2] - ftb[0])) // 2, bar_y + 13), footer_text, font=f_footer, fill=(255, 255, 255, 255))

    out_p = BRAIN_DIR / out_name
    canvas.convert("RGB").save(out_p, "JPEG", quality=95)
    print(f"Rendered: {out_p}")

if __name__ == "__main__":
    hero_ensalada = "nanobanana-output/ensalada-de-manzana-cremosa-y-refrescante-hero.jpg"
    hero_arroz = "nanobanana-output/arroz-con-leche-cremoso-en-vaso-hero.jpg"
    
    # 1. Ensalada
    render_culinary_infographic_pin_v6(
        hero_path=hero_ensalada,
        title="Ensalada de Zanahoria con Manzana, Piña y Yogur",
        category="ensalada",
        badge_name="badge_laurel_gourmet",
        ribbon_name="arch_ribbon_green",
        out_name="pin_ensalada_v6_perfect.jpg",
        ingredients=[
            "2 zanahorias medianas ralladas",
            "1 manzana verde en cubitos",
            "1 taza de piña fresca en trozos",
            "1/2 taza de yogur natural cremoso",
            "1 cucharada de miel de flores",
        ],
        steps=[
            "Mezcla las zanahorias, manzana y piña en un bol.",
            "Combina el yogur natural con la miel suavemente.",
            "Vierte el aderezo de yogur sobre las frutas frescas.",
            "Remueve bien y refrigera 30 min antes de servir.",
        ],
        tip_text="Añade un puñado de nueces tostadas justo antes de servir para aportar un toque crujiente irresistible.",
        prep_time="15 min",
        calories="150 kcal",
        servings="4 porc.",
        domain_text="recetagenial.com",
    )
    
    # 2. Arroz
    render_culinary_infographic_pin_v6(
        hero_path=hero_arroz,
        title="Arroz con Leche Tradicional y Canela en Rama",
        category="arroz",
        badge_name="badge_stamp_star",
        ribbon_name="arch_ribbon_gold",
        out_name="pin_arroz_v6_perfect.jpg",
        ingredients=[
            "1 litro de leche entera fresca",
            "100 g de arroz redondo especial",
            "70 g de azúcar blanco fino",
            "1 rama de canela de Ceilán",
            "Piel de limón sin parte blanca",
        ],
        steps=[
            "Infusiona la leche con canela y piel de limón.",
            "Añade el arroz y cocina a fuego lento removiendo.",
            "Agrega el azúcar al final para máxima cremosidad.",
            "Sirve en cuencos y espolvorea canela molida.",
        ],
        tip_text="Remover constantemente libera el almidón del arroz para lograr una textura ultra cremosa.",
        prep_time="45 min",
        calories="190 kcal",
        servings="6 porc.",
        domain_text="recetadolce.com",
    )
