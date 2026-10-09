import sys
from pathlib import Path
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont, ImageOps
import numpy as np

ASSETS_DIR = Path(r"c:\Users\REDX420\Desktop\Rankstein\rankstein\assets")
ICONS_DIR = ASSETS_DIR / "icons"
RIBBONS_DIR = ASSETS_DIR / "ribbons"
BADGES_DIR = ASSETS_DIR / "badges"
TEXTURES_DIR = ASSETS_DIR / "textures"
BRAIN_DIR = Path(r"C:\Users\REDX420\.gemini\antigravity\brain\4def31ef-1cbb-4e58-b00a-3c4bea3fd439")

def tint_image(img: Image.Image, color: tuple[int, int, int]) -> Image.Image:
    """Tint non-transparent dark pixels of an RGBA image to a target color."""
    rgba = img.convert("RGBA")
    r_target, g_target, b_target = color[:3]
    arr = np.array(rgba, dtype=np.float32)
    
    # Calculate luminance of RGB
    lum = 0.299 * arr[:, :, 0] + 0.587 * arr[:, :, 1] + 0.114 * arr[:, :, 2]
    # For dark linework on transparent bg:
    # where lum is dark (close to 0), blend towards color
    # where alpha is > 0, preserve alpha
    alpha = arr[:, :, 3]
    
    # Interpolate: if original linework is dark, replace RGB with target color * (1 - lum/255)
    # Or simple tint: target color modulated by luminance or alpha
    # Let's do clean tint: target color for colored strokes
    mask = (alpha > 20)
    arr[mask, 0] = r_target
    arr[mask, 1] = g_target
    arr[mask, 2] = b_target
    
    return Image.fromarray(arr.astype(np.uint8), mode="RGBA")

def test_asset_loading():
    print("Testing asset loading...")
    for icon_name in ["timer", "flame", "chef_hat", "bulb", "cutlery", "sprig"]:
        p = ICONS_DIR / f"{icon_name}.png"
        assert p.exists(), f"Missing icon {p}"
        im = Image.open(p)
        print(f"Icon {icon_name}: size={im.size}, mode={im.mode}")

    for ribbon_name in ["ribbon_green_scroll", "ribbon_terracotta_arch", "ribbon_green_curled", "ribbon_terracotta_flourish"]:
        p = RIBBONS_DIR / f"{ribbon_name}.png"
        assert p.exists(), f"Missing ribbon {p}"
        im = Image.open(p)
        print(f"Ribbon {ribbon_name}: size={im.size}")

    for badge_name in ["badge_stamp_star", "badge_laurel_gourmet", "badge_wax_seal", "badge_rosette_gold"]:
        p = BADGES_DIR / f"{badge_name}.png"
        assert p.exists(), f"Missing badge {p}"
        im = Image.open(p)
        print(f"Badge {badge_name}: size={im.size}")

    tex_p = TEXTURES_DIR / "paper_parchment.jpg"
    assert tex_p.exists(), f"Missing texture {tex_p}"
    print("All assets exist and loaded successfully!")

if __name__ == "__main__":
    test_asset_loading()
