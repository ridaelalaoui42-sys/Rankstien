"""Comprehensive recipe-aware pin generation test with macro crops, polished banners and title wrapping."""

import math
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

# ── Procedural Vector Icons ──────────────────────────────────────────────────

def draw_vector_leaf(draw: ImageDraw.ImageDraw, cx: float, cy: float, size: float, color: tuple, angle_deg: float = 0):
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

def draw_vector_sprig(draw: ImageDraw.ImageDraw, cx: float, cy: float, size: float, color: tuple):
    draw_vector_leaf(draw, cx - size * 0.45, cy + 2, size * 0.75, color, angle_deg=-38)
    draw_vector_leaf(draw, cx + size * 0.45, cy + 2, size * 0.75, color, angle_deg=38)
    draw_vector_leaf(draw, cx, cy - size * 0.25, size * 0.9, color, angle_deg=0)
    # Tiny center stem line
    draw.line([(cx, cy + size * 0.5), (cx, cy - size * 0.1)], fill=color, width=2)

def draw_vector_clock(draw: ImageDraw.ImageDraw, cx: float, cy: float, r: float, color: tuple):
    draw.ellipse((cx - r, cy - r, cx + r, cy + r), outline=color, width=3)
    draw.line([(cx, cy), (cx, cy - r * 0.58)], fill=color, width=3)
    draw.line([(cx, cy), (cx + r * 0.52, cy)], fill=color, width=3)
    draw.ellipse((cx - 2, cy - 2, cx + 2, cy + 2), fill=color)

def draw_vector_flame(draw: ImageDraw.ImageDraw, cx: float, cy: float, size: float, color: tuple):
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
    hr = size * 0.24
    draw.ellipse((cx - hr, cy - size * 0.5, cx + hr, cy - size * 0.5 + 2 * hr), fill=color)
    draw.chord((cx - size * 0.48, cy - size * 0.05, cx + size * 0.48, cy + size * 0.68), start=0, end=180, fill=color)

