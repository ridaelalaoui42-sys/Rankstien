from pathlib import Path
from PIL import Image
import numpy as np
from scipy.ndimage import label

BRAIN_DIR = Path(r"C:\Users\REDX420\.gemini\antigravity\brain\4def31ef-1cbb-4e58-b00a-3c4bea3fd439")
ASSETS_DIR = Path(__file__).resolve().parents[2] / "rankstein" / "assets"
RIBBONS_DIR = ASSETS_DIR / "ribbons"
RIBBONS_DIR.mkdir(parents=True, exist_ok=True)

def perfect_extract_all_arch_ribbons():
    src_p = BRAIN_DIR / "culinary_arch_ribbons_1791506993929.jpg"
    img = Image.open(src_p).convert("RGB")
    arr = np.array(img, dtype=np.uint8)
    
    # Non-white pixels (where any channel is < 244)
    min_rgb = np.min(arr, axis=2)
    ribbon_mask = min_rgb < 244
    
    lbl, num_features = label(ribbon_mask)
    print(f"Connected components: {num_features}")
    
    # 4 ribbons ordered from top to bottom by y_min
    names = [
        "arch_ribbon_green",
        "arch_ribbon_terracotta",
        "arch_ribbon_burgundy",
        "arch_ribbon_gold",
    ]
    
    components = []
    for idx in range(1, num_features + 1):
        ys, xs = np.where(lbl == idx)
        if len(xs) > 10000:  # Valid ribbon
            components.append((ys.min(), idx, ys, xs))
    
    components.sort(key=lambda c: c[0])  # Sort by top y
    
    for (y_top, c_id, ys, xs), name in zip(components, names):
        x1, x2 = xs.min(), xs.max()
        y1, y2 = ys.min(), ys.max()
        
        # Create RGBA cutout strictly for this component
        comp_mask = (lbl == c_id)
        
        # Crop bounds with 4px padding
        px1 = max(0, x1 - 4)
        py1 = max(0, y1 - 4)
        px2 = min(arr.shape[1], x2 + 5)
        py2 = min(arr.shape[0], y2 + 5)
        
        sub_rgb = arr[py1:py2, px1:px2].copy()
        sub_mask = comp_mask[py1:py2, px1:px2]
        sub_min = min_rgb[py1:py2, px1:px2]
        
        # Smooth alpha:
        # Inside component: alpha based on distance from white
        alpha = np.zeros_like(sub_min, dtype=np.float32)
        
        # Where component mask is True:
        # Full alpha if sub_min < 230, smooth falloff 230->248
        feather_start = 228
        threshold = 248
        
        core = sub_mask & (sub_min <= feather_start)
        alpha[core] = 255.0
        
        transition = sub_mask & (sub_min > feather_start) & (sub_min < threshold)
        alpha[transition] = 255.0 * (threshold - sub_min[transition]) / (threshold - feather_start)
        
        out_arr = np.dstack([sub_rgb, np.clip(alpha, 0, 255).astype(np.uint8)])
        out_im = Image.fromarray(out_arr, mode="RGBA")
        
        out_p = RIBBONS_DIR / f"{name}.png"
        out_im.save(out_p, "PNG")
        print(f"Extracted {name}.png: size={out_im.size}, y_range=[{y1}, {y2}]")

if __name__ == "__main__":
    perfect_extract_all_arch_ribbons()
