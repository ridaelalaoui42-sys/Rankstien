"""
RankStein Remasterer — Viral Pin Resurrection Engine
Scrapes, downloads, edits, and republishes viral pins with luxury branding.
"""

import asyncio
import re
from pathlib import Path

import httpx
import piexif
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont
from playwright.async_api import async_playwright
from playwright_stealth import Stealth

# Configuration
PINTEREST_BASE = "https://es.pinterest.com"
SESSION_DIR = Path("data/sessions/remasterer_v1")
DOWNLOAD_DIR = Path("data/media/remaster_raw")
REMASTER_DIR = Path("data/media/remaster_final")
[d.mkdir(parents=True, exist_ok=True) for d in [DOWNLOAD_DIR, REMASTER_DIR]]


def inject_seo_metadata(image_path, title, description, keywords):
    """Injects EXIF metadata (Title, Description, Keywords) into JPEG images for SEO."""
    try:
        # Only works on JPEGs easily with piexif
        if str(image_path).lower().endswith((".png", ".webp")):
            return  # Skip PNG/WEBP for now, or convert to JPEG first

        exif_dict = {"0th": {}, "Exif": {}, "GPS": {}, "1st": {}, "Interop": {}}

        # Standard Exif
        exif_dict["0th"][piexif.ImageIFD.ImageDescription] = description.encode("utf-8")

        # Windows XP Tags (Highly read by search engines)
        exif_dict["0th"][piexif.ImageIFD.XPTitle] = title.encode("utf-16le")
        exif_dict["0th"][piexif.ImageIFD.XPComment] = description.encode("utf-16le")
        exif_dict["0th"][piexif.ImageIFD.XPKeywords] = keywords.encode("utf-16le")

        exif_bytes = piexif.dump(exif_dict)
        piexif.insert(exif_bytes, str(image_path))
        print(f"   SEO Metadata injected into {Path(image_path).name}")
    except Exception as e:
        print(f"   FAILED to inject metadata: {e}")