def draw_vector_bulb(draw: ImageDraw.ImageDraw, cx: float, cy: float, size: float, color: tuple):
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
    x1, y1, x2, y2 = xy
    h = y2 - y1
    w = x2 - x1
    r = h // 2
    # Draw rounded ribbon pill with soft outline
    draw.rounded_rectangle((x1, y1, x2, y2), radius=r, fill=bg_color)
    draw.rounded_rectangle((x1 + 3, y1 + 3, x2 - 3, y2 - 3), radius=r - 2, outline=(255, 255, 255, 80), width=1)
    
    # Text
    tb = draw.textbbox((0, 0), text, font=font)
    tw = tb[2] - tb[0]
    th = tb[3] - tb[1]
    tx = x1 + (w - tw) // 2
    ty = y1 + (h - th) // 2 - 2
    draw.text((tx, ty), text, font=font, fill=text_color)
    
    # Left and Right Vector Sprigs
    sprig_color = (255, 255, 255, 235)
    draw_vector_sprig(draw, tx - 32, y1 + h // 2 - 1, 24, sprig_color)
    draw_vector_sprig(draw, tx + tw + 32, y1 + h // 2 - 1, 24, sprig_color)

# ── Recipe Themes & Font Suites ───────────────────────────────────────────

class RecipeTheme:
    def __init__(
        self,
        name: str,
        primary_ribbon: tuple[int, int, int],
        accent_pill: tuple[int, int, int],
        title_dark: tuple[int, int, int],
        font_title_base: str,
        font_title_accent: str,
        font_ribbon: str,
        font_flair: str,
        kicker_default: str,
        badge_lines: list[str],
        hashtag_bar: str,
    ):
        self.name = name
        self.primary_ribbon = primary_ribbon
        self.accent_pill = accent_pill
        self.title_dark = title_dark
        self.font_title_base = font_title_base
        self.font_title_accent = font_title_accent
        self.font_ribbon = font_ribbon
        self.font_flair = font_flair
        self.kicker_default = kicker_default
        self.badge_lines = badge_lines
        self.hashtag_bar = hashtag_bar

THEMES = {
    "ensalada": RecipeTheme(
        name="ensalada_saludable",
        primary_ribbon=(78, 125, 40),    # Garden Green
        accent_pill=(232, 99, 26),      # Carrot Orange
        title_dark=(42, 68, 30),        # Forest Green
        font_title_base="DMSerifDisplay-Regular.ttf",
        font_title_accent="Pacifico-Regular.ttf",
        font_ribbon="Montserrat-Bold.ttf",
        font_flair="Pacifico-Regular.ttf",
        kicker_default="¡Una combinación fresca y deliciosa!",
        badge_lines=["FRESCA,", "SALUDABLE Y", "LLENA DE", "SABOR"],
        hashtag_bar="#EnsaladaSaludable • #RecetaFácil • #ComidaFresca",
    ),
    "postre": RecipeTheme(
        name="postre_reposteria",
        primary_ribbon=(190, 24, 75),    # Berry Ruby
        accent_pill=(217, 119, 6),      # Warm Caramel Honey
        title_dark=(76, 5, 25),         # Cacao Burgundy
        font_title_base="AbrilFatface-Regular.ttf",
        font_title_accent="DancingScript-Bold.ttf",
        font_ribbon="DMSerifDisplay-Regular.ttf",
        font_flair="DancingScript-Bold.ttf",
        kicker_default="¡Irresistible, dulce y delicioso!",
        badge_lines=["DULCE,", "CREMOSA Y", "MUY FÁCIL", "DE HACER"],
        hashtag_bar="#PostreCasero • #ReposteríaFácil • #DulcesDeliciosos",
    ),
    "arroz": RecipeTheme(
        name="arroz_paella",
        primary_ribbon=(194, 65, 12),    # Saffron Terracotta
        accent_pill=(229, 139, 0),      # Saffron Gold
        title_dark=(75, 28, 10),        # Deep Terracotta
        font_title_base="AbrilFatface-Regular.ttf",
        font_title_accent="Playball-Regular.ttf",
        font_ribbon="Montserrat-Bold.ttf",
        font_flair="Playball-Regular.ttf",
        kicker_default="¡Tradición mediterránea en cada bocado!",
        badge_lines=["TRADICIONAL,", "SABROSA Y", "EN SU PUNTO", "PERFECTO"],
        hashtag_bar="#ArrozTradicional • #PaellaCasera • #SaborEspañol",
    ),
    "carne": RecipeTheme(
        name="carne_asados",
        primary_ribbon=(153, 27, 27),    # Roast Crimson
        accent_pill=(234, 88, 12),      # Flame Ember Orange
        title_dark=(69, 10, 10),        # Smokey Maroon
        font_title_base="Montserrat-Bold.ttf",
        font_title_accent="AbrilFatface-Regular.ttf",
        font_ribbon="Montserrat-Bold.ttf",
        font_flair="Caveat-Bold.ttf",
        kicker_default="¡Jugosa, tierna y llena de sabor!",
        badge_lines=["JUGOSA,", "CRUJIENTE Y", "DELICIOSA", "AL HORNO"],
        hashtag_bar="#CarneAlHorno • #RecetaCasera • #CocinaTradicional",
    ),
    "pescado": RecipeTheme(
        name="pescado_marisco",
        primary_ribbon=(8, 145, 178),    # Coastal Aqua Marine
        accent_pill=(244, 63, 94),      # Coral Rose
        title_dark=(12, 74, 110),       # Deep Marine Navy
        font_title_base="Cinzel[wght].ttf",
        font_title_accent="Lora-Italic[wght].ttf",
        font_ribbon="Montserrat-Bold.ttf",
        font_flair="DancingScript-Bold.ttf",
        kicker_default="¡Fresco, ligero y con aroma a mar!",
        badge_lines=["FRESCO,", "LIGERO Y", "100% MARINO", "DELICIOSO"],
        hashtag_bar="#PescadoFresco • #Mariscos • #CocinaMediterránea",
    ),
    "pasta": RecipeTheme(
        name="pasta_italiana",
        primary_ribbon=(220, 38, 38),    # Pomodoro Red
        accent_pill=(22, 163, 74),      # Basil Green
        title_dark=(69, 10, 10),        # Chianti Wine
        font_title_base="PlayfairDisplay.ttf",
        font_title_accent="Lobster-Regular.ttf",
        font_ribbon="Montserrat-Bold.ttf",
        font_flair="Pacifico-Regular.ttf",
        kicker_default="¡El auténtico sabor de la cocina italiana!",
        badge_lines=["AL DENTE,", "CREMOSA Y", "LLENA DE", "SABOR"],
        hashtag_bar="#PastaCasera • #CocinaItaliana • #RecetaFácil",
    ),
}

def resolve_theme_for_text(text: str) -> RecipeTheme:
    t = (text or "").lower()
    if any(k in t for k in ("ensalada", "verdura", "aguacate", "quinoa", "kale", "gazpacho", "saludable", "verde", "detox")):
        return THEMES["ensalada"]
    if any(k in t for k in ("postre", "tarta", "pastel", "bizcocho", "galleta", "chocolate", "cacao", "dulce", "crema", "flan", "cheesecake")):
        return THEMES["postre"]
    if any(k in t for k in ("arroz", "paella", "risotto", "azafran", "azafrán", "fideua", "guiso", "estofado", "lenteja", "garbanzo")):
        return THEMES["arroz"]
    if any(k in t for k in ("carne", "pollo", "ternera", "cerdo", "asado", "bbq", "solomillo", "costilla", "alitas", "hamburguesa")):
        return THEMES["carne"]
    if any(k in t for k in ("pescado", "marisco", "salmon", "salmón", "atun", "atún", "merluza", "bacalao", "gamba", "pulpo", "calamar")):
        return THEMES["pescado"]
    if any(k in t for k in ("pasta", "pizza", "espagueti", "macarron", "macarrón", "lasana", "lasaña", "tomate", "pomodoro")):
        return THEMES["pasta"]
    return THEMES["ensalada"]

def fit_text_line(draw: ImageDraw.ImageDraw, text: str, font_name: str, max_width: int, preferred_size: int, min_size: int = 34):
    for size in range(preferred_size, min_size - 1, -2):
        font = get_font(font_name, size)
        tb = draw.textbbox((0, 0), text, font=font)
        if (tb[2] - tb[0]) <= max_width:
            return font, [text]
    # If still doesn't fit, split into 2 lines
    words = text.split()
    half = len(words) // 2
    l1 = " ".join(words[:half])
    l2 = " ".join(words[half:])
    font = get_font(font_name, min_size)
    return font, [l1, l2]

def generate_recipe_aware_pin(
    hero_path: str,
    output_path: str,
    title: str,
    description: str,
    ingredients: list[str],
    steps: list[str],
    tip: str = "",
    prep_time: str = "20 min",
    calories: str = "220 kcal",
    servings: str = "4 porc.",
    domain_text: str = "recetagenial.com",
) -> str:
    theme = resolve_theme_for_text(f"{title} {' '.join(ingredients)}")

    # Palette
    c_bg = (250, 248, 242)
    c_ribbon = theme.primary_ribbon
    c_accent = theme.accent_pill
    c_title = theme.title_dark
    c_ink = (40, 36, 32)
    c_card_bg = (255, 255, 255)
    c_card_border = (228, 222, 210)
    c_meta_bg = (246, 242, 233)

    # 1. Base Canvas
    canvas = Image.new("RGBA", (PIN_W, PIN_H), (*c_bg, 255))
    draw = ImageDraw.Draw(canvas, "RGBA")

    # Delicate outer stitched border
    draw.rounded_rectangle((22, 22, PIN_W - 22, PIN_H - 22), radius=28, outline=(225, 218, 204), width=2)
    for cx, cy in [(40, 40), (PIN_W - 40, 40), (40, PIN_H - 40), (PIN_W - 40, PIN_H - 40)]:
        draw_vector_sprig(draw, cx, cy, 20, (*c_ribbon, 160))

    # 2. Top-Left Kicker Banner
    f_kicker = get_font(theme.font_flair, 25)
    kicker_text = theme.kicker_default
    kb = draw.textbbox((0, 0), kicker_text, font=f_kicker)
    kw = kb[2] - kb[0] + 50
    draw.rounded_rectangle((48, 42, 48 + kw, 94), radius=18, fill=c_accent)
    draw.text((73, 50), kicker_text, font=f_kicker, fill=(255, 255, 255))

    # 3. Multi-Font Title with dynamic wrapping
    max_title_w = 410
    cur_y = 116

    # Smart split
    dish_match = re.match(r"^(ensalada de|tarta de|pastel de|bizcocho de|arroz con|paella de|guiso de|sopa de|crema de|pollo al|solomillo de|lomo de)\s+(.*)$", title.strip(), re.IGNORECASE)
    if dish_match:
        lead_txt = dish_match.group(1).title()
        rest_txt = dish_match.group(2).strip()
    else:
        words = title.strip().split()
        lead_txt = " ".join(words[:2]).title()
        rest_txt = " ".join(words[2:]).strip()

    # Draw Lead line
    f_lead, lead_lines = fit_text_line(draw, lead_txt, theme.font_title_base, max_title_w, preferred_size=50, min_size=38)
    for ll in lead_lines:
        draw.text((50, cur_y), ll, font=f_lead, fill=c_title)
        cur_y += draw.textbbox((0, 0), ll, font=f_lead)[3] - draw.textbbox((0, 0), ll, font=f_lead)[1] + 12

    # Draw Hero noun(s) with Accent font
    f_hero, hero_lines = fit_text_line(draw, rest_txt.title(), theme.font_title_accent, max_title_w, preferred_size=58, min_size=36)
    for hl in hero_lines:
        draw.text((50, cur_y), hl, font=f_hero, fill=c_accent)
        cur_y += draw.textbbox((0, 0), hl, font=f_hero)[3] - draw.textbbox((0, 0), hl, font=f_hero)[1] + 14

    # Decorative divider
    draw.line([(50, cur_y), (140, cur_y)], fill=c_accent, width=3)
    draw_vector_sprig(draw, 165, cur_y, 20, c_ribbon)
    draw.line([(190, cur_y), (280, cur_y)], fill=c_accent, width=3)
    cur_y += 18

    # 4. Appetizing Description Paragraph
    f_desc = get_font("Poppins-Regular.ttf", 18)
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
        cur_y += 26

    # 5. Top-Right Hero Food Photo (Framed bowl circle)
    from rankstein.remaster_variants import _cover
    with Image.open(hero_path) as h_img:
        hero_sq = _cover(h_img, 460, 460, focus_y=0.42).convert("RGBA")
    
    mask = Image.new("L", (460, 460), 0)
    mask_draw = ImageDraw.Draw(mask)
    mask_draw.ellipse((0, 0, 460, 460), fill=255)

    shadow = Image.new("RGBA", (500, 500), (0, 0, 0, 0))
    s_draw = ImageDraw.Draw(shadow)
    s_draw.ellipse((20, 20, 480, 480), fill=(20, 15, 10, 80))
    shadow = shadow.filter(ImageFilter.GaussianBlur(16))
    canvas.paste(shadow, (PIN_W - 495 - 20, 16), shadow)

    canvas.paste(hero_sq, (PIN_W - 460 - 35, 36), mask)
    draw.ellipse((PIN_W - 460 - 35, 36, PIN_W - 35, 496), outline=(255, 255, 255), width=6)

    # 6. Floating Stamp Badge over hero photo
    cx, cy = PIN_W - 105, 410
    radius = 85
    draw.ellipse((cx - radius, cy - radius, cx + radius, cy + radius), fill=c_ribbon)
    draw.ellipse((cx - radius + 5, cy - radius + 5, cx + radius - 5, cy + radius - 5), outline=(255, 255, 255, 180), width=2)
    
    f_badge = get_font(theme.font_ribbon, 16)
    total_badge_h = len(theme.badge_lines) * 22
    b_y = cy - total_badge_h // 2
    for bl in theme.badge_lines:
        bb = draw.textbbox((0, 0), bl, font=f_badge)
        draw.text((cx - (bb[2] - bb[0]) // 2, b_y), bl, font=f_badge, fill=(255, 255, 255))
        b_y += 22

    # 7. Middle Row: Left Column (INGREDIENTES) & Right Column (METRICS CARD)
    mid_y = 515
    ing_box_w = 425
    f_ribbon = get_font(theme.font_ribbon, 24)
    draw_ribbon_banner(draw, (45, mid_y, 45 + 380, mid_y + 46), c_ribbon, "INGREDIENTES", f_ribbon)
    
    ing_card_y = mid_y + 58
    ing_card_h = 240
    draw.rounded_rectangle((45, ing_card_y, 45 + ing_box_w, ing_card_y + ing_card_h), radius=18, fill=c_card_bg, outline=c_card_border, width=1)
    
    f_ing = get_font("Poppins-SemiBold.ttf", 20)
    cur_ing_y = ing_card_y + 16
    for item in ingredients[:5]:
        draw.text((64, cur_ing_y - 2), "•", font=get_font("Montserrat-Bold.ttf", 26), fill=c_accent)
        iw = draw.textbbox((0, 0), item, font=f_ing)[2]
        if iw > (ing_box_w - 60):
            words = item.split()
            l1, l2 = " ".join(words[:len(words)//2]), " ".join(words[len(words)//2:])
            draw.text((88, cur_ing_y), l1, font=f_ing, fill=c_ink)
            cur_ing_y += 24
            draw.text((88, cur_ing_y), l2, font=f_ing, fill=c_ink)
            cur_ing_y += 28
        else:
            draw.text((88, cur_ing_y), item, font=f_ing, fill=c_ink)
            cur_ing_y += 42

    # Right Column: METRICS CARD
    meta_x = 495
    meta_w = PIN_W - meta_x - 45
    meta_y = mid_y + 12
    meta_h = 286
    draw.rounded_rectangle((meta_x, meta_y, meta_x + meta_w, meta_y + meta_h), radius=22, fill=c_meta_bg, outline=(226, 217, 202), width=2)
    
    col_w = meta_w // 3
    f_meta_lbl = get_font("Montserrat-Bold.ttf", 13)
    f_meta_val = get_font("Montserrat-Bold.ttf", 20)
    # Col 1: Time
    cx1 = meta_x + col_w // 2
    draw_vector_clock(draw, cx1, meta_y + 36, 16, c_title)
    draw.text((cx1 - 38, meta_y + 68), "TIEMPO DE\nPREPARACIÓN", font=f_meta_lbl, fill=(100, 90, 80))
    draw.rounded_rectangle((cx1 - (col_w - 24) // 2, meta_y + 128, cx1 + (col_w - 24) // 2, meta_y + 172), radius=14, fill=c_accent)
    tb1 = draw.textbbox((0, 0), prep_time, font=f_meta_val)
    draw.text((cx1 - (tb1[2] - tb1[0]) // 2, meta_y + 138), prep_time, font=f_meta_val, fill=(255, 255, 255))

    # Col 2: Calories
    cx2 = meta_x + col_w + col_w // 2
    draw_vector_flame(draw, cx2, meta_y + 36, 32, c_accent)
    draw.text((cx2 - 32, meta_y + 78), "CALORÍAS", font=f_meta_lbl, fill=(100, 90, 80))
    draw.rounded_rectangle((cx2 - (col_w - 24) // 2, meta_y + 128, cx2 + (col_w - 24) // 2, meta_y + 172), radius=14, fill=c_accent)
    tb2 = draw.textbbox((0, 0), calories, font=f_meta_val)
    draw.text((cx2 - (tb2[2] - tb2[0]) // 2, meta_y + 138), calories, font=f_meta_val, fill=(255, 255, 255))

    # Col 3: Servings
    cx3 = meta_x + 2 * col_w + col_w // 2
    draw_vector_people(draw, cx3, meta_y + 36, 30, c_title)
    draw.text((cx3 - 35, meta_y + 78), "PORCIONES", font=f_meta_lbl, fill=(100, 90, 80))
    draw.rounded_rectangle((cx3 - (col_w - 24) // 2, meta_y + 128, cx3 + (col_w - 24) // 2, meta_y + 172), radius=14, fill=c_accent)
    tb3 = draw.textbbox((0, 0), servings, font=f_meta_val)
    draw.text((cx3 - (tb3[2] - tb3[0]) // 2, meta_y + 138), servings, font=f_meta_val, fill=(255, 255, 255))

    # Callout line inside meta card
    draw.line([(meta_x + 20, meta_y + 195), (meta_x + meta_w - 20, meta_y + 195)], fill=(225, 215, 200), width=1)
    draw_vector_sprig(draw, meta_x + 36, meta_y + 225, 18, c_ribbon)
    draw.text((meta_x + 55, meta_y + 215), "100% Casero & Tradicional", font=get_font("Poppins-SemiBold.ttf", 17), fill=c_ribbon)
    draw.text((meta_x + 30, meta_y + 244), "Paso a paso fácil y garantizado", font=get_font("Poppins-Regular.ttf", 15), fill=(120, 110, 100))

    # 8. PASO A PASO Section with Macro Crop Images!
    steps_y = 835
    draw_ribbon_banner(draw, ((PIN_W - 410) // 2, steps_y, (PIN_W + 410) // 2, steps_y + 46), c_ribbon, "PASO A PASO", f_ribbon)

    step_grid_y = steps_y + 60
    card_w = (PIN_W - 90 - 3 * 18) // 4
    card_h = 245

    f_step_num = get_font("Montserrat-Bold.ttf", 20)
    f_step_txt = get_font("Poppins-Regular.ttf", 16)

    # 4 Macro focus crops of the dish image for steps 1..4 (like reference image!)
    crop_focuses = [0.2, 0.4, 0.6, 0.8]
    with Image.open(hero_path) as h_img:
        for idx, step_txt in enumerate(steps[:4], 1):
            sc_x = 45 + (idx - 1) * (card_w + 18)
            draw.rounded_rectangle((sc_x, step_grid_y, sc_x + card_w, step_grid_y + card_h), radius=16, fill=c_card_bg, outline=c_card_border, width=1)
            
            # Step photo thumbnail at top of card (height 100px)
            thumb_h = 92
            step_thumb = _cover(h_img, card_w, thumb_h, focus_y=crop_focuses[idx - 1]).convert("RGBA")
            t_mask = Image.new("L", (card_w, thumb_h), 0)
            t_mdraw = ImageDraw.Draw(t_mask)
            t_mdraw.rounded_rectangle((0, 0, card_w, thumb_h), radius=16, fill=255)
            # Flatten bottom corners of mask
            t_mdraw.rectangle((0, thumb_h - 16, card_w, thumb_h), fill=255)
            canvas.paste(step_thumb, (sc_x, step_grid_y), t_mask)

            # Circular Number badge on top-left of photo
            badge_r = 17
            draw.ellipse((sc_x + 8, step_grid_y + 8, sc_x + 8 + 2 * badge_r, step_grid_y + 8 + 2 * badge_r), fill=c_accent)
            draw.ellipse((sc_x + 10, step_grid_y + 10, sc_x + 6 + 2 * badge_r, step_grid_y + 6 + 2 * badge_r), outline=(255, 255, 255), width=2)
            nb = draw.textbbox((0, 0), str(idx), font=f_step_num)
            draw.text((sc_x + 8 + badge_r - (nb[2] - nb[0]) // 2, step_grid_y + 8 + badge_r - (nb[3] - nb[1]) // 2 - 1), str(idx), font=f_step_num, fill=(255, 255, 255))

            # Step text below photo
            words = step_txt.split()
            st_lines = []
            cur_st = ""
            for w in words:
                cand = f"{cur_st} {w}".strip()
                if cur_st and draw.textbbox((0, 0), cand, font=f_step_txt)[2] > (card_w - 20):
                    st_lines.append(cur_st)
                    cur_st = w
                else:
                    cur_st = cand
            if cur_st:
                st_lines.append(cur_st)

            st_y = step_grid_y + thumb_h + 10
            for sl in st_lines[:6]:
                draw.text((sc_x + 10, st_y), sl, font=f_step_txt, fill=c_ink)
                st_y += 22

    # 9. Bottom Section: Consejo + Catchphrase + ¡DISFRUTA! Mini Photo
    bot_y = 1160
    tip_w = 425
    tip_h = 195
    draw.rounded_rectangle((45, bot_y, 45 + tip_w, bot_y + tip_h), radius=18, fill=c_meta_bg, outline=(215, 205, 190), width=1)
    draw_vector_bulb(draw, 74, bot_y + 32, 28, c_accent)
    f_tip_title = get_font(theme.font_title_base, 25)
    draw.text((106, bot_y + 18), "Consejo del Chef:", font=f_tip_title, fill=c_title)

    f_tip_txt = get_font("Poppins-Regular.ttf", 17)
    tip_text = tip or "Sirve recién preparado para disfrutar al máximo su textura y aroma."
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

    ty = bot_y + 64
    for tl in tip_lines[:4]:
        draw.text((65, ty), tl, font=f_tip_txt, fill=c_ink)
        ty += 26

    # Middle Sign-off (balanced width)
    f_flair = get_font(theme.font_flair, 24)
    draw.text((495, bot_y + 34), "¡Deliciosa, casera y perfecta", font=f_flair, fill=c_accent)
    draw.text((495, bot_y + 72), "para cualquier ocasión!", font=f_flair, fill=c_accent)
    draw_vector_sprig(draw, 506, bot_y + 134, 18, c_ribbon)
    draw.text((524, bot_y + 124), "Lista en pocos minutos", font=get_font("Poppins-SemiBold.ttf", 18), fill=c_ribbon)

    # Right: Thumbnail Preview
    mini_thumb_size = 195
    mini_x = PIN_W - mini_thumb_size - 45
    with Image.open(hero_path) as h_img:
        mini_thumb = _cover(h_img, mini_thumb_size, mini_thumb_size, focus_y=0.5).convert("RGBA")
    mini_mask = Image.new("L", (mini_thumb_size, mini_thumb_size), 0)
    mini_mask_draw = ImageDraw.Draw(mini_mask)
    mini_mask_draw.rounded_rectangle((0, 0, mini_thumb_size, mini_thumb_size), radius=22, fill=255)
    canvas.paste(mini_thumb, (mini_x, bot_y), mini_mask)
    draw.rounded_rectangle((mini_x, bot_y, mini_x + mini_thumb_size, bot_y + mini_thumb_size), radius=22, outline=(255, 255, 255), width=4)

    draw.rounded_rectangle((mini_x + 15, bot_y + mini_thumb_size - 38, mini_x + mini_thumb_size - 15, bot_y + mini_thumb_size - 6), radius=12, fill=c_ribbon)
    db = draw.textbbox((0, 0), "¡DISFRUTA!", font=get_font("Montserrat-Bold.ttf", 16))
    draw.text((mini_x + mini_thumb_size // 2 - (db[2] - db[0]) // 2, bot_y + mini_thumb_size - 32), "¡DISFRUTA!", font=get_font("Montserrat-Bold.ttf", 16), fill=(255, 255, 255))

    # 10. Bottom Full-Width Themed Branding Bar
    bar_y = 1425
    draw.rounded_rectangle((35, bar_y, PIN_W - 35, bar_y + 50), radius=25, fill=c_title)
    f_footer = get_font("Poppins-SemiBold.ttf", 19)
    footer_text = f"{theme.hashtag_bar}  •  {domain_text}"
    ftb = draw.textbbox((0, 0), footer_text, font=f_footer)
    draw.text(((PIN_W - (ftb[2] - ftb[0])) // 2, bar_y + 13), footer_text, font=f_footer, fill=(255, 255, 255))

    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    canvas.convert("RGB").save(str(out), "JPEG", quality=95)
    print(f"Generated pin ({theme.name}): {out.name}")
    return str(out)

if __name__ == "__main__":
    brain = Path("C:/Users/REDX420/.gemini/antigravity/brain/4def31ef-1cbb-4e58-b00a-3c4bea3fd439")
    
    # 1. Ensalada
    generate_recipe_aware_pin(
        hero_path="nanobanana-output/ensalada-de-manzana-cremosa-y-refrescante-hero.jpg",
        output_path=str(brain / "pin_suite_01_ensalada_v2.jpg"),
        title="Ensalada de Zanahoria con Manzana, Piña y Yogur",
        description="¡Una combinación fresca y deliciosa que no puedes perderte! Esta ensalada de zanahoria con manzana, piña y yogur es perfecta para cualquier ocasión.",
        ingredients=[
            "2 zanahorias medianas, ralladas",
            "1 manzana verde en cubitos",
            "1 taza de piña en trozos",
            "1/2 taza de yogur natural",
            "1 cucharada de miel",
        ],
        steps=[
            "Mezcla las zanahorias ralladas, manzana y piña en un tazón.",
            "En otro recipiente combina el yogur y la miel suavemente.",
            "Vierte la mezcla de yogur sobre la ensalada de frutas.",
            "Mezcla bien y refrigera 30 min antes de servir fresca.",
        ],
        tip="Puedes añadir nueces tostadas para darle un toque crujiente irresistible.",
        prep_time="15 min",
        calories="150 kcal",
        servings="4 porc.",
        domain_text="recetagenial.com",
    )

    # 2. Chocolate
    generate_recipe_aware_pin(
        hero_path="nanobanana-output/bizcocho-chocolate-matilda-receta-definitiva-hero.jpg",
        output_path=str(brain / "pin_suite_02_chocolate_v2.jpg"),
        title="Bizcocho de Chocolate con Crema de Trufa y Avellanas",
        description="El bizcocho más esponjoso, húmedo e irresistible de chocolate. Perfecto para celebraciones o para darte un capricho goloso inolvidable.",
        ingredients=[
            "200 g de chocolate negro 70%",
            "150 g de harina de repostería",
            "4 huevos camperos frescos",
            "120 g de azúcar moreno",
            "100 g de mantequilla pomada",
        ],
        steps=[
            "Funde el chocolate negro con la mantequilla al baño maría.",
            "Bate los huevos con el azúcar hasta que doblen su volumen.",
            "Incorpora la harina tamizada con movimientos envolventes.",
            "Hornea a 180°C durante 30 minutos y deja templar.",
        ],
        tip="Usa chocolate con alto porcentaje de cacao para un sabor más intenso y profundo.",
        prep_time="40 min",
        calories="320 kcal",
        servings="8 porc.",
        domain_text="recetadolce.com",
    )

    # 3. Arroz
    generate_recipe_aware_pin(
        hero_path="nanobanana-output/arroz-con-leche-cremoso-en-vaso-hero.jpg",
        output_path=str(brain / "pin_suite_03_arroz_v2.jpg"),
        title="Arroz con Leche Tradicional y Canela en Rama",
        description="La receta de la abuela, cremosa y aromática con toque de limón y canela. Un postre tradicional que conquista todos los paladares.",
        ingredients=[
            "1 litro de leche entera fresca",
            "100 g de arroz redondo especial",
            "70 g de azúcar blanco fino",
            "1 rama de canela de Ceilán",
            "Piel de limón sin parte blanca",
        ],
        steps=[
            "Infusiona la leche con la canela y la piel de limón.",
            "Añade el arroz y cocina a fuego muy lento removiendo.",
            "Agrega el azúcar los últimos 10 minutos para cremosidad.",
            "Vierte en recipientes individuales y espolvorea canela.",
        ],
        tip="Remover constantemente libera el almidón del arroz para máxima cremosidad.",
        prep_time="45 min",
        calories="190 kcal",
        servings="6 porc.",
        domain_text="recetadolce.com",
    )
