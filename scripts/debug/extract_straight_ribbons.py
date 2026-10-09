from pathlib import Path
from PIL import Image, ImageDraw
import numpy as np

BRAIN_DIR = Path(r"C:\Users\REDX420\.gemini\antigravity\brain\4def31ef-1cbb-4e58-b00a-3c4bea3fd439")
ASSETS_DIR = Path(__file__).resolve().parents[2] / "rankstein" / "assets"
RIBBONS_DIR = ASSETS_DIR / "ribbons"
RIBBONS_DIR.mkdir(parents=True, exist_ok=True)

def make_transparent_white_bg(img: Image.Image, threshold: int = 245, feather: int = 20) -> Image.Image:
    rgba = img.convert("RGBA")
    arr = np.array(rgba, dtype=np.float32)
    r, g, b = arr[:, :, 0], arr[:, :, 1], arr[:, :, 2]
    min_rgb = np.minimum(np.minimum(r, g), b)
    alpha = np.ones_like(min_rgb) * 255.0
    fade_start = threshold - feather
    alpha[min_rgb >= threshold] = 0.0
    transition_mask = (min_rgb >= fade_start) & (min_rgb < threshold)
    alpha[transition_mask] = 255.0 * (threshold - min_rgb[transition_mask]) / feather
    arr[:, :, 3] = np.clip(alpha, 0, 255)
    return Image.fromarray(arr.astype(np.uint8), mode="RGBA")

def clean_extract_straight_ribbons():
    src_p = BRAIN_DIR / "straight_ribbon_banners_1791506616243.jpg"
    assert src_p.exists()
    img = Image.open(src_p)
    w, h = img.size
    
    stripes = [
        ("ribbon_straight_green", (int(w * 0.04), int(h * 0.06), int(w * 0.96), int(h * 0.25)), (106, 129, 47)),
        ("ribbon_straight_berry", (int(w * 0.04), int(h * 0.29), int(w * 0.96), int(h * 0.48)), (156, 38, 63)),
        ("ribbon_straight_gold", (int(w * 0.04), int(h * 0.51), int(w * 0.96), int(h * 0.71)), (204, 150, 48)),
        ("ribbon_straight_terracotta", (int(w * 0.04), int(h * 0.74), int(w * 0.96), int(h * 0.94)), (205, 87, 42)),
    ]
    
    for name, box, solid_color in stripes:
        crop = img.crop(box)
        c_draw = ImageDraw.Draw(crop)
        cw, ch = crop.size
        
        # Center bar is from ~16% to ~84% width, and ~12% to ~88% height
        x_start = int(cw * 0.165)
        x_end = int(cw * 0.835)
        y_start = int(ch * 0.12)
        y_end = int(ch * 0.88)
        c_draw.rectangle((x_start, y_start, x_end, y_end), fill=solid_color)
        
        rgba = make_transparent_white_bg(crop)
        bbox = rgba.getbbox()
        if bbox:
            bx1 = max(0, bbox[0] - 4)
            by1 = max(0, bbox[1] - 4)
            bx2 = min(rgba.width, bbox[2] + 4)
            by2 = min(rgba.height, bbox[3] + 4)
            rgba = rgba.crop((bx1, by1, bx2, by2))
        
        out_p = RIBBONS_DIR / f"{name}.png"
        rgba.save(out_p, "PNG")
        print(f"Cleaned and saved {name}.png ({rgba.size})")

if __name__ == "__main__":
    clean_extract_straight_ribbons()
