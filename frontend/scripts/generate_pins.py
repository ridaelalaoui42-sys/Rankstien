"""
Pinterest Pin Generator — RecetaDolce
Generates vertical 1000x1500 split-screen Pinterest pins using Pillow.
Uses locally generated/saved fresas images.

Usage: python scripts/generate_pins.py
Output: scripts/pins/output/pin_<slug>.png
"""
from PIL import Image, ImageDraw, ImageFont, ImageEnhance
from pathlib import Path
import textwrap
import sys

# ─── Config ───────────────────────────────────────────────────────────────────
PIN_W, PIN_H         = 1000, 1500
BANNER_H             = 220           # center banner height
BANNER_COLOR         = (90, 20, 35)  # deep burgundy / maroon
TEXT_WHITE           = (255, 255, 255)
TEXT_LIGHT           = (255, 220, 210)
ACCENT_COLOR         = (200, 80, 80) # rose accent

SCRIPTS_DIR = Path(__file__).parent
PROJECT_DIR = SCRIPTS_DIR.parent
IMAGES_DIR  = PROJECT_DIR / "public" / "images" / "fresas"
OUT_DIR     = SCRIPTS_DIR / "pins" / "output"
OUT_DIR.mkdir(parents=True, exist_ok=True)

SITE_URL = "www.RecetaDolce.com"

# ─── Font loader (falls back to default if not found) ─────────────────────────
def load_font(size, bold=False):
    candidates_bold   = ["arialbd.ttf","Arial Bold.ttf","DejaVuSans-Bold.ttf","Helvetica-Bold.ttf"]
    candidates_normal = ["arial.ttf","Arial.ttf","DejaVuSans.ttf","Helvetica.ttf"]
    search = candidates_bold if bold else candidates_normal
    dirs = [
        "C:/Windows/Fonts/",
        "/usr/share/fonts/truetype/",
        "/usr/share/fonts/",
        str(Path.home() / "Library/Fonts/"),
    ]
    for d in dirs:
        for f in search:
            p = Path(d) / f
            if p.exists():
                try: return ImageFont.truetype(str(p), size)
                except: pass
    return ImageFont.load_default()

