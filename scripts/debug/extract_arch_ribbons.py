from pathlib import Path
from PIL import Image
import numpy as np

BRAIN_DIR = Path(r"C:\Users\REDX420\.gemini\antigravity\brain\4def31ef-1cbb-4e58-b00a-3c4bea3fd439")
ASSETS_DIR = Path(__file__).resolve().parents[2] / "rankstein" / "assets"
RIBBONS_DIR = ASSETS_DIR / "ribbons"
RIBBONS_DIR.mkdir(parents=True, exist_ok=True)

def make_transparent_white_bg(img: Image.Image, threshold: int = 248, feather: int = 16) -> Image.Image:
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

def clean_extract_arch_ribbons():
    src_p = BRAIN_DIR / "culinary_arch_ribbons_1791506993929.jpg"
    assert src_p.exists()
    img = Image.open(src_p)
    w, h = img.size
    
    # Non-overlapping y-boundaries for 1024x1024 image
    stripes = [
        ("arch_ribbon_green", (int(w * 0.02), 20, int(w * 0.98), 255)),
        ("arch_ribbon_terracotta", (int(w * 0.02), 265, int(w * 0.98), 500)),
        ("arch_ribbon_burgundy", (int(w * 0.02), 510, int(w * 0.98), 745)),
        ("arch_ribbon_gold", (int(w * 0.02), 755, int(w * 0.98), 990)),
    ]
    
    for name, box in stripes:
        crop = img.crop(box)
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
        print(f"Cleanly extracted {name}.png ({rgba.size})")

if __name__ == "__main__":
    clean_extract_arch_ribbons()
