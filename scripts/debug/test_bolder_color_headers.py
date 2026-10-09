"""Test script for bolder, bigger, recipe-aware color-coded recipe pin headers."""

from __future__ import annotations

import re
import sys
from pathlib import Path
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from rankstein.remaster_variants import _cover, _font, PIN_WIDTH, PIN_HEIGHT

def get_recipe_theme_colors(text_to_match: str) -> dict:
    t = (text_to_match or "").lower()
    
    # 1. Arroces / Paellas / Azafrán / Guisos (Saffron Gold)
    if any(k in t for k in ("arroz", "paella", "risotto", "azafran", "azafrán", "curry", "tortilla", "patata", "guiso", "estofado", "garbanzo", "lenteja", "potaje")):
        return {
            "name": "saffron_gold",
            "header": (255, 196, 68),       # Glowing Saffron Amber Gold
            "accent": (255, 218, 128),      # Warm gold accent for bullets/numbers
            "label": "Azafrán & Arroces",
        }
    
    # 2. Ensaladas / Verduras / Vegano / Saludable / Gazpacho (Fresh Herb Lime)
    if any(k in t for k in ("ensalada", "verdura", "aguacate", "espinaca", "calabac", "pepino", "lechuga", "gazpacho", "salmorejo", "saludable", "verde", "vegano", "vegetal", "hierba", "albahaca", "smoothie", "detox")):
        return {
            "name": "fresh_green",
            "header": (154, 230, 110),      # Bright Herb Lime / Pistachio
            "accent": (195, 244, 168),
            "label": "Huerta & Ensaladas",
        }

    # 3. Fresas / Frutas / Frutos Rojos / Helados (Berry Coral Ruby)
    if any(k in t for k in ("fresa", "frambuesa", "arandano", "arándano", "cereza", "fruta", "helado", "sorbete", "mora", "sandia", "sandía", "limon", "limón", "citrico", "cítrico")):
        return {
            "name": "berry_coral",
            "header": (255, 126, 158),      # Electric Berry Coral
            "accent": (255, 185, 204),
            "label": "Frutos Rojos & Helados",
        }

    # 4. Postres / Chocolate / Tartas / Bakery (Warm Honey Caramel)
    if any(k in t for k in ("postre", "tarta", "pastel", "bizcocho", "galleta", "chocolate", "cacao", "trufa", "flan", "crema", "dulce", "brownie", "mousse", "caramelo", "vainilla", "cheesecake", "muffin", "pan", "hojaldre")):
        return {
            "name": "warm_caramel",
            "header": (255, 190, 118),      # Golden Honey Caramel
            "accent": (255, 222, 182),
            "label": "Repostería & Dulces",
        }

    # 5. Carnes / Asados / Barbacoa (Paprika Flame Ember)
    if any(k in t for k in ("carne", "pollo", "ternera", "cerdo", "solomillo", "costilla", "alitas", "hamburguesa", "asado", "bbq", "barbacoa", "jamon", "jamón", "lomo", "cordero", "albondiga", "chorizo")):
        return {
            "name": "paprika_ember",
            "header": (255, 134, 98),       # Paprika Fire Terracotta
            "accent": (255, 182, 158),
            "label": "Carnes & Asados",
        }

    # 6. Pescados / Mariscos / Del Mar (Mediterranean Sea Aqua)
    if any(k in t for k in ("pescado", "marisco", "gamba", "salmon", "salmón", "atun", "atún", "merluza", "bacalao", "calamar", "pulpo", "mejillon", "mejillón", "almeja", "langostino")):
        return {
            "name": "sea_aqua",
            "header": (100, 226, 245),      # Coastal Aqua Turquoise
            "accent": (175, 244, 253),
            "label": "Pescados & Mariscos",
        }

    # 7. Pastas / Pizzas / Tomate / Italiano (Pomodoro Sunset)
    if any(k in t for k in ("pasta", "pizza", "espagueti", "macarron", "lasana", "lasaña", "tomate", "pomodoro", "bolognesa", "carbonara", "ravioli")):
        return {
            "name": "pomodoro_sunset",
            "header": (255, 140, 95),       # Pomodoro Warm Coral
            "accent": (255, 188, 160),
            "label": "Pastas & Pomodoro",
        }

    # Fallback Gourmet Champagne Gold
    return {
        "name": "champagne_gold",
        "header": (252, 224, 130),          # Gourmet Champagne Gold
        "accent": (255, 238, 180),
        "label": "Cocina Gourmet",
    }