# ─── Core pin generator ────────────────────────────────────────────────────────
def make_pin(image_path: Path, title_es: str, slug: str) -> Path:
    HALF_H = (PIN_H - BANNER_H) // 2

    # Load source image
    src = Image.open(image_path).convert("RGB")
    src_w, src_h = src.size

    # ── TOP PHOTO (finished dish) — upper-center crop ──────────────────────────
    top_src = src.copy()
    # Resize to fill PIN_W keeping aspect
    scale = max(PIN_W / src_w, HALF_H / src_h)
    tw = int(src_w * scale)
    th = int(src_h * scale)
    top_src = top_src.resize((tw, th), Image.LANCZOS)
    # Crop top-center
    left = (tw - PIN_W) // 2
    top_src = top_src.crop((left, 0, left + PIN_W, HALF_H))
    # Slight brightness boost
    top_src = ImageEnhance.Brightness(top_src).enhance(1.05)

    # ── BOTTOM PHOTO (detail/closeup) — lower-center crop + slight zoom ────────
    bot_src = src.copy()
    # Zoom in 30% for closeup feel
    zoom_w = int(src_w * 0.65)
    zoom_h = int(src_h * 0.65)
    cx, cy = src_w // 2, int(src_h * 0.65)  # focus lower center
    box = (max(0, cx - zoom_w//2), max(0, cy - zoom_h//2),
           min(src_w, cx + zoom_w//2), min(src_h, cy + zoom_h//2))
    bot_src = bot_src.crop(box)
    scale2 = max(PIN_W / bot_src.width, HALF_H / bot_src.height)
    bot_src = bot_src.resize((int(bot_src.width*scale2), int(bot_src.height*scale2)), Image.LANCZOS)
    left2 = (bot_src.width - PIN_W) // 2
    bot_src = bot_src.crop((left2, 0, left2 + PIN_W, HALF_H))
    # Slight contrast boost for the closeup
    bot_src = ImageEnhance.Contrast(bot_src).enhance(1.15)
    bot_src = ImageEnhance.Sharpness(bot_src).enhance(1.3)

    # ── COMPOSE CANVAS ─────────────────────────────────────────────────────────
    canvas = Image.new("RGB", (PIN_W, PIN_H), (20, 10, 10))
    canvas.paste(top_src, (0, 0))
    canvas.paste(bot_src, (0, HALF_H + BANNER_H))

    # ── GRADIENT OVERLAYS (top & bottom fade to black near banner) ─────────────
    def add_gradient(canvas, y_start, y_end, from_alpha, to_alpha):
        grad = Image.new("RGBA", (PIN_W, abs(y_end - y_start)), (0, 0, 0, 0))
        draw = ImageDraw.Draw(grad)
        steps = abs(y_end - y_start)
        for i in range(steps):
            t = i / steps
            a = int(from_alpha + (to_alpha - from_alpha) * t)
            draw.line([(0, i), (PIN_W, i)], fill=(0, 0, 0, a))
        canvas_rgba = canvas.convert("RGBA")
        canvas_rgba.paste(grad, (0, min(y_start, y_end)), grad)
        return canvas_rgba.convert("RGB")

    # Bottom of top photo fades darker → banner
    canvas = add_gradient(canvas, HALF_H - 80, HALF_H, 0, 180)
    # Top of bottom photo fades from banner
    canvas = add_gradient(canvas, HALF_H + BANNER_H, HALF_H + BANNER_H + 80, 180, 0)

    # ── BANNER ─────────────────────────────────────────────────────────────────
    draw = ImageDraw.Draw(canvas)
    banner_y = HALF_H
    # Main banner rect
    draw.rectangle([(0, banner_y), (PIN_W, banner_y + BANNER_H)], fill=BANNER_COLOR)
    # Top & bottom thin accent lines
    draw.rectangle([(0, banner_y), (PIN_W, banner_y + 3)], fill=ACCENT_COLOR)
    draw.rectangle([(0, banner_y + BANNER_H - 3), (PIN_W, banner_y + BANNER_H)], fill=ACCENT_COLOR)

    # ── BANNER TEXT ─────────────────────────────────────────────────────────────
    # 1. RECIPE TITLE (big, bold serif)
    title_upper = title_es.upper()
    font_title  = load_font(52, bold=True)
    font_sub    = load_font(26, bold=False)
    font_url    = load_font(22, bold=False)
    font_logo   = load_font(30, bold=True)

    # Wrap title if long
    chars_per_line = 18
    lines = textwrap.wrap(title_upper, width=chars_per_line)
    if len(lines) > 3:
        lines = lines[:3]
        lines[-1] += "…"

    # Calculate vertical layout inside banner
    line_h = 58
    total_text_h = len(lines) * line_h + 35 + 30  # lines + "Receta Completa" + URL
    text_y = banner_y + (BANNER_H - total_text_h) // 2

    for line in lines:
        bbox = draw.textbbox((0, 0), line, font=font_title)
        lw = bbox[2] - bbox[0]
        x = (PIN_W - lw) // 2
        # subtle shadow
        draw.text((x + 2, text_y + 2), line, font=font_title, fill=(0, 0, 0, 120))
        draw.text((x, text_y), line, font=font_title, fill=TEXT_WHITE)
        text_y += line_h

    text_y += 8

    # 2. "Receta Completa" subtitle
    sub_text = "Receta Completa"
    bbox = draw.textbbox((0, 0), sub_text, font=font_sub)
    sw = bbox[2] - bbox[0]
    draw.text(((PIN_W - sw) // 2, text_y), sub_text, font=font_sub, fill=TEXT_LIGHT)
    text_y += 35

    # 3. URL
    bbox = draw.textbbox((0, 0), SITE_URL, font=font_url)
    uw = bbox[2] - bbox[0]
    draw.text(((PIN_W - uw) // 2, text_y), SITE_URL, font=font_url, fill=(255, 180, 160))

    # ── RG LOGO (right side of banner) ─────────────────────────────────────────
    logo_x = PIN_W - 90
    logo_y = banner_y + BANNER_H // 2 - 30
    # Circle background
    draw.ellipse([(logo_x - 28, logo_y - 28), (logo_x + 28, logo_y + 28)], fill=ACCENT_COLOR)
    # "RG" text
    bbox = draw.textbbox((0, 0), "RG", font=font_logo)
    lw = bbox[2] - bbox[0]
    draw.text((logo_x - lw // 2, logo_y - 18), "RG", font=font_logo, fill=TEXT_WHITE)

    # ── WATERMARK (bottom-left) ─────────────────────────────────────────────────
    font_wm = load_font(18)
    draw.text((20, PIN_H - 30), f"© RecetaDolce | {SITE_URL}", font=font_wm, fill=(255, 255, 255, 140))

    # ── SAVE ───────────────────────────────────────────────────────────────────
    out_path = OUT_DIR / f"pin_{slug}.png"
    canvas.save(out_path, "PNG", quality=95)
    print(f"  Saved: {out_path.name}")
    return out_path

# ─── Articles ─────────────────────────────────────────────────────────────────
PINS = [
    ("tarta-de-fresas-con-nata",  "fresas-tarta-nata.jpg",       "Tarta de Fresas con Nata"),
    ("mermelada-de-fresas-casera","fresas-mermelada-casera.jpg",  "Mermelada de Fresas Casera"),
    ("fresas-con-nata-perfectas", "fresas-con-nata.jpg",          "Fresas con Nata Perfectas"),
    ("mousse-de-fresa-mascarpone","fresas-mousse-mascarpone.jpg", "Mousse de Fresa con Mascarpone"),
    ("batido-cremoso-de-fresas",  "fresas-batido-cremoso.jpg",    "Batido Cremoso de Fresas"),
]

def main():
    print("RecetaDolce — Pinterest Pin Generator")
    print("=" * 40)
    try:
        from PIL import Image
    except ImportError:
        print("Run: pip install Pillow")
        sys.exit(1)

    for slug, img_file, title_es in PINS:
        img_path = IMAGES_DIR / img_file
        if not img_path.exists():
            print(f"  MISSING image: {img_file}")
            continue
        print(f"\nGenerating pin: {title_es}")
        make_pin(img_path, title_es, slug)

    print(f"\nDone! Pins saved in: {OUT_DIR}")

if __name__ == "__main__":
    main()
