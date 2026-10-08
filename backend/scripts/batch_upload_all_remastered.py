import asyncio
import os
import random
import re
import sys
from pathlib import Path

import piexif

project_root = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(project_root / "backend" / "scripts"))

import batch_upload_remastered
from batch_upload_remastered import (
    create_pin,
    create_stealth_browser,
    ensure_logged_in,
    get_board_for_slug,
    get_supabase,
)

batch_upload_remastered.PINTEREST_BASE = "https://www.pinterest.com"

MEDIA_DIR = project_root / "data" / "media" / "remaster_final"
UPLOADED_TRACKER = project_root / "data" / "media" / "uploaded_remasters.txt"


def normalize(text):
    if not text:
        return ""
    import unicodedata

    text = unicodedata.normalize("NFKD", text).encode("ASCII", "ignore").decode("utf-8")
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def get_exif_title(image_path):
    try:
        exif_dict = piexif.load(str(image_path))
        if piexif.ImageIFD.XPTitle in exif_dict.get("0th", {}):
            title_tuple = exif_dict["0th"][piexif.ImageIFD.XPTitle]
            return bytes(title_tuple).decode("utf-16le").rstrip("\x00")
    except:
        pass
    return ""


async def main():
    email = os.environ.get("PINTEREST_EMAIL", "").strip()
    password = os.environ.get("PINTEREST_PASSWORD", "").strip()
    if not email or not password:
        raise RuntimeError("PINTEREST_EMAIL and PINTEREST_PASSWORD must be set before batch upload.")

    sb = get_supabase()
    res = sb.table("posts").select("id, title, slug, excerpt").eq("status", "published").execute()
    posts = res.data

    uploaded_files = set()
    if UPLOADED_TRACKER.exists():
        with open(UPLOADED_TRACKER) as f:
            uploaded_files = set(line.strip() for line in f.readlines())

    all_files = list(MEDIA_DIR.glob("remastered_*.jpg")) + list(MEDIA_DIR.glob("remastered_*.png"))

    to_upload = []

    for f in all_files:
        if f.name in uploaded_files:
            continue

        exif_title = get_exif_title(f)
        filename_norm = normalize(f.name)
        exif_norm = normalize(exif_title)

        matched_post = None
        best_score = 0

        for p in posts:
            post_title_norm = normalize(p["title"])
            post_slug_norm = normalize(p["slug"])

            score = 0
            if post_slug_norm in filename_norm.replace(" ", ""):
                score += 10

            # Match EXIF title words
            if exif_norm:
                post_words = set(post_title_norm.split())
                exif_words = set(exif_norm.split())
                common = post_words.intersection(exif_words)
                if len(common) > 2:
                    score += len(common)

            if score > best_score:
                best_score = score
                matched_post = p

        if matched_post and best_score > 2:
            to_upload.append({"file": f, "post": matched_post})

    print(f"Found {len(to_upload)} new files ready to upload out of {len(all_files)} total files.")

    if not to_upload:
        return

    pw, context, page = await create_stealth_browser(headless=True)
    try:
        if await ensure_logged_in(page, email, password):
            for i, item in enumerate(to_upload, 1):
                try:
                    post = item["post"]
                    img = item["file"]
                    board = get_board_for_slug(post["slug"])

                    print(f"[{i}/{len(to_upload)}] Pinning {img.name} -> {post['slug']}")

                    # Check for closed context and recreate if needed
                    try:
                        if page.is_closed():
                            raise Exception("Page closed")
                    except Exception:
                        print("⚠️ Browser context closed. Recreating...")
                        try:
                            if context:
                                await context.close()
                            if pw:
                                await pw.stop()
                        except Exception:
                            pass
                        pw, context, page = await create_stealth_browser(headless=True)
                        await ensure_logged_in(page, email, password)

                    pin_id = await create_pin(page, post, img, board)

                    if pin_id:
                        print(f"✅ Success! Pin ID: {pin_id} linked to {post['slug']}")
                        with open(UPLOADED_TRACKER, "a") as f:
                            f.write(img.name + "\n")
                        # Delete the image from remaster_final
                        try:
                            if img.exists():
                                img.unlink()
                                print(f"🗑️ Deleted {img.name} from remaster_final")
                        except Exception as e:
                            print(f"⚠️ Failed to delete {img.name}: {e}")

                        # Delete corresponding file from remaster_raw
                        try:
                            raw_name = img.name.replace("remastered_", "")
                            raw_path = project_root / "data" / "media" / "remaster_raw" / raw_name
                            if raw_path.exists():
                                raw_path.unlink()
                                print(f"🗑️ Deleted {raw_name} from remaster_raw")
                        except Exception as e:
                            print(f"⚠️ Failed to delete raw image {raw_name}: {e}")
                    else:
                        print(f"❌ Failed to pin {img.name}")
                except Exception as loop_e:
                    print(
                        f"❌ Exception during pinning {img.name if 'img' in locals() else 'unknown'}: {loop_e}"
                    )

                if i < len(to_upload):
                    delay = random.uniform(9, 14)
                    print(f"⏱️ Sleeping {delay:.1f}s...")
                    await asyncio.sleep(delay)
    finally:
        try:
            if context:
                await context.close()
            if pw:
                await pw.stop()
        except Exception:
            pass


if __name__ == "__main__":
    asyncio.run(main())