class PinRemasterer:
    def __init__(self, headless=True, session_name="remasterer_v1"):
        self.headless = headless
        self.session_dir = SESSION_DIR.parent / session_name
        self.session_dir.mkdir(parents=True, exist_ok=True)
        self.pw = None
        self.context = None
        self.page = None

    async def start(self):
        # Clean Firefox locks before every launch (prevents "already running" errors)
        for lock_name in ["parent.lock", ".parentlock", "lock"]:
            lock_path = self.session_dir / lock_name
            if lock_path.exists():
                try:
                    lock_path.unlink()
                except Exception:
                    pass

        self.pw = await async_playwright().start()
        self.context = await self.pw.firefox.launch_persistent_context(
            user_data_dir=str(self.session_dir),
            headless=True,
            viewport={"width": 1440, "height": 900},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:128.0) Gecko/20100101 Firefox/128.0",
            args=["--no-remote", "--allow-downgrade"],
        )
        self.page = self.context.pages[0] if self.context.pages else await self.context.new_page()
        await Stealth().apply_stealth_async(self.page)

    async def stop(self):
        if self.context:
            await self.context.close()
        if self.pw:
            await self.pw.stop()

    async def collect_and_download(self, keyword: str, count: int = 50):
        """Scrapes pins and downloads images with titles/metadata."""
        print(f"Collecting {count} viral pins for: {keyword}...")
        results = []
        search_url = f"{PINTEREST_BASE}/search/pins/?q={keyword}&rs=typed"

        await self.page.goto(search_url, wait_until="domcontentloaded", timeout=60000)
        await asyncio.sleep(5)

        # Aggressive scroll to load more
        for _ in range(5):
            await self.page.mouse.wheel(0, 3000)
            await asyncio.sleep(2)

        pins = await self.page.query_selector_all('[data-test-id="pin"]')
        async with httpx.AsyncClient() as client:
            for i, pin in enumerate(pins[:count]):
                try:
                    img_el = await pin.query_selector("img")
                    if not img_el:
                        continue

                    img_url = await img_el.get_attribute("src")
                    alt_text = await img_el.get_attribute("alt") or ""

                    # Get high-res version
                    img_url = (
                        img_url.replace("236x", "originals")
                        .replace("474x", "originals")
                        .replace("736x", "originals")
                    )

                    link_el = await pin.query_selector('a[href*="/pin/"]')
                    href = await link_el.get_attribute("href")
                    pin_id = re.search(r"/pin/(\d+)", href).group(1)

                    # Download
                    resp = await client.get(img_url)
                    if resp.status_code == 200:
                        file_ext = ".jpg" if "jpg" in img_url.lower() or "jpeg" in img_url.lower() else ".png"
                        raw_path = DOWNLOAD_DIR / f"{pin_id}{file_ext}"
                        with open(raw_path, "wb") as f:
                            f.write(resp.content)

                        results.append(
                            {
                                "pin_id": pin_id,
                                "raw_path": str(raw_path),
                                "original_url": f"{PINTEREST_BASE}{href}",
                                "original_title": alt_text,
                            }
                        )
                        if len(results) % 10 == 0:
                            print(f"   Downloaded {len(results)} images...")
                except Exception:
                    continue

        return results

    def _get_accent_color(self, img):
        """Extracts the dominant vibrant color using a more robust sampling."""
        try:
            # Resize and convert to RGB for easier processing
            small_img = img.resize((100, 100)).convert("RGB")
            # Get pixels and filter out extremes
            pixels = list(small_img.getdata())
            vibrant_pixels = []
            for r, g, b in pixels:
                # Check for saturation (vibrancy)
                if max(r, g, b) - min(r, g, b) > 40:  # Saturation threshold
                    # Check for brightness (not too dark, not too light)
                    if 40 < (r + g + b) / 3 < 200:
                        vibrant_pixels.append((r, g, b))

            if vibrant_pixels:
                # Pick the average of the most vibrant ones
                vibrant_pixels.sort(key=lambda p: max(p) - min(p), reverse=True)
                return vibrant_pixels[0]

            return (230, 0, 35)  # Default Pinterest Red
        except:
            return (230, 0, 35)

    def _get_font(self, name, size, weight="Regular"):
        """Class-level font loader with robust fallbacks."""
        font_dir = Path("data/fonts")
        sys_font_dir = Path("C:/Windows/Fonts")

        # 1. Try local data/fonts
        local_path = font_dir / f"{name}-{weight}.ttf"
        if local_path.exists():
            try:
                return ImageFont.truetype(str(local_path), size)
            except:
                pass

        # 2. Try System Fallbacks
        fallbacks = {
            "PlayfairDisplay": ["timesbd.ttf", "georgiab.ttf", "pala.ttf"],
            "Montserrat": ["segoeuib.ttf", "arialbd.ttf", "tahomabd.ttf"],
            "GreatVibes": ["GreatVibes-Regular.ttf"],
        }

        for fallback in fallbacks.get(name, []):
            fb_path = sys_font_dir / fallback
            if fb_path.exists():
                try:
                    return ImageFont.truetype(str(fb_path), size)
                except:
                    pass

        return ImageFont.load_default()

    def _draw_text_fitted(
        self,
        draw,
        text,
        font_name,
        size,
        color,
        target_w,
        max_width,
        start_y,
        max_height=None,
        weight="Bold",
        line_spacing=1.1,
        shadow=False,
        align="center",
    ):
        """Draws text wrapped and scaled to fit the target width AND height perfectly."""

        def get_wrapped_lines(text, font, max_pixel_width):
            lines = []
            words = text.split()
            if not words:
                return []

            current_line = words[0]
            for word in words[1:]:
                test_line = current_line + " " + word
                bbox = draw.textbbox((0, 0), test_line, font=font)
                if (bbox[2] - bbox[0]) <= max_pixel_width:
                    current_line = test_line
                else:
                    lines.append(current_line)
                    current_line = word
            lines.append(current_line)
            return lines

        # Initial font sizing
        current_size = size
        font = self._get_font(font_name, current_size, weight)

        # Dynamic Scaling: Shrink font if lines are too wide OR too tall
        while current_size > 22:  # Lower minimum to handle very long titles
            current_font = self._get_font(font_name, current_size, weight)
            wrapped_lines = get_wrapped_lines(text.upper(), current_font, max_width)

            # Calculate total height
            total_h = 0
            for line in wrapped_lines:
                bbox = draw.textbbox((0, 0), line, font=current_font)
                total_h += (bbox[3] - bbox[1]) * line_spacing

            if not max_height or total_h <= max_height:
                font = current_font
                break

            current_size -= 2

        # Final wrap with the chosen font
        wrapped_lines = get_wrapped_lines(text.upper(), font, max_width)

        # Render lines centered
        curr_y = start_y
        for line in wrapped_lines:
            l_bbox = draw.textbbox((0, 0), line, font=font)
            tw = l_bbox[2] - l_bbox[0]
            th = l_bbox[3] - l_bbox[1]

            if align == "center":
                tx = (target_w - tw) // 2
            else:  # left
                tx = 100

            if shadow:
                # Subtler but visible shadow
                draw.text((tx + 2, curr_y + 2), line, font=font, fill=(0, 0, 0, 180))

            draw.text((tx, curr_y), line, font=font, fill=color)
            curr_y += int(th * line_spacing)

        return curr_y

    def _apply_texture(self, img):
        """Adds a subtle grain texture for a 'tactile' 2026 feel."""
        import numpy as np

        width, height = img.size
        # Finer, more sophisticated grain
        noise = np.random.normal(0, 8, (height, width, 3)).astype(np.uint8)
        noise_img = Image.fromarray(noise).convert("RGBA")

        # Super subtle blend
        return Image.blend(img, noise_img, 0.03)

    def apply_editorial_overlay(
        self, image_path, title_text, hook=None, layout="editorial", brand_name="RecetaDolce"
    ):
        """
        Advanced V4.2 Design Engine — Luxury Pinterest Edition.
        Layouts: editorial, tutorial, minimalist, luxury, split.
        """
        try:
            import random

            if not hook:
                hooks = [
                    "PASO A PASO",
                    "RECETA VIRAL",
                    "SECRETO REVELADO",
                    "EDICIÓN 2026",
                    "CALIDAD PREMIUM",
                    "TENDENCIA VIRAL",
                ]
                hook = random.choice(hooks)

            with Image.open(image_path) as img:
                target_w, target_h = 1000, 1500
                if img.mode != "RGBA":
                    img = img.convert("RGBA")

                # --- 1. Smart Cropping & Padding ---
                if layout == "split":
                    img_h = int(target_h * 0.65)
                    img_w = target_w
                    img_ratio = img.width / img.height
                    target_ratio = img_w / img_h

                    if img_ratio > target_ratio:
                        new_h = img_h
                        new_w = int(new_h * img_ratio)
                        canvas_img = img.resize((new_w, new_h), Image.Resampling.LANCZOS)
                        left = (new_w - img_w) // 2
                        canvas_img = canvas_img.crop((left, 0, left + img_w, img_h))
                    else:
                        new_w = img_w
                        new_h = int(new_w / img_ratio)
                        canvas_img = img.resize((new_w, new_h), Image.Resampling.LANCZOS)
                        top = (new_h - img_h) // 2
                        canvas_img = canvas_img.crop((0, top, img_w, top + img_h))

                    full_canvas = Image.new("RGBA", (target_w, target_h), (252, 248, 242, 255))
                    full_canvas.paste(canvas_img, (0, 0))
                    canvas_img = full_canvas
                else:
                    img_ratio = img.width / img.height
                    target_ratio = target_w / target_h
                    if img_ratio > target_ratio:
                        new_h = target_h
                        new_w = int(new_h * img_ratio)
                        canvas_img = img.resize((new_w, new_h), Image.Resampling.LANCZOS)
                        left = (new_w - target_w) // 2
                        canvas_img = canvas_img.crop((left, 0, left + target_w, target_h))
                    else:
                        new_w = target_w
                        new_h = int(new_w / img_ratio)
                        canvas_img = img.resize((new_w, new_h), Image.Resampling.LANCZOS)
                        top = (new_h - target_h) // 2
                        canvas_img = canvas_img.crop((0, top, target_w, top + target_h))

                # --- 2. Professional Enhancements ---
                canvas_img = ImageEnhance.Color(canvas_img).enhance(1.25)  # More vibrant
                canvas_img = ImageEnhance.Contrast(canvas_img).enhance(1.15)
                canvas_img = self._apply_texture(canvas_img)

                # --- 2.1 Protection Gradient (Hide original pin titles) ---
                overlay = Image.new("RGBA", (target_w, target_h), (0, 0, 0, 0))
                o_draw = ImageDraw.Draw(overlay)
                # Stronger dark gradient at top to cover original text
                for i in range(500):
                    alpha = int((1 - i / 500) * 230)
                    o_draw.line([0, i, target_w, i], fill=(10, 10, 10, alpha))
                canvas_img = Image.alpha_composite(canvas_img, overlay)

                accent_color = self._get_accent_color(img)
                draw = ImageDraw.Draw(canvas_img, "RGBA")

                # --- 3. Font Setup ---
                font_hook = self._get_font("Montserrat", 45, "Bold")
                font_brand = self._get_font("Montserrat", 35, "Regular")
                font_cta = self._get_font("Montserrat", 50, "Bold")
                font_script = self._get_font("GreatVibes", 190, "Regular")
                font_badge = self._get_font("Montserrat", 30, "Bold")

                # --- 4. Layout Implementation ---
                text_color = (255, 255, 255)
                curr_y = 400

                if layout == "editorial":
                    # Glassmorphism Box - Darker and more premium
                    mask = Image.new("L", (target_w, target_h), 0)
                    m_draw = ImageDraw.Draw(mask)
                    # Slightly wider and taller box
                    box_coords = [50, target_h // 2 - 250, target_w - 50, target_h // 2 + 580]
                    m_draw.rounded_rectangle(box_coords, radius=60, fill=255)
                    blurred = canvas_img.filter(ImageFilter.GaussianBlur(radius=50))
                    canvas_img.paste(blurred, (0, 0), mask=mask)

                    overlay = Image.new("RGBA", (target_w, target_h), (0, 0, 0, 0))
                    o_draw = ImageDraw.Draw(overlay)
                    # Glass effect with better contrast
                    o_draw.rounded_rectangle(
                        box_coords, radius=60, fill=(20, 20, 20, 100), outline=(255, 255, 255, 180), width=5
                    )
                    canvas_img = Image.alpha_composite(canvas_img, overlay)
                    draw = ImageDraw.Draw(canvas_img, "RGBA")
                    curr_y = target_h // 2 - 160

                elif layout == "luxury":
                    # Bottom Dark Gradient & Elegant Script Accent
                    overlay = Image.new("RGBA", (target_w, target_h), (0, 0, 0, 0))
                    o_draw = ImageDraw.Draw(overlay)
                    # Very deep gradient at bottom
                    for i in range(target_h - 1100, target_h):
                        alpha = int(((i - (target_h - 1100)) / 1100) * 255)
                        o_draw.line([0, i, target_w, i], fill=(5, 5, 5, alpha))
                    canvas_img = Image.alpha_composite(canvas_img, overlay)
                    draw = ImageDraw.Draw(canvas_img, "RGBA")

                    # Script Brand Signature with outer glow
                    brand_script = brand_name
                    sw_bbox = draw.textbbox((0, 0), brand_script, font=font_script)
                    sww = sw_bbox[2] - sw_bbox[0]
                    tx, ty = (target_w - sww) // 2, target_h - 920
                    # Fake glow
                    draw.text((tx + 2, ty + 2), brand_script, font=font_script, fill=(0, 0, 0, 100))
                    draw.text((tx, ty), brand_script, font=font_script, fill=accent_color)
                    curr_y = target_h - 700

                elif layout == "tutorial":
                    # Solid Top Banner
                    draw.rectangle([0, 0, target_w, 280], fill=(10, 10, 10, 255))
                    draw.text((100, 110), hook, font=font_hook, fill=accent_color)

                    # Larger Text box at bottom with shadow
                    box_coords = [40, target_h - 680, target_w - 40, target_h - 60]
                    draw.rounded_rectangle(
                        [c + 5 for c in box_coords], radius=50, fill=(0, 0, 0, 80)
                    )  # Shadow
                    draw.rounded_rectangle(box_coords, radius=50, fill=(255, 255, 255, 255))
                    draw = ImageDraw.Draw(canvas_img, "RGBA")
                    curr_y = target_h - 630
                    text_color = (15, 15, 15)

                elif layout == "minimalist":
                    # Clean top text with deep shadow for readability
                    overlay = Image.new("RGBA", (target_w, target_h), (0, 0, 0, 0))
                    o_draw = ImageDraw.Draw(overlay)
                    for i in range(900):
                        alpha = int((1 - i / 900) * 240)
                        o_draw.line([0, i, target_w, i], fill=(0, 0, 0, alpha))
                    canvas_img = Image.alpha_composite(canvas_img, overlay)
                    draw = ImageDraw.Draw(canvas_img, "RGBA")
                    curr_y = 180

                elif layout == "split":
                    # Sandwich/Stripe Layout
                    strip_h = 560
                    strip_y = (target_h - strip_h) // 2 + 180

                    draw.rectangle(
                        [0, strip_y, target_w, strip_y + strip_h],
                        fill=(accent_color[0], accent_color[1], accent_color[2], 255),
                    )

                    brand_script = brand_name
                    sw_bbox = draw.textbbox((0, 0), brand_script, font=font_script)
                    sww = sw_bbox[2] - sw_bbox[0]
                    draw.text(
                        ((target_w - sww) // 2, strip_y - 160),
                        brand_script,
                        font=font_script,
                        fill=(255, 255, 255, 255),
                    )

                    curr_y = strip_y + 70
                    text_color = (255, 255, 255)

                # --- 5. Title Rendering (Smart Fitting) ---
                max_h_map = {
                    "editorial": 450,
                    "luxury": 450,
                    "tutorial": 400,
                    "minimalist": 450,
                    "split": 350,
                }

                curr_y = self._draw_text_fitted(
                    draw,
                    title_text,
                    "PlayfairDisplay",
                    130,
                    text_color,
                    target_w,
                    840 if layout in ["editorial", "tutorial"] else 920,
                    curr_y,
                    max_height=max_h_map.get(layout, 400),
                    shadow=(text_color == (255, 255, 255)),
                )

                # --- 6. Aesthetic Badges & Social Proof ---
                def draw_stars(d, x_center, y, count=None, size=45):
                    if not count:
                        count = random.choice([4.8, 4.9, 5.0])
                    full_stars = int(count)
                    star_w = size + 12
                    start_x = x_center - (star_w * 5) // 2
                    for i in range(5):
                        fill = (255, 210, 0) if i < full_stars else (200, 200, 200)
                        try:
                            d.text(
                                (start_x + i * star_w, y),
                                "★",
                                font=self._get_font("Lora", size, "Bold"),
                                fill=fill,
                            )
                        except:
                            pass

                    # Add numeric rating
                    font_rating = self._get_font("Montserrat", 32, "Bold")
                    d.text(
                        (start_x + 5 * star_w + 10, y + 5),
                        f"{count}/5",
                        font=font_rating,
                        fill=(255, 255, 255) if layout != "tutorial" else (50, 50, 50),
                    )

                draw_stars(draw, target_w // 2, curr_y + 25)
                curr_y += 90

                # Badge moved to top-right corner safely
                badge_text = f"{random.randint(15, 45)} MIN"
                draw.rounded_rectangle([target_w - 240, 60, target_w - 60, 120], radius=30, fill=accent_color)
                draw.text((target_w - 215, 75), badge_text, font=font_badge, fill="white")

                # --- 7. Call to Action Button REMOVED ---
                # Buttons removed per user request to clean up designs

                # --- 8. Branding ---

                brand_text = f"{brand_name.upper()}.COM"
                b_bbox = draw.textbbox((0, 0), brand_text, font=font_brand)
                draw.text(
                    ((target_w - (b_bbox[2] - b_bbox[0])) // 2, target_h - 60),
                    brand_text,
                    font=font_brand,
                    fill=text_color,
                )

                # --- 9. Final Save & SEO ---
                clean_title = re.sub(r"[^a-z0-9]+", "-", title_text.lower()).strip("-")
                filename = f"remastered_v4_{layout}_{clean_title}_{Path(image_path).name}"
                save_path = REMASTER_DIR / filename
                if save_path.suffix.lower() not in [".jpg", ".jpeg"]:
                    save_path = save_path.with_suffix(".jpg")

                canvas_img.convert("RGB").save(save_path, "JPEG", quality=95, optimize=True)

                inject_seo_metadata(
                    save_path,
                    f"{title_text} | {brand_name} Luxury Edition",
                    f"Aprende a preparar {title_text}. {hook}. Diseño exclusivo 2026.",
                    f"{title_text}, receta fit, lujo, gourmet, pinterest 2026",
                )
                return save_path

        except Exception as e:
            print(f"   [!] Remaster error: {e}")
            return None


async def run_remasterer(keyword, article_title, brand_name="RecetaDolce", session_name="remasterer_v1"):
    remasterer = PinRemasterer(headless=True, session_name=session_name)
    await remasterer.start()

    print("\n--- RankStein Remasterer V4.1 Active ---")
    print(f"Targeting: {keyword} | Title: {article_title} | Brand: {brand_name} | Session: {session_name}")

    collected = await remasterer.collect_and_download(keyword, count=20)

    final_assets = []
    layouts = ["editorial", "tutorial", "minimalist", "luxury", "split"]

    for i, item in enumerate(collected):
        layout = layouts[i % len(layouts)]
        print(f"   [{i + 1}/{len(collected)}] Remastering with {layout.upper()} layout...")
        processed_path = remasterer.apply_editorial_overlay(
            item["raw_path"], article_title, layout=layout, brand_name=brand_name
        )
        if processed_path:
            final_assets.append({"original_pin_id": item["pin_id"], "remastered_path": str(processed_path)})

    await remasterer.stop()
    print(f"\nCOMPLETED: {len(final_assets)} luxury pins generated in {REMASTER_DIR}")
    return final_assets


if __name__ == "__main__":
    import sys

    kw = sys.argv[1] if len(sys.argv) > 1 else "postres virales 2026"
    title = sys.argv[2] if len(sys.argv) > 2 else "Postres Irresistibles"
    asyncio.run(run_remasterer(kw, title))
