from __future__ import annotations

import re
import sys
from pathlib import Path
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from rankstein.remaster_variants import _cover, _font, _theme_for_domain, PIN_WIDTH, PIN_HEIGHT

def generate_visual_recipe_card(
    *,
    source_path: str,
    title: str,
    subtitle: str,
    ingredients: list[str],
    steps: list[str],
    domain_handle: str,
    output_path: Path,
) -> dict:
    source = Path(source_path)
    if not source.is_file():
        return {"success": False, "error": f"Source image not found: {source_path}"}

    theme = _theme_for_domain(domain_handle)
    
    with Image.open(source) as raw:
        photo = _cover(raw, PIN_WIDTH, PIN_HEIGHT, focus_y=0.38)
    photo = ImageEnhance.Contrast(photo).enhance(1.05)
    photo = ImageEnhance.Color(photo).enhance(1.06).convert("RGBA")

    # ── 1. CINEMATIC DARK BOTTOM VIGNETTE ─────────────────────────────────────
    overlay = Image.new("RGBA", (PIN_WIDTH, PIN_HEIGHT), (0, 0, 0, 0))
    overlay_draw = ImageDraw.Draw(overlay)
    vignette_start = 840
    vignette_height = PIN_HEIGHT - vignette_start
    for y in range(vignette_start, PIN_HEIGHT):
        progress = (y - vignette_start) / vignette_height
        alpha = int(245 * (progress ** 1.15))
        overlay_draw.line((0, y, PIN_WIDTH, y), fill=(12, 9, 7, alpha))
    
    canvas = Image.alpha_composite(photo, overlay)

    # ── 2. TOP FLOATING HEADER CARD ───────────────────────────────────────────
    card_x1 = 110
    card_x2 = 890
    card_w = card_x2 - card_x1
    card_y1 = 36
    card_radius = 28

    draw = ImageDraw.Draw(canvas, "RGBA")

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
    sub_clean = subtitle.strip() or "Receta casera tradicional • Deliciosa y lista en minutos"
    sub_lines = []
    sub_words = sub_clean.split()
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

    # Soft drop shadow behind header card
    shadow_img = Image.new("RGBA", (card_w + 50, card_h + 50), (0, 0, 0, 0))
    s_draw = ImageDraw.Draw(shadow_img)
    s_draw.rounded_rectangle((25, 25, 25 + card_w, 25 + card_h), radius=card_radius, fill=(10, 8, 6, 90))
    shadow_img = shadow_img.filter(ImageFilter.GaussianBlur(12))
    canvas.paste(shadow_img, (card_x1 - 25, card_y1 - 25 + 8), shadow_img)

    draw = ImageDraw.Draw(canvas, "RGBA")

    # Header Card Fill
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

    # ── 3. BOTTOM TWO-COLUMN RECIPE SECTION ───────────────────────────────────
    col_y_start = 950
    col_left_x1 = 55
    col_left_w = 415
    col_left_x2 = col_left_x1 + col_left_w

    col_right_x1 = 505
    col_right_w = 435
    col_right_x2 = col_right_x1 + col_right_w

    # ── A. SOFT BLURRED HIGHLIGHT BACKPLATE UNDER COLUMNS ────────────────────
    # Creates an ultra-soft feathered translucent dark backing directly under the text columns
    highlight_img = Image.new("RGBA", (PIN_WIDTH, PIN_HEIGHT), (0, 0, 0, 0))
    h_draw = ImageDraw.Draw(highlight_img)

    # Left column soft backing plate
    h_draw.rounded_rectangle(
        (col_left_x1 - 15, col_y_start - 10, col_left_x2 + 15, 1435),
        radius=24,
        fill=(8, 6, 5, 140),
    )
    # Right column soft backing plate
    h_draw.rounded_rectangle(
        (col_right_x1 - 15, col_y_start - 10, col_right_x2 + 15, 1435),
        radius=24,
        fill=(8, 6, 5, 140),
    )
    # 18px Gaussian blur makes edges dissolve naturally into the background
    highlight_img = highlight_img.filter(ImageFilter.GaussianBlur(18))
    canvas = Image.alpha_composite(canvas, highlight_img)

    # ── B. TEXT GLOW / BLURRED HIGHLIGHT LAYER DIRECTLY UNDER TEXT ───────────
    # Renders a tight Gaussian-blurred dark halo hugging every letter
    glow_layer = Image.new("RGBA", (PIN_WIDTH, PIN_HEIGHT), (0, 0, 0, 0))
    glow_draw = ImageDraw.Draw(glow_layer)

    header_font = _font(35, serif=True)
    header_color = (252, 244, 230)

    # Queue header glow
    for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 2), (0, 0)):
        glow_draw.text((col_left_x1 + dx, col_y_start + dy + 1), "Ingredientes:", font=header_font, fill=(0, 0, 0, 255))
        glow_draw.text((col_right_x1 + dx, col_y_start + dy + 1), "Preparación:", font=header_font, fill=(0, 0, 0, 255))

    # Calculate item layouts & queue text glow
    ing_font = _font(21, bold=True, sans=True)
    bullet_font = _font(21, bold=True, sans=True)
    ing_y = col_y_start + 50
    ing_line_h = 29

    ing_rendered_items = []
    for item in ingredients[:8]:
        clean_item = item.strip()
        words = clean_item.split()
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
        
        # Add to rendered list for final crisp pass
        ing_rendered_items.append((col_left_x1, ing_y, item_lines))

        # Add to glow layer (multi-offset footprint)
        for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 2), (0, 0)):
            glow_draw.text((col_left_x1 + dx, ing_y + dy + 1), "•", font=bullet_font, fill=(0, 0, 0, 255))
            cur_line_y = ing_y
            for line in item_lines:
                glow_draw.text((col_left_x1 + 20 + dx, cur_line_y + dy + 1), line, font=ing_font, fill=(0, 0, 0, 255))
                cur_line_y += ing_line_h

        ing_y += len(item_lines) * ing_line_h + 3

    # Steps layout & queue text glow
    step_font = _font(20, bold=False, sans=True)
    step_num_font = _font(20, bold=True, sans=True)
    step_y = col_y_start + 50
    step_line_h = 28

    step_rendered_items = []
    for idx, step in enumerate(steps[:4], 1):
        clean_step = step.strip()
        prefix = f"{idx}. "
        p_box = draw.textbbox((0, 0), prefix, font=step_num_font)
        p_w = p_box[2] - p_box[0]

        words = clean_step.split()
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

    # Blur the text glow layer with 4px Gaussian blur
    glow_blurred = glow_layer.filter(ImageFilter.GaussianBlur(4))
    canvas = Image.alpha_composite(canvas, glow_blurred)

    # ── C. RENDER CRISP TOP TEXT OVER BLURRED HIGHLIGHT ──────────────────────
    draw = ImageDraw.Draw(canvas, "RGBA")

    # Headers
    draw.text((col_left_x1, col_y_start), "Ingredientes:", font=header_font, fill=header_color)
    draw.text((col_right_x1, col_y_start), "Preparación:", font=header_font, fill=header_color)

    # Ingredients
    for x_pos, y_pos, lines in ing_rendered_items:
        draw.text((x_pos, y_pos), "•", font=bullet_font, fill=(255, 255, 255))
        c_y = y_pos
        for line in lines:
            draw.text((x_pos + 20, c_y), line, font=ing_font, fill=(255, 255, 255))
            c_y += ing_line_h

    # Steps
    for x_pos, y_pos, prefix, p_w, lines in step_rendered_items:
        draw.text((x_pos, y_pos), prefix, font=step_num_font, fill=(255, 255, 255))
        c_y = y_pos
        for line in lines:
            draw.text((x_pos + p_w + 4, c_y), line, font=step_font, fill=(255, 255, 255))
            c_y += step_line_h

    # ── 4. SUBTLE FOOTER BRANDING ─────────────────────────────────────────────
    footer_font = _font(19, sans=True)
    footer_text = f"{theme.public_domain}"
    fb = draw.textbbox((0, 0), footer_text, font=footer_font)
    fw = fb[2] - fb[0]
    draw.text(((PIN_WIDTH - fw) // 2 + 1, 1461), footer_text, font=footer_font, fill=(0, 0, 0, 180))
    draw.text(((PIN_WIDTH - fw) // 2, 1460), footer_text, font=footer_font, fill=(230, 225, 215, 190))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.convert("RGB").save(output_path, "JPEG", quality=94, optimize=True)
    return {
        "success": True,
        "output_path": str(output_path),
        "width": PIN_WIDTH,
        "height": PIN_HEIGHT,
    }

if __name__ == "__main__":
    raw = 'data/media/remaster_raw/1003950941947830943.jpg'
    out = Path('C:/Users/REDX420/.gemini/antigravity/brain/4def31ef-1cbb-4e58-b00a-3c4bea3fd439/paella_recipe_card_highlight_test.jpg')
    res = generate_visual_recipe_card(
        source_path=raw,
        title='Paella Valenciana Tradicional',
        subtitle='El auténtico sabor del arroz mediterráneo en tu mesa',
        ingredients=[
            '400 g de arroz bomba',
            '500 g de pollo y conejo troceado',
            '200 g de judías verdes (bajoqueta)',
            '100 g de garrofó valenciano',
            '1 tomate maduro rallado',
            'Unas hebras de azafrán',
            'Aceite de oliva virgen extra y sal',
        ],
        steps=[
            'Dora bien la carne con aceite de oliva hasta que tome buen color.',
            'Añade la verdura y sofríe junto con el tomate rallado.',
            'Vierte el agua y deja hervir para crear un caldo sabroso.',
            'Añade el azafrán y el arroz, cocinando 18-20 min hasta el socarrat.',
        ],
        domain_handle='recetagenial',
        output_path=out,
    )
    print(res)
