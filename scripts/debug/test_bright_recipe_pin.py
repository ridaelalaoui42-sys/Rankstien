"""Prototype for the bright, recipe-aware infographic pin matching user reference."""

from pathlib import Path
import re
from PIL import Image, ImageDraw, ImageFilter, ImageFont

PIN_W = 1000
PIN_H = 1500

FONTS_DIR = Path("rankstein/assets/fonts")
WIN_FONTS = Path("C:/Windows/Fonts")

def get_font(font_name: str, size: int) -> ImageFont.FreeTypeFont:
    for candidate in [FONTS_DIR / font_name, WIN_FONTS / font_name]:
        if candidate.exists():
            try:
                return ImageFont.truetype(str(candidate), size)
            except Exception:
                pass
    return ImageFont.load_default(size=size)

def draw_ribbon(draw, xy, fill, text, font, text_color=(255, 255, 255), flourish="🌿"):
    x1, y1, x2, y2 = xy
    h = y2 - y1
    w = x2 - x1
    r = h // 2
    # Draw rounded ribbon pill
    draw.rounded_rectangle((x1, y1, x2, y2), radius=r, fill=fill)
    
    # Text with flourishes
    full_text = f"{flourish}  {text}  {flourish}" if flourish else text
    tb = draw.textbbox((0, 0), full_text, font=font)
    tw = tb[2] - tb[0]
    th = tb[3] - tb[1]
    tx = x1 + (w - tw) // 2
    ty = y1 + (h - th) // 2 - 2
    draw.text((tx, ty), full_text, font=font, fill=text_color)