def render_test_pin(
    *,
    source_path: str,
    title: str,
    subtitle: str,
    ingredients: list[str],
    steps: list[str],
    font_choice: str,  # "georgia_bold" or "montserrat_bold"
    header_size: int,   # 42 or 44
    output_path: Path,
) -> None:
    source = Path(source_path)
    with Image.open(source) as raw:
        photo = _cover(raw, PIN_WIDTH, PIN_HEIGHT, focus_y=0.38)
    photo = ImageEnhance.Contrast(photo).enhance(1.05)
    photo = ImageEnhance.Color(photo).enhance(1.06).convert("RGBA")

    # 1. Dark bottom vignette
    overlay = Image.new("RGBA", (PIN_WIDTH, PIN_HEIGHT), (0, 0, 0, 0))
    overlay_draw = ImageDraw.Draw(overlay)
    vignette_start = 840
    vignette_height = PIN_HEIGHT - vignette_start
    for y in range(vignette_start, PIN_HEIGHT):
        progress = (y - vignette_start) / vignette_height
        alpha = int(245 * (progress ** 1.15))
        overlay_draw.line((0, y, PIN_WIDTH, y), fill=(12, 9, 7, alpha))
    canvas = Image.alpha_composite(photo, overlay)

    # 2. Floating Ivory Header Card
    card_x1, card_x2 = 110, 890
    card_w = card_x2 - card_x1
    card_y1 = 36
    card_radius = 28
    draw = ImageDraw.Draw(canvas, "RGBA")

    title_clean = re.sub(r"\s+", " ", title.strip())
    title_font = _font(48, bold=True, serif=True)
    title_lines = [title_clean]
    if draw.textbbox((0, 0), title_clean, font=title_font)[2] > (card_w - 70):
        # wrap to 2 lines
        words = title_clean.split()
        mid = len(words) // 2
        title_lines = [" ".join(words[:mid]), " ".join(words[mid:])]

    sub_font = _font(24, sans=True)
    sub_lines = [subtitle]
    title_sample = draw.textbbox((0, 0), "Ágj", font=title_font)
    title_line_h = (title_sample[3] - title_sample[1]) + 8
    title_block_h = len(title_lines) * title_line_h
    sub_sample = draw.textbbox((0, 0), "Ágj", font=sub_font)
    sub_line_h = (sub_sample[3] - sub_sample[1]) + 6
    sub_block_h = len(sub_lines) * sub_line_h
    card_h = 24 + title_block_h + 12 + sub_block_h + 22
    card_y2 = card_y1 + card_h

    # Card shadow
    shadow_img = Image.new("RGBA", (card_w + 50, card_h + 50), (0, 0, 0, 0))
    s_draw = ImageDraw.Draw(shadow_img)
    s_draw.rounded_rectangle((25, 25, 25 + card_w, 25 + card_h), radius=card_radius, fill=(10, 8, 6, 90))
    shadow_img = shadow_img.filter(ImageFilter.GaussianBlur(12))
    canvas.paste(shadow_img, (card_x1 - 25, card_y1 - 25 + 8), shadow_img)

    draw = ImageDraw.Draw(canvas, "RGBA")
    draw.rounded_rectangle(
        (card_x1, card_y1, card_x2, card_y2),
        radius=card_radius,
        fill=(248, 242, 233, 250),
        outline=(226, 216, 202, 190),
        width=1,
    )

    cur_y = card_y1 + 24
    for line in title_lines:
        tb = draw.textbbox((0, 0), line, font=title_font)
        tx = (PIN_WIDTH - (tb[2] - tb[0])) // 2
        draw.text((tx, cur_y), line, font=title_font, fill=(24, 20, 18))
        cur_y += title_line_h

    cur_y += 6
    for line in sub_lines:
        sb = draw.textbbox((0, 0), line, font=sub_font)
        sx = (PIN_WIDTH - (sb[2] - sb[0])) // 2
        draw.text((sx, cur_y), line, font=sub_font, fill=(70, 65, 60))
        cur_y += sub_line_h

    # 3. Two-Column Recipe Section
    col_y_start = 945
    col_left_x1, col_left_w = 55, 415
    col_left_x2 = col_left_x1 + col_left_w
    col_right_x1, col_right_w = 505, 435
    col_right_x2 = col_right_x1 + col_right_w

    # Tier 1 Feathered Backplate
    highlight_img = Image.new("RGBA", (PIN_WIDTH, PIN_HEIGHT), (0, 0, 0, 0))
    h_draw = ImageDraw.Draw(highlight_img)
    h_draw.rounded_rectangle((col_left_x1 - 15, col_y_start - 10, col_left_x2 + 15, 1435), radius=24, fill=(8, 6, 5, 145))
    h_draw.rounded_rectangle((col_right_x1 - 15, col_y_start - 10, col_right_x2 + 15, 1435), radius=24, fill=(8, 6, 5, 145))
    highlight_img = highlight_img.filter(ImageFilter.GaussianBlur(18))
    canvas = Image.alpha_composite(canvas, highlight_img)

    # Recipe-Aware Colors
    theme_colors = get_recipe_theme_colors(f"{title} {' '.join(ingredients)}")
    header_color = theme_colors["header"]
    accent_color = theme_colors["accent"]

    # Typography for headers
    if font_choice == "georgia_bold":
        header_font = _font(header_size, bold=True, serif=True)
    else:
        header_font = _font(header_size, bold=True, sans=True)

    # Tier 2 Glyph Glow
    glow_layer = Image.new("RGBA", (PIN_WIDTH, PIN_HEIGHT), (0, 0, 0, 0))
    glow_draw = ImageDraw.Draw(glow_layer)

    # Header glow
    for dx, dy in ((-2, 0), (2, 0), (0, -2), (0, 2), (-1, -1), (1, 1), (0, 0)):
        glow_draw.text((col_left_x1 + dx, col_y_start + dy), "Ingredientes:", font=header_font, fill=(0, 0, 0, 255))
        glow_draw.text((col_right_x1 + dx, col_y_start + dy), "Preparación:", font=header_font, fill=(0, 0, 0, 255))

    ing_font = _font(21, bold=True, sans=True)
    bullet_font = _font(22, bold=True, sans=True)
    header_box = draw.textbbox((0, 0), "Ingredientes:", font=header_font)
    header_h = header_box[3] - header_box[1]
    ing_y = col_y_start + header_h + 16
    ing_line_h = 29

    ing_rendered_items = []
    for item in ingredients[:8]:
        words = item.strip().split()
        item_lines = []
        cur_line = ""
        for w in words:
            cand = f"{cur_line} {w}".strip()
            if cur_line and draw.textbbox((0, 0), cand, font=ing_font)[2] > (col_left_w - 30):
                item_lines.append(cur_line)
                cur_line = w
            else:
                cur_line = cand
        if cur_line:
            item_lines.append(cur_line)
        ing_rendered_items.append((col_left_x1, ing_y, item_lines))

        for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 2), (0, 0)):
            glow_draw.text((col_left_x1 + dx, ing_y + dy + 1), "•", font=bullet_font, fill=(0, 0, 0, 255))
            cur_line_y = ing_y
            for line in item_lines:
                glow_draw.text((col_left_x1 + 22 + dx, cur_line_y + dy + 1), line, font=ing_font, fill=(0, 0, 0, 255))
                cur_line_y += ing_line_h
        ing_y += len(item_lines) * ing_line_h + 3

    step_font = _font(20, bold=False, sans=True)
    step_num_font = _font(20, bold=True, sans=True)
    step_y = col_y_start + header_h + 16
    step_line_h = 28

    step_rendered_items = []
    for idx, step in enumerate(steps[:5], 1):
        prefix = f"{idx}. "
        p_box = draw.textbbox((0, 0), prefix, font=step_num_font)
        p_w = p_box[2] - p_box[0]
        words = step.strip().split()
        step_lines = []
        cur_line = ""
        indent_w = col_right_w - p_w - 8
        for w in words:
            cand = f"{cur_line} {w}".strip()
            if cur_line and draw.textbbox((0, 0), cand, font=step_font)[2] > indent_w:
                step_lines.append(cur_line)
                cur_line = w
            else:
                cur_line = cand
        if cur_line:
            step_lines.append(cur_line)
        step_rendered_items.append((col_right_x1, step_y, prefix, p_w, step_lines))

        for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 2), (0, 0)):
            glow_draw.text((col_right_x1 + dx, step_y + dy + 1), prefix, font=step_num_font, fill=(0, 0, 0, 255))
            cur_s_y = step_y
            for s_line in step_lines:
                glow_draw.text((col_right_x1 + p_w + 4 + dx, cur_s_y + dy + 1), s_line, font=step_font, fill=(0, 0, 0, 255))
                cur_s_y += step_line_h
        step_y += len(step_lines) * step_line_h + 8

    glow_blurred = glow_layer.filter(ImageFilter.GaussianBlur(4))
    canvas = Image.alpha_composite(canvas, glow_blurred)

    # Crisp top rendering
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

    # Footer
    footer_font = _font(19, sans=True)
    footer_text = "recetagenial.com"
    fb = draw.textbbox((0, 0), footer_text, font=footer_font)
    fw = fb[2] - fb[0]
    draw.text(((PIN_WIDTH - fw) // 2 + 1, 1461), footer_text, font=footer_font, fill=(0, 0, 0, 180))
    draw.text(((PIN_WIDTH - fw) // 2, 1460), footer_text, font=footer_font, fill=(230, 225, 215, 190))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.convert("RGB").save(str(output_path), "JPEG", quality=95)
    print(f"Generated: {output_path} (font={font_choice}, size={header_size}, theme={theme_colors['name']})")

if __name__ == "__main__":
    raw = "data/media/remaster_raw/1003950941947830943.jpg"
    base_out = Path("C:/Users/REDX420/.gemini/antigravity/brain/4def31ef-1cbb-4e58-b00a-3c4bea3fd439")
    
    # 1. Georgia Bold 44px
    render_test_pin(
        source_path=raw,
        title="Paella Valenciana Tradicional",
        subtitle="El auténtico arroz mediterráneo a la leña",
        ingredients=[
            "400 g de arroz bomba",
            "500 g de pollo y conejo troceado",
            "200 g de judías verdes (bajoqueta)",
            "100 g de garrofó valenciano",
            "1 tomate maduro rallado",
            "Unas hebras de azafrán de hebra",
            "Aceite de oliva virgen extra y sal",
        ],
        steps=[
            "Dora bien la carne con aceite de oliva hasta que tome buen color dorado.",
            "Añade la verdura y sofríe junto con el tomate rallado.",
            "Vierte el agua y deja hervir a fuego vivo para infusionar el caldo.",
            "Añade el azafrán y el arroz bomba, cocinando 18-20 min hasta el socarrat.",
        ],
        font_choice="georgia_bold",
        header_size=44,
        output_path=base_out / "paella_header_georgia_bold_44.jpg",
    )

    # 2. Montserrat Bold 44px
    render_test_pin(
        source_path=raw,
        title="Paella Valenciana Tradicional",
        subtitle="El auténtico arroz mediterráneo a la leña",
        ingredients=[
            "400 g de arroz bomba",
            "500 g de pollo y conejo troceado",
            "200 g de judías verdes (bajoqueta)",
            "100 g de garrofó valenciano",
            "1 tomate maduro rallado",
            "Unas hebras de azafrán de hebra",
            "Aceite de oliva virgen extra y sal",
        ],
        steps=[
            "Dora bien la carne con aceite de oliva hasta que tome buen color dorado.",
            "Añade la verdura y sofríe junto con el tomate rallado.",
            "Vierte el agua y deja hervir a fuego vivo para infusionar el caldo.",
            "Añade el azafrán y el arroz bomba, cocinando 18-20 min hasta el socarrat.",
        ],
        font_choice="montserrat_bold",
        header_size=44,
        output_path=base_out / "paella_header_montserrat_bold_44.jpg",
    )
