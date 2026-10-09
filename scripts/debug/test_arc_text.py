import math
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

BRAIN_DIR = Path(r"C:\Users\REDX420\.gemini\antigravity\brain\4def31ef-1cbb-4e58-b00a-3c4bea3fd439")
ASSETS_DIR = Path(__file__).resolve().parents[2] / "rankstein" / "assets"
RIBBONS_DIR = ASSETS_DIR / "ribbons"
FONTS_DIR = ASSETS_DIR / "fonts"

def get_font(name: str, size: int) -> ImageFont.FreeTypeFont:
    p = FONTS_DIR / name
    if p.exists():
        return ImageFont.truetype(str(p), size)
    return ImageFont.load_default(size=size)

def render_arc_text_ribbon(
    ribbon_name: str,
    text: str,
    font_name: str = "Montserrat-Bold.ttf",
    font_size: int = 50,
    letter_spacing_px: float = 6.0,
    text_color: tuple = (255, 255, 255, 255),
    shadow_color: tuple = (10, 8, 6, 230),
    bold_stroke: int = 2,
    apex_y: float = 46.0,  # Higher up to be perfectly centered in the ribbon
) -> Image.Image:
    """Render perfectly arched, bold, centered text matching the luxury ribbon curvature."""
    p = RIBBONS_DIR / f"{ribbon_name}.png"
    im = Image.open(p).convert("RGBA")
    
    font = get_font(font_name, font_size)
    
    # Exact circle geometry for 940px wide ribbon:
    cx = im.width / 2.0  # 470
    R = 1040.0
    cy = apex_y + R  # Centers the text vertically inside the ribbon banner
    
    # Measure characters
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
        
        # Position on circle
        px = cx + R * math.cos(ch_angle)
        py = cy + R * math.sin(ch_angle)
        
        # Tangent rotation angle in degrees
        rot_deg = math.degrees(ch_angle + math.pi / 2.0)
        
        # Render glyph using anchor="mm" with extra stroke width for bold commanding weight
        char_box_size = int(font_size * 2.5)
        c_img = Image.new("RGBA", (char_box_size, char_box_size), (0, 0, 0, 0))
        c_draw = ImageDraw.Draw(c_img)
        
        center_box = char_box_size // 2
        # Rich 3D shadow with stroke
        c_draw.text(
            (center_box + 2, center_box + 3),
            ch,
            font=font,
            anchor="mm",
            fill=shadow_color,
            stroke_width=bold_stroke,
            stroke_fill=shadow_color,
        )
        # Bold, crisp white text
        c_draw.text(
            (center_box, center_box),
            ch,
            font=font,
            anchor="mm",
            fill=text_color,
            stroke_width=bold_stroke,
            stroke_fill=text_color,
        )
        
        # Rotate glyph
        c_rot = c_img.rotate(-rot_deg, resample=Image.Resampling.BICUBIC)
        
        # Paste centered at (px, py)
        im.paste(
            c_rot,
            (int(px - char_box_size / 2.0), int(py - char_box_size / 2.0)),
            c_rot,
        )
        
        cur_angle += (cw + letter_spacing_px) / R
        
    return im

def test_suite():
    tests = [
        ("arch_ribbon_green", "INGREDIENTES", "Montserrat-Bold.ttf", 50, "arc_bolder_01_green_montserrat.png"),
        ("arch_ribbon_green", "INGREDIENTES", "DMSerifDisplay-Regular.ttf", 52, "arc_bolder_02_green_dmserif.png"),
        ("arch_ribbon_terracotta", "PASO A PASO", "Montserrat-Bold.ttf", 50, "arc_bolder_03_terracotta_montserrat.png"),
        ("arch_ribbon_gold", "INGREDIENTES", "Montserrat-Bold.ttf", 50, "arc_bolder_04_gold_montserrat.png"),
        ("arch_ribbon_burgundy", "PASO A PASO", "AbrilFatface-Regular.ttf", 50, "arc_bolder_05_burgundy_abril.png"),
    ]
    for r_name, txt, f_name, f_size, out_file in tests:
        res = render_arc_text_ribbon(r_name, txt, font_name=f_name, font_size=f_size, letter_spacing_px=6.0, apex_y=46.0)
        out_p = BRAIN_DIR / out_file
        res.save(out_p)
        print(f"Generated: {out_p.name}")

if __name__ == "__main__":
    test_suite()