def draw_badge(draw, center, radius, fill, lines, font, text_color=(255, 255, 255)):
    cx, cy = center
    draw.ellipse((cx - radius, cy - radius, cx + radius, cy + radius), fill=fill)
    # Draw inner dashed or thin white ring
    draw.ellipse((cx - radius + 5, cy - radius + 5, cx + radius - 5, cy + radius - 5), outline=(255, 255, 255, 180), width=2)
    
    # Render centered lines
    total_h = sum(draw.textbbox((0, 0), l, font=font)[3] - draw.textbbox((0, 0), l, font=font)[1] + 4 for l in lines)
    cur_y = cy - total_h // 2
    for l in lines:
        tb = draw.textbbox((0, 0), l, font=font)
        tw = tb[2] - tb[0]
        th = tb[3] - tb[1]
        draw.text((cx - tw // 2, cur_y), l, font=font, fill=text_color)
        cur_y += th + 4

def generate_bright_pin(
    hero_path: str,
    output_path: str,
    title_lead: str = "Ensalada de",
    title_hero: str = "Zanahoria",
    title_sub: str = "con Manzana,",
    title_sub_hero: str = "Piña y Yogur",
    description: str = "¡Una combinación fresca y deliciosa que no puedes perderte! Esta ensalada de zanahoria con manzana, piña y yogur es perfecta para cualquier ocasión.",
    ingredients: list = None,
    steps: list = None,
    tip: str = "Puedes añadir nueces tostadas para darle un toque crujiente y delicioso.",
    prep_time: str = "15 min",
    calories: str = "150 kcal",
    servings: str = "4 porc.",
    domain_text: str = "recetagenial.com",
):
    ingredients = ingredients or [
        "2 zanahorias medianas, ralladas",
        "1 manzana verde, cortada en cubitos",
        "1 taza de piña en trozos",
        "1/2 taza de yogur natural",
        "1 cucharada de miel",
    ]
    steps = steps or [
        "Mezcla las zanahorias ralladas, la manzana y la piña en un tazón grande.",
        "En otro recipiente, combina el yogur natural y la miel hasta integrar.",
        "Vierte la mezcla de yogur sobre la ensalada de zanahoria, manzana y piña.",
        "Mezcla bien y refrigera al menos 30 minutos antes de servir bien fría.",
    ]

    # Colors (Fresh Salad Palette from user reference)
    c_bg = (250, 248, 242)           # Warm organic cream
    c_ribbon_green = (78, 125, 40)   # Lush garden green
    c_accent_orange = (232, 99, 26)  # Bright carrot orange
    c_title_dark = (42, 68, 30)      # Deep forest green
    c_ink = (40, 36, 32)             # Deep charcoal text
    c_card_bg = (255, 255, 255)      # Crisp white
    c_card_border = (228, 222, 210)  # Soft cream border
    c_meta_bg = (246, 242, 233)      # Meta card soft cream

    # Fonts
    f_kicker = get_font("Pacifico-Regular.ttf", 26)
    f_title_base = get_font("DMSerifDisplay-Regular.ttf", 52)
    f_title_accent = get_font("Pacifico-Regular.ttf", 66)
    f_desc = get_font("Poppins-Regular.ttf", 19)
    f_ribbon = get_font("Montserrat-Bold.ttf", 24)
    f_badge = get_font("Montserrat-Bold.ttf", 17)
    f_meta_lbl = get_font("Montserrat-Bold.ttf", 15)
    f_meta_val = get_font("Montserrat-Bold.ttf", 20)
    f_ing = get_font("Poppins-SemiBold.ttf", 20)
    f_step_num = get_font("Montserrat-Bold.ttf", 22)
    f_step_txt = get_font("Poppins-Regular.ttf", 17)
    f_tip_title = get_font("DMSerifDisplay-Regular.ttf", 26)
    f_tip_txt = get_font("Poppins-Regular.ttf", 17)
    f_flair = get_font("Pacifico-Regular.ttf", 25)
    f_footer = get_font("Poppins-SemiBold.ttf", 19)

    # 1. Base Canvas
    canvas = Image.new("RGBA", (PIN_W, PIN_H), (*c_bg, 255))
    draw = ImageDraw.Draw(canvas, "RGBA")

    # Delicate outer stitched border
    draw.rounded_rectangle((22, 22, PIN_W - 22, PIN_H - 22), radius=28, outline=(225, 218, 204), width=2)
    # Subtle leaf corner stamps
    corner_leaf_font = get_font("Segoe-UI-Emoji.ttf", 22)
    for cx, cy in [(32, 32), (PIN_W - 54, 32), (32, PIN_H - 54), (PIN_W - 54, PIN_H - 54)]:
        draw.text((cx, cy), "🌿", font=corner_leaf_font, fill=(120, 150, 90, 180))

    # 2. Top-Left Wavy Kicker Banner
    kicker_text = "¡Una combinación fresca y deliciosa!"
    kb = draw.textbbox((0, 0), kicker_text, font=f_kicker)
    kw = kb[2] - kb[0] + 50
    draw.rounded_rectangle((48, 42, 48 + kw, 94), radius=18, fill=c_accent_orange)
    draw.text((73, 50), kicker_text, font=f_kicker, fill=(255, 255, 255))

    # 3. Multi-Font Title
    cur_y = 118
    # Line 1: Lead (Base font)
    draw.text((50, cur_y), title_lead, font=f_title_base, fill=c_title_dark)
    cur_y += 58
    # Line 2: Main Hero Noun (Accent Script font)
    draw.text((50, cur_y), title_hero, font=f_title_accent, fill=c_accent_orange)
    cur_y += 74
    # Line 3: Sub Lead (Base font)
    draw.text((50, cur_y), title_sub, font=f_title_base, fill=c_title_dark)
    cur_y += 58
    # Line 4: Second Hero Noun (Accent Script font)
    draw.text((50, cur_y), title_sub_hero, font=f_title_accent, fill=c_accent_orange)
    cur_y += 78

    # Small decorative divider
    draw.line([(50, cur_y), (140, cur_y)], fill=c_accent_orange, width=3)
    draw.text((150, cur_y - 14), "🌿", font=corner_leaf_font, fill=c_ribbon_green)
    draw.line([(185, cur_y), (275, cur_y)], fill=c_accent_orange, width=3)
    cur_y += 20

    # 4. Appetizing Description Paragraph
    words = description.split()
    desc_lines = []
    cur_l = ""
    for w in words:
        cand = f"{cur_l} {w}".strip()
        if cur_l and draw.textbbox((0, 0), cand, font=f_desc)[2] > 390:
            desc_lines.append(cur_l)
            cur_l = w
        else:
            cur_l = cand
    if cur_l:
        desc_lines.append(cur_l)

    for dl in desc_lines[:4]:
        draw.text((50, cur_y), dl, font=f_desc, fill=c_ink)
        cur_y += 28

    # 5. Top-Right Hero Food Photo (Framed bowl circle/squircle)
    with Image.open(hero_path) as h_img:
        from rankstein.remaster_variants import _cover
        hero_sq = _cover(h_img, 460, 460, focus_y=0.42).convert("RGBA")
    
    # Create circular mask
    mask = Image.new("L", (460, 460), 0)
    mask_draw = ImageDraw.Draw(mask)
    mask_draw.ellipse((0, 0, 460, 460), fill=255)

    # Soft drop shadow behind circular hero photo
    shadow = Image.new("RGBA", (500, 500), (0, 0, 0, 0))
    s_draw = ImageDraw.Draw(shadow)
    s_draw.ellipse((20, 20, 480, 480), fill=(20, 15, 10, 80))
    shadow = shadow.filter(ImageFilter.GaussianBlur(16))
    canvas.paste(shadow, (PIN_W - 495 - 20, 16), shadow)

    # Paste hero circle
    canvas.paste(hero_sq, (PIN_W - 460 - 35, 36), mask)

    # White border ring around hero bowl
    draw.ellipse((PIN_W - 460 - 35, 36, PIN_W - 35, 496), outline=(255, 255, 255), width=6)

    # 6. Floating Stamp Badge over hero photo
    draw_badge(
        draw,
        center=(PIN_W - 105, 410),
        radius=85,
        fill=c_ribbon_green,
        lines=["FRESCA,", "SALUDABLE Y", "LLENA DE", "SABOR ♡"],
        font=f_badge,
        text_color=(255, 255, 255),
    )

    # 7. Middle Row: Left Column (INGREDIENTES) & Right Column (METRICS CARD)
    mid_y = 515

    # ── Left Column: INGREDIENTES ──
    ing_box_w = 425
    draw_ribbon(draw, (45, mid_y, 45 + 320, mid_y + 44), c_ribbon_green, "INGREDIENTES", f_ribbon, flourish="🌿")
    
    ing_card_y = mid_y + 56
    ing_card_h = 240
    # Soft white card
    draw.rounded_rectangle((45, ing_card_y, 45 + ing_box_w, ing_card_y + ing_card_h), radius=18, fill=c_card_bg, outline=c_card_border, width=1)
    
    # Render Ingredients with cute colored bullets
    cur_ing_y = ing_card_y + 16
    for item in ingredients[:5]:
        draw.text((64, cur_ing_y - 2), "•", font=get_font("Montserrat-Bold.ttf", 26), fill=c_accent_orange)
        # Wrap item if needed
        iw = draw.textbbox((0, 0), item, font=f_ing)[2]
        if iw > (ing_box_w - 60):
            # Split into 2 lines
            words = item.split()
            l1, l2 = " ".join(words[:len(words)//2]), " ".join(words[len(words)//2:])
            draw.text((88, cur_ing_y), l1, font=f_ing, fill=c_ink)
            cur_ing_y += 24
            draw.text((88, cur_ing_y), l2, font=f_ing, fill=c_ink)
            cur_ing_y += 28
        else:
            draw.text((88, cur_ing_y), item, font=f_ing, fill=c_ink)
            cur_ing_y += 42

    # ── Right Column: METRICS CARD ──
    meta_x = 495
    meta_w = PIN_W - meta_x - 45
    meta_y = mid_y + 12
    meta_h = 284
    draw.rounded_rectangle((meta_x, meta_y, meta_x + meta_w, meta_y + meta_h), radius=22, fill=c_meta_bg, outline=(226, 217, 202), width=2)
    
    # 3 Stat Columns inside Meta Card
    stats = [
        ("⏱️", "TIEMPO DE\nPREPARACIÓN", prep_time),
        ("🔥", "CALORÍAS", calories),
        ("👥", "PORCIONES", servings),
    ]
    col_w = meta_w // 3
    for idx, (icon, label, val) in enumerate(stats):
        col_cx = meta_x + idx * col_w + col_w // 2
        # Icon
        draw.text((col_cx - 16, meta_y + 24), icon, font=corner_leaf_font, fill=c_title_dark)
        # Label
        lbl_lines = label.split("\n")
        lbl_y = meta_y + 68
        for ll in lbl_lines:
            lb = draw.textbbox((0, 0), ll, font=f_meta_lbl)
            draw.text((col_cx - (lb[2] - lb[0]) // 2, lbl_y), ll, font=f_meta_lbl, fill=(100, 90, 80))
            lbl_y += 18
        
        # Rounded orange value pill
        pill_w = col_w - 24
        pill_h = 44
        pill_x = col_cx - pill_w // 2
        pill_y = meta_y + 128
        draw.rounded_rectangle((pill_x, pill_y, pill_x + pill_w, pill_y + pill_h), radius=14, fill=c_accent_orange)
        vb = draw.textbbox((0, 0), val, font=f_meta_val)
        draw.text((col_cx - (vb[2] - vb[0]) // 2, pill_y + 10), val, font=f_meta_val, fill=(255, 255, 255))

    # Divider line inside meta card
    draw.line([(meta_x + 20, meta_y + 195), (meta_x + meta_w - 20, meta_y + 195)], fill=(225, 215, 200), width=1)
    # Bottom callout in meta card
    draw.text((meta_x + 30, meta_y + 215), "🌿 100% Saludable & Natural", font=get_font("Poppins-SemiBold.ttf", 17), fill=c_ribbon_green)
    draw.text((meta_x + 30, meta_y + 242), "Perfecta para comidas ligeras y cenas", font=get_font("Poppins-Regular.ttf", 15), fill=(120, 110, 100))

    # 8. PASO A PASO Section
    steps_y = 835
    draw_ribbon(draw, ((PIN_W - 360) // 2, steps_y, (PIN_W + 360) // 2, steps_y + 44), c_ribbon_green, "PASO A PASO", f_ribbon, flourish="🌿")

    # 4 Steps Cards in a 2x2 grid or horizontal sequence
    # Let's do 4 horizontal step cards with numbered badges!
    step_grid_y = steps_y + 60
    card_w = (PIN_W - 90 - 3 * 18) // 4  # 4 cards
    card_h = 245

    for idx, step_txt in enumerate(steps[:4], 1):
        sc_x = 45 + (idx - 1) * (card_w + 18)
        # Step card container
        draw.rounded_rectangle((sc_x, step_grid_y, sc_x + card_w, step_grid_y + card_h), radius=16, fill=c_card_bg, outline=c_card_border, width=1)
        
        # Step header banner with numbered badge
        draw.rounded_rectangle((sc_x, step_grid_y, sc_x + card_w, step_grid_y + 48), radius=16, fill=c_meta_bg)
        draw.rectangle((sc_x, step_grid_y + 30, sc_x + card_w, step_grid_y + 48), fill=c_meta_bg)
        
        # Number badge
        draw.ellipse((sc_x + 12, step_grid_y + 8, sc_x + 44, step_grid_y + 40), fill=c_accent_orange)
        nb = draw.textbbox((0, 0), str(idx), font=f_step_num)
        draw.text((sc_x + 28 - (nb[2] - nb[0]) // 2, step_grid_y + 12), str(idx), font=f_step_num, fill=(255, 255, 255))
        
        draw.text((sc_x + 52, step_grid_y + 14), f"Paso {idx}", font=get_font("Montserrat-Bold.ttf", 17), fill=c_title_dark)

        # Step text wrapped
        words = step_txt.split()
        st_lines = []
        cur_st = ""
        for w in words:
            cand = f"{cur_st} {w}".strip()
            if cur_st and draw.textbbox((0, 0), cand, font=f_step_txt)[2] > (card_w - 24):
                st_lines.append(cur_st)
                cur_st = w
            else:
                cur_st = cand
        if cur_st:
            st_lines.append(cur_st)

        st_y = step_grid_y + 60
        for sl in st_lines[:7]:
            draw.text((sc_x + 12, st_y), sl, font=f_step_txt, fill=c_ink)
            st_y += 24

    # 9. Bottom Section: Consejo (Tip) + Catchphrase + ¡DISFRUTA! Mini Photo
    bot_y = 1160

    # ── Left: Consejo Card ──
    tip_w = 425
    tip_h = 195
    # Card with dashed border
    draw.rounded_rectangle((45, bot_y, 45 + tip_w, bot_y + tip_h), radius=18, fill=c_meta_bg, outline=(215, 205, 190), width=1)
    draw.text((65, bot_y + 16), "💡", font=corner_leaf_font, fill=c_accent_orange)
    draw.text((105, bot_y + 14), "Consejo del Chef:", font=f_tip_title, fill=c_title_dark)

    # Wrap tip
    tip_words = tip.split()
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

    ty = bot_y + 62
    for tl in tip_lines[:4]:
        draw.text((65, ty), tl, font=f_tip_txt, fill=c_ink)
        ty += 26

    # ── Middle: Appetizing Script Sign-off ──
    callout_txt1 = "Saludable, colorida y"
    callout_txt2 = "perfecta para cualquier ocasión"
    draw.text((495, bot_y + 35), callout_txt1, font=f_flair, fill=c_accent_orange)
    draw.text((495, bot_y + 75), callout_txt2, font=f_flair, fill=c_accent_orange)
    draw.text((495, bot_y + 125), "🌿  ¡Preparada en sólo 15 minutos!  🌿", font=get_font("Poppins-SemiBold.ttf", 18), fill=c_ribbon_green)

    # ── Right: ¡DISFRUTA! Thumbnail Preview ──
    mini_thumb_size = 195
    mini_x = PIN_W - mini_thumb_size - 45
    with Image.open(hero_path) as h_img:
        from rankstein.remaster_variants import _cover
        mini_thumb = _cover(h_img, mini_thumb_size, mini_thumb_size, focus_y=0.5).convert("RGBA")
    
    mini_mask = Image.new("L", (mini_thumb_size, mini_thumb_size), 0)
    mini_mask_draw = ImageDraw.Draw(mini_mask)
    mini_mask_draw.rounded_rectangle((0, 0, mini_thumb_size, mini_thumb_size), radius=22, fill=255)
    canvas.paste(mini_thumb, (mini_x, bot_y), mini_mask)
    draw.rounded_rectangle((mini_x, bot_y, mini_x + mini_thumb_size, bot_y + mini_thumb_size), radius=22, outline=(255, 255, 255), width=4)

    # Mini ribbon across bottom of thumbnail: ¡DISFRUTA!
    draw.rounded_rectangle((mini_x + 15, bot_y + mini_thumb_size - 38, mini_x + mini_thumb_size - 15, bot_y + mini_thumb_size - 6), radius=12, fill=c_ribbon_green)
    db = draw.textbbox((0, 0), "¡DISFRUTA!", font=get_font("Montserrat-Bold.ttf", 16))
    draw.text((mini_x + mini_thumb_size // 2 - (db[2] - db[0]) // 2, bot_y + mini_thumb_size - 32), "¡DISFRUTA!", font=get_font("Montserrat-Bold.ttf", 16), fill=(255, 255, 255))

    # 10. Bottom Full-Width Themed Branding Bar
    bar_y = 1425
    draw.rounded_rectangle((35, bar_y, PIN_W - 35, bar_y + 50), radius=25, fill=c_title_dark)
    footer_text = f"🌿 #EnsaladaSaludable  ♡  #RecetaFácil  ♡  #ComidaFresca  •  {domain_text}"
    ftb = draw.textbbox((0, 0), footer_text, font=f_footer)
    draw.text(((PIN_W - (ftb[2] - ftb[0])) // 2, bar_y + 13), footer_text, font=f_footer, fill=(255, 255, 255))

    # Save
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    canvas.convert("RGB").save(str(out), "JPEG", quality=95)
    print(f"Generated bright infographic pin: {out} ({out.stat().st_size} bytes)")
    return str(out)

if __name__ == "__main__":
    generate_bright_pin(
        hero_path="nanobanana-output/ensalada-de-manzana-cremosa-y-refrescante-hero.jpg",
        output_path="C:/Users/REDX420/.gemini/antigravity/brain/4def31ef-1cbb-4e58-b00a-3c4bea3fd439/bright_infographic_pin_test.jpg",
    )
