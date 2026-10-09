import sys
from pathlib import Path
from PIL import Image, ImageChops, ImageFilter, ImageOps
import numpy as np

BRAIN_DIR = Path(r"C:\Users\REDX420\.gemini\antigravity\brain\4def31ef-1cbb-4e58-b00a-3c4bea3fd439")
ASSETS_DIR = Path(__file__).resolve().parents[2] / "rankstein" / "assets"

def make_transparent_white_bg(img: Image.Image, threshold: int = 245, feather: int = 25) -> Image.Image:
    """Turn white/near-white background into smooth transparent alpha."""
    rgba = img.convert("RGBA")
    arr = np.array(rgba, dtype=np.float32)
    # Brightness / distance from white
    r, g, b = arr[:, :, 0], arr[:, :, 1], arr[:, :, 2]
    # In pure white, min(r, g, b) is 255
    min_rgb = np.minimum(np.minimum(r, g), b)
    
    # Alpha mask: 255 where dark, 0 where white
    # If min_rgb >= threshold, it starts fading to transparent
    alpha = np.ones_like(min_rgb) * 255.0
    fade_start = threshold - feather
    
    # Pixels purely white
    alpha[min_rgb >= threshold] = 0.0
    # Pixels in transition
    transition_mask = (min_rgb >= fade_start) & (min_rgb < threshold)
    alpha[transition_mask] = 255.0 * (threshold - min_rgb[transition_mask]) / feather
    
    # Clamp and assign
    arr[:, :, 3] = np.clip(alpha, 0, 255)
    
    # Also defringe slightly: push near-white edges slightly towards darker edge color
    res = Image.fromarray(arr.astype(np.uint8), mode="RGBA")
    return res

def process_assets():
    icons_dir = ASSETS_DIR / "icons"
    ribbons_dir = ASSETS_DIR / "ribbons"
    badges_dir = ASSETS_DIR / "badges"
    textures_dir = ASSETS_DIR / "textures"
    
    for d in (icons_dir, ribbons_dir, badges_dir, textures_dir):
        d.mkdir(parents=True, exist_ok=True)

    # 1. Texture
    tex_path = BRAIN_DIR / "paper_craft_texture_1791505970768.jpg"
    if tex_path.exists():
        tex = Image.open(tex_path).convert("RGB")
        tex.save(textures_dir / "paper_parchment.jpg", "JPEG", quality=95)
        print("Saved paper_parchment.jpg")

    # 2. Icons sheet: 1024x1024 (2 rows x 3 columns)
    icons_path = BRAIN_DIR / "culinary_icons_sheet_1791505884296.jpg"
    if icons_path.exists():
        img = Image.open(icons_path)
        w, h = img.size
        # 6 regions roughly:
        # col0: [0.05, 0.35], col1: [0.36, 0.64], col2: [0.65, 0.95]
        # row0: [0.08, 0.48], row1: [0.52, 0.92]
        regions = {
            "timer": (int(w * 0.04), int(h * 0.08), int(w * 0.35), int(h * 0.46)),
            "flame": (int(w * 0.36), int(h * 0.08), int(w * 0.64), int(h * 0.46)),
            "chef_hat": (int(w * 0.65), int(h * 0.08), int(w * 0.96), int(h * 0.46)),
            "bulb": (int(w * 0.04), int(h * 0.50), int(w * 0.35), int(h * 0.92)),
            "cutlery": (int(w * 0.36), int(h * 0.50), int(w * 0.64), int(h * 0.92)),
            "sprig": (int(w * 0.65), int(h * 0.50), int(w * 0.96), int(h * 0.92)),
        }
        for name, box in regions.items():
            crop = img.crop(box)
            # Tight bounding box by non-white
            crop_rgba = make_transparent_white_bg(crop)
            # Find bbox of non-zero alpha
            bbox = crop_rgba.getbbox()
            if bbox:
                # Add small 4px margin
                bx1 = max(0, bbox[0] - 6)
                by1 = max(0, bbox[1] - 6)
                bx2 = min(crop_rgba.width, bbox[2] + 6)
                by2 = min(crop_rgba.height, bbox[3] + 6)
                crop_rgba = crop_rgba.crop((bx1, by1, bx2, by2))
            crop_rgba.save(icons_dir / f"{name}.png", "PNG")
            print(f"Saved icon: {name}.png ({crop_rgba.size})")

    # 3. Ribbons sheet: 1024x1024 (4 horizontal banners)
    ribbons_path = BRAIN_DIR / "blank_ribbon_banners_1791505920098.jpg"
    if ribbons_path.exists():
        img = Image.open(ribbons_path)
        w, h = img.size
        r_boxes = {
            "ribbon_green_scroll": (int(w * 0.03), int(h * 0.02), int(w * 0.97), int(h * 0.26)),
            "ribbon_terracotta_arch": (int(w * 0.03), int(h * 0.26), int(w * 0.97), int(h * 0.50)),
            "ribbon_green_curled": (int(w * 0.03), int(h * 0.50), int(w * 0.97), int(h * 0.74)),
            "ribbon_terracotta_flourish": (int(w * 0.03), int(h * 0.74), int(w * 0.97), int(h * 0.98)),
        }
        for name, box in r_boxes.items():
            crop = img.crop(box)
            crop_rgba = make_transparent_white_bg(crop, threshold=248, feather=20)
            bbox = crop_rgba.getbbox()
            if bbox:
                bx1 = max(0, bbox[0] - 6)
                by1 = max(0, bbox[1] - 6)
                bx2 = min(crop_rgba.width, bbox[2] + 6)
                by2 = min(crop_rgba.height, bbox[3] + 6)
                crop_rgba = crop_rgba.crop((bx1, by1, bx2, by2))
            crop_rgba.save(ribbons_dir / f"{name}.png", "PNG")
            print(f"Saved ribbon: {name}.png ({crop_rgba.size})")

    # 4. Badges sheet: 1024x1024 (2x2 grid)
    badges_path = BRAIN_DIR / "culinary_badges_sheet_1791505950112.jpg"
    if badges_path.exists():
        img = Image.open(badges_path)
        w, h = img.size
        b_boxes = {
            "badge_stamp_star": (int(w * 0.03), int(h * 0.03), int(w * 0.48), int(h * 0.48)),
            "badge_laurel_gourmet": (int(w * 0.52), int(h * 0.03), int(w * 0.97), int(h * 0.48)),
            "badge_wax_seal": (int(w * 0.03), int(h * 0.51), int(w * 0.48), int(h * 0.97)),
            "badge_rosette_gold": (int(w * 0.52), int(h * 0.51), int(w * 0.97), int(h * 0.97)),
        }
        for name, box in b_boxes.items():
            crop = img.crop(box)
            crop_rgba = make_transparent_white_bg(crop, threshold=245, feather=25)
            bbox = crop_rgba.getbbox()
            if bbox:
                bx1 = max(0, bbox[0] - 6)
                by1 = max(0, bbox[1] - 6)
                bx2 = min(crop_rgba.width, bbox[2] + 6)
                by2 = min(crop_rgba.height, bbox[3] + 6)
                crop_rgba = crop_rgba.crop((bx1, by1, bx2, by2))
            crop_rgba.save(badges_dir / f"{name}.png", "PNG")
            print(f"Saved badge: {name}.png ({crop_rgba.size})")

if __name__ == "__main__":
    process_assets()
