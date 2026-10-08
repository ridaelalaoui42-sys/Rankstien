import argparse
import asyncio
import logging
import os
import random
import re
import shutil
import sys
import unicodedata
from logging.handlers import RotatingFileHandler
from pathlib import Path

from dotenv import load_dotenv

# ---------- Config ----------
load_dotenv(override=False)
SUPABASE_URL = os.environ.get("NEXT_PUBLIC_SUPABASE_URL", "https://xjvmnmfczvwkjiasirsl.supabase.co")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
BASE_URL = "https://recetadolce.com"
PINTEREST_BASE = "https://es.pinterest.com"
DEFAULT_BOARD = "Recetas Españolas"

# Paths
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
MEDIA_DIR = PROJECT_ROOT / "data" / "media"
SESSION_DIR = PROJECT_ROOT / "data" / "sessions" / "pinterest_rida_v7"
LOG_DIR = PROJECT_ROOT / "data" / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
ARCHIVE_DIR = MEDIA_DIR / "archive"
ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)

# Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(message)s",
    handlers=[
        RotatingFileHandler(
            str(LOG_DIR / "batch_upload.log"), maxBytes=5 * 1024 * 1024, backupCount=2, encoding="utf-8"
        ),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger("batch_uploader")

# EEAT Citations
EEAT_CITATIONS = {
    "seafood": "Cumpliendo con las normativas de AESAN y EFSA para la seguridad alimentaria en mariscos.",
    "meat": "Siguiendo los estándares del Codex Alimentarius para el manejo seguro de carnes.",
    "eggs": "Basado en el RD 1021/2022 para la higiene de preparaciones con huevo.",
    "general": "Receta elaborada bajo los estándares de calidad y seguridad de AESAN 2026.",
}


def _kill_firefox_locks():
    """Targeted profile cleanup; keeps sibling Pinterest workers alive."""
    from pinterest_batch_core import cleanup_session_artifacts

    return cleanup_session_artifacts(SESSION_DIR, "firefox")


def cleanup_workspace(sb):
    import time

    logger.info("🧹 Starting workspace cleanup...")
    # Delete debug and temp images
    for p in ["debug_login_fail_*.jpg", "upload_temp_batch.*", "debug_*.png"]:
        for f in PROJECT_ROOT.rglob(p):
            try:
                f.unlink()
            except Exception:
                pass

    # Delete files in archive older than 1 day
    now = time.time()
    for f in ARCHIVE_DIR.glob("*.*"):
        if now - f.stat().st_mtime > 86400:
            try:
                f.unlink()
                logger.info(f"   🗑️ Deleted old archived file: {f.name}")
            except Exception:
                pass

    # Archive images of ALREADY uploaded pins
    res = sb.table("posts").select("id, slug, pinterest_pin_id").eq("status", "published").execute()
    pinned = [p for p in res.data if p.get("pinterest_pin_id") and len(str(p["pinterest_pin_id"])) >= 15]
    logger.info(f"   🔍 Checking {len(pinned)} pinned posts for local images to archive...")
    archived_count = 0
    for p in pinned:
        img = find_local_image_for_slug(p["slug"])
        if img and img.parent != ARCHIVE_DIR:
            try:
                shutil.move(str(img), str(ARCHIVE_DIR / img.name))
                archived_count += 1
            except Exception as e:
                pass
    if archived_count > 0:
        logger.info(f"   📦 Archived {archived_count} images for already pinned posts.")
    logger.info("✨ Workspace cleanup complete.")


def get_supabase():
    try:
        from supabase import create_client

        return create_client(SUPABASE_URL, SUPABASE_KEY)
    except Exception as e:
        logger.error(f"Supabase connection failed: {e}")
        sys.exit(1)


def fetch_unpinned_posts(sb, limit=None):
    res = (
        sb.table("posts")
        .select("id, title, slug, excerpt, pinterest_pin_id")
        .eq("status", "published")
        .order("created_at", desc=True)
        .execute()
    )
    unpinned = [p for p in res.data if not p.get("pinterest_pin_id") or len(str(p["pinterest_pin_id"])) < 15]
    return unpinned[:limit] if limit else unpinned


def update_pin_id(sb, post_id, pin_id):
    try:
        sb.table("posts").update({"pinterest_pin_id": str(pin_id)}).eq("id", post_id).execute()
        logger.info(f"   ✅ Saved pin ID {pin_id}")
    except Exception as e:
        logger.error(f"Failed to update pin ID in Supabase: {e}")


def normalize(text):
    if not text:
        return ""
    text = "".join(c for c in unicodedata.normalize("NFD", str(text)) if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9]", "", text.lower())


def find_local_image_for_slug(slug):
    n_s = normalize(slug)
    keywords = [normalize(k) for k in slug.split("-") if len(k) > 3]
    best_f = None
    max_score = 0

    # Search both media and remaster_final
    search_dirs = [MEDIA_DIR, MEDIA_DIR / "remaster_final"]
    patterns = ["pin_*.*", "remastered_*.*"]

    all_files = []
    for d in search_dirs:
        if d.exists():
            for p in patterns:
                all_files.extend(list(d.glob(p)))

    for f in all_files:
        n_f = normalize(f.name)
        score = sum(1 for kw in keywords if kw in n_f)
        if n_s in n_f:
            score += 10
        if score > max_score:
            max_score = score
            best_f = f
    return best_f if max_score >= 2 else None


def build_pin_description(post):
    title = post["title"]
    slug = post["slug"]
    excerpt = post.get("excerpt", "") or ""
    # Maximize 500 char limit
    main_desc = (
        excerpt[:300]
        if len(excerpt) > 50
        else f"Aprende paso a paso cómo preparar la mejor receta de {title}. Un plato gourmet explicado por expertos."
    )

    eeat = EEAT_CITATIONS.get("general")
    if any(k in slug for k in ["marisco", "pulpo", "sepia", "bogavante", "gambas"]):
        eeat = EEAT_CITATIONS["seafood"]
    elif any(k in slug for k in ["pollo", "carne", "jamon", "cocido"]):
        eeat = EEAT_CITATIONS["meat"]
    elif any(k in slug for k in ["tortilla", "huevo", "mayonesa"]):
        eeat = EEAT_CITATIONS["eggs"]

    desc = f"{main_desc}\n\n🛡️ {eeat}\n\n🔗 Receta completa en RecetaDolce.com\n#RecetaDolce #CocinaEspañola #Gourmet #Recetas"
    return desc[:500]


async def human_type(page, selector_or_el, text):
    if isinstance(selector_or_el, str):
        el = await page.wait_for_selector(selector_or_el, timeout=20000)
    else:
        el = selector_or_el
    await el.click(force=True)
    await asyncio.sleep(1)
    await page.keyboard.down("Control")
    await page.keyboard.press("a")
    await page.keyboard.up("Control")
    await page.keyboard.press("Backspace")
    for char in text:
        await page.keyboard.type(char)
        await asyncio.sleep(random.uniform(0.04, 0.12))


async def create_stealth_browser(headless=True):
    from pinterest_batch_core import DEFAULT_BROWSER_MAP, PinterestAccount, create_turbo_browser

    browser = DEFAULT_BROWSER_MAP.get(SESSION_DIR.name, os.environ.get("PINTEREST_BROWSER", "firefox"))
    account = PinterestAccount(
        name=SESSION_DIR.name,
        session_dir=SESSION_DIR,
        email=os.environ.get("PINTEREST_EMAIL", ""),
        password=os.environ.get("PINTEREST_PASSWORD", ""),
        browser=browser,
    )
    return await create_turbo_browser(account, "batch_upload_remastered", headless=headless)


async def _click_visible(page, locator, timeout=1500):
    try:
        count = await locator.count()
    except Exception:
        return False
    for index in range(count):
        item = locator.nth(index)
        try:
            if await item.is_visible(timeout=timeout):
                await item.click(force=True, timeout=3000)
                await asyncio.sleep(1.5)
                return True
        except Exception:
            continue
    return False


async def _dismiss_login_overlays(page):
    for pattern in (
        re.compile(r"^(close|dismiss|fermer|cerrar)$", re.I),
        re.compile(r"se connecter avec google", re.I),
    ):
        try:
            await _click_visible(page, page.get_by_label(pattern), timeout=700)
        except Exception:
            pass
    for selector in (
        'button[aria-label="Close"]',
        'button[aria-label="Fermer"]',
        'button[aria-label="Cerrar"]',
        '[data-testid="close-button"]',
        '[data-test-id="closeup-close-button"]',
    ):
        try:
            if await _click_visible(page, page.locator(selector), timeout=700):
                return
        except Exception:
            pass


async def _open_login_form(page):
    """Force Pinterest into the login dialog, not the sign-up dialog."""
    # Check if inputs are already visible
    for _ in range(12):
        email = page.locator('input[type="email"], input#email, input[name="id"]').first
        password = page.locator('input[type="password"], input#password, input[name="password"]').first

        if await email.is_visible() and await password.is_visible():
            return True

        # Try to dismiss overlays
        await _dismiss_login_overlays(page)

        # Try to click explicit 'Log in' / 'Iniciar sesión' button if inputs are not visible
        try:
            btn = page.locator(
                'div[data-test-id="login-button"], button:has-text("Log in"), button:has-text("Iniciar sesión"), a:has-text("Log in"), a:has-text("Iniciar sesión")'
            ).first
            if await btn.is_visible():
                await btn.click(timeout=1000)
                await asyncio.sleep(1)
                continue
        except Exception:
            pass

        await asyncio.sleep(1)

    return False


async def _click_login_submit(page):
    submit_patterns = (
        re.compile(r"^Log in$", re.I),
        re.compile(r"^Se connecter$", re.I),
        re.compile(r"^Iniciar sesi[oó]n$", re.I),
        re.compile(r"^Acceder$", re.I),
    )
    for pattern in submit_patterns:
        if await _click_visible(page, page.get_by_role("button", name=pattern), timeout=700):
            return True
    buttons = page.locator('button[type="submit"]')
    for index in range(await buttons.count()):
        button = buttons.nth(index)
        try:
            text = ((await button.inner_text(timeout=700)) or "").strip()
            if re.search(r"continue|join|create|sign up|crear|registr", text, re.I):
                continue
            if await button.is_visible(timeout=700):
                await button.click(force=True, timeout=3000)
                await asyncio.sleep(1.5)
                return True
        except Exception:
            continue
    return False


async def ensure_logged_in(page, email, password):
    logger.info("🔐 Verifying Pinterest session...")
    try:
        await page.goto(f"{PINTEREST_BASE}/", wait_until="domcontentloaded")
        await asyncio.sleep(5)
        if await page.query_selector('[data-test-id="header-profile"], [data-test-id="header-avatar"]'):
            logger.info("✅ Session valid.")
            return True

        logger.warning("🔑 Not logged in. Attempting login flow...")
        await page.goto(f"{PINTEREST_BASE}/login/", wait_until="domcontentloaded")
        await asyncio.sleep(3)
        if not await _open_login_form(page):
            logger.error("Pinterest login form did not open.")
            await page.screenshot(path=str(PROJECT_ROOT / "data" / "debug_login_fail_batch.jpg"))
            return False
        await human_type(page, 'input#email, input[name="id"], input[type="email"]', email)
        await human_type(page, "input#password, input[name='password']", password)
        if not await _click_login_submit(page):
            await page.click('button[type="submit"]')
        await asyncio.sleep(10)

        success = (
            await page.query_selector('[data-test-id="header-profile"], [data-test-id="header-avatar"]')
            is not None
        )
        if success:
            logger.info("✅ Login successful.")
        else:
            logger.error("❌ Login failed.")
        return success
    except Exception as e:
        logger.error(f"Login error: {e}")
    return False


BOARD_KEYWORDS = {
    "recetas": [
        "arroz",
        "paella",
        "fideua",
        "bogavante",
        "marisco",
        "caldoso",
        "pollo",
        "carne",
        "cocido",
        "gazpacho",
        "tradicional",
        "abuela",
        "casera",
        "ibérico",
        "pasabocas",
        "tapa",
        "aperitivo",
        "guacamole",
        "bravas",
        "ajillo",
        "croquetas",
        "jamon",
        "pulpo",
        "tortilla",
        "chips",
        "ensalada",
        "vegetariano",
        "quinoa",
        "espina",
        "cesar",
        "griega",
        "aguacate",
        "campera",
        "saludable",
        "fresca",
    ],
    "Galetas": [
        "churros",
        "tarta",
        "helado",
        "postre",
        "mousse",
        "galletas",
        "bizcocho",
        "vainilla",
        "donuts",
        "crema",
        "mermelada",
        "mantequilla",
    ],
    "recetas fresas": ["fresa", "fresas", "fruta"],
}

DEFAULT_BOARD = "recetas"


def get_board_for_slug(slug):
    slug_norm = normalize(slug)
    best_board = DEFAULT_BOARD
    max_score = 0
    for board, keywords in BOARD_KEYWORDS.items():
        score = 0
        for kw in keywords:
            if kw in slug_norm:
                score += 2
            for part in slug.split("-"):
                if kw == normalize(part):
                    score += 5
        if score > max_score:
            max_score = score
            best_board = board
    return best_board


async def create_pin(page, post, image_path, board_name):
    title = post["title"]
    url = f"{BASE_URL}/{post['slug']}"
    desc = build_pin_description(post)
    from pinterest_batch_core import create_pin_from_fields

    return await create_pin_from_fields(
        page,
        image_path,
        title,
        url,
        desc,
        board_name,
        "batch_upload_remastered",
    )
    alt = f"Fotografía profesional de {title}. Receta gourmet de RecetaDolce.com"

    logger.info(f"📌 Pinning: {title[:40]}...")

    ext = image_path.suffix
    temp_img = PROJECT_ROOT / "data" / f"upload_temp_batch{ext}"
    shutil.copy(str(image_path), str(temp_img))

    try:
        await page.goto(f"{PINTEREST_BASE}/pin-creation-tool/", wait_until="domcontentloaded", timeout=60000)
        await asyncio.sleep(5)

        # Check if redirected away (e.g. to home)
        if "pin-creation-tool" not in page.url:
            logger.warning("   ⚠️ Redirected from creation tool. Retrying navigation...")
            await page.goto(f"{PINTEREST_BASE}/pin-creation-tool/")
            await asyncio.sleep(5)

        f_inp = await page.wait_for_selector('input[type="file"]', timeout=30000)
        if not f_inp:
            raise Exception("File input not found")

        await f_inp.set_input_files(str(temp_img))
        await asyncio.sleep(6)  # Wait for upload

        # Robust Metadata Selection (Match MCP logic)
        title_selectors = [
            '[data-test-id="pin-draft-title"] textarea',
            'textarea[placeholder*="título" i]',
            'div[role="textbox"][aria-label*="título" i]',
            'div[contenteditable="true"]',
        ]
        desc_selectors = [
            '[data-test-id="pin-draft-description"] textarea',
            'textarea[placeholder*="descripción" i]',
            'div[role="combobox"]',
        ]
        link_selectors = [
            'input[id="pin-draft-link"]',
            'input[placeholder*="enlace" i]',
            'input[placeholder*="link" i]',
            'input[placeholder*="website" i]',
            'input[aria-label*="link" i]',
            'input[name="link"]',
        ]

        # Fill Title
        for sel in title_selectors:
            try:
                el = await page.wait_for_selector(sel, timeout=4000)
                if el:
                    await human_type(page, el, title[:100])
                    break
            except:
                continue

        # Fill Description
        for sel in desc_selectors:
            try:
                el = await page.wait_for_selector(sel, timeout=2000)
                if el:
                    await human_type(page, el, desc[:500])
                    break
            except:
                continue

        # Alt Text
        try:
            alt_btn = await page.query_selector(
                'button:has-text("Add alt text"), button:has-text("Añadir texto alternativo")'
            )
            if alt_btn:
                await alt_btn.click()
                await asyncio.sleep(1)
                alt_inp = await page.query_selector(
                    'textarea[placeholder*="Explain" i], textarea[placeholder*="explica" i]'
                )
                if alt_inp:
                    await alt_inp.fill(alt[:500])
        except:
            pass

        # Fill Link
        link_filled = False
        for sel in link_selectors:
            try:
                el = await page.wait_for_selector(sel, timeout=2000)
                if el:
                    await human_type(page, el, url)
                    val = await el.input_value()
                    if url in val:
                        link_filled = True
                        break
                    else:
                        await el.fill(url)
                        link_filled = True
                        break
            except:
                continue

        if not link_filled:
            logger.warning(f"⚠️ Failed to fill link {url} via standard selectors!")

        # Board
        try:
            b_btn = await page.wait_for_selector(
                '[data-test-id="board-dropdown-select-button"], [data-test-id="board-selector"]',
                timeout=10000,
            )
            await b_btn.click(force=True)
            await asyncio.sleep(2)

            search_input = await page.query_selector(
                'input[placeholder*="Search" i], input[placeholder*="Buscar" i]'
            )
            if search_input:
                await search_input.fill(board_name)
                await asyncio.sleep(2)

            board_item = await page.query_selector(
                f'div[role="option"]:has-text("{board_name}"), div[data-test-id="board-row"]:has-text("{board_name}")'
            )
            if board_item:
                await board_item.click(force=True)
            else:
                first = await page.query_selector('div[role="option"]')
                if first:
                    await first.click(force=True)
        except:
            pass

        await asyncio.sleep(3)
        # Publish
        pub_btn = await page.query_selector(
            'button[data-test-id="board-dropdown-save-button"], button:has-text("Publish"), button:has-text("Publicar"), button:has-text("Save")'
        )
        if pub_btn:
            await pub_btn.click(force=True)
            logger.info("   🚀 Publish clicked. Waiting for ID...")
            for _ in range(30):
                await asyncio.sleep(1)
                match = re.search(r"/pin/(\d+)", page.url)
                if match:
                    return match.group(1)
                view_pin = await page.query_selector('a[href*="/pin/"]')
                if view_pin:
                    href = await view_pin.get_attribute("href")
                    m = re.search(r"/pin/(\d+)", href or "")
                    return m.group(1) if m else None
    except Exception as e:
        logger.error(f"   ❌ Error pinning {title[:30]}: {e}")
    finally:
        if temp_img.exists():
            temp_img.unlink()
    return None


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()

    email = os.environ.get("PINTEREST_EMAIL", "")
    password = os.environ.get("PINTEREST_PASSWORD", "")

    sb = get_supabase()

    # Run cleanup of previously uploaded pins and temp files
    cleanup_workspace(sb)

    posts = fetch_unpinned_posts(sb, args.limit)
    matched = [
        (p, find_local_image_for_slug(p["slug"])) for p in posts if find_local_image_for_slug(p["slug"])
    ]

    logger.info(f"🚀 Batch starting. Found {len(matched)} posts with matching local images.")
    if not matched:
        return

    pw, context, page = None, None, None
    try:
        pw, context, page = await create_stealth_browser(headless=True)
        if not await ensure_logged_in(page, email, password):
            logger.error("❌ Failed to verify initial session.")
            return

        for i, (p, img) in enumerate(matched, 1):
            board = get_board_for_slug(p["slug"])

            # Proactively check if page is closed
            try:
                if page.is_closed():
                    raise Exception("Page closed")
            except Exception:
                logger.warning("⚠️ Browser context closed unexpectedly. Recreating...")
                try:
                    if context:
                        await context.close()
                    if pw:
                        await pw.stop()
                except Exception:
                    pass
                pw, context, page = await create_stealth_browser(headless=True)
                await ensure_logged_in(page, email, password)

            pin_id = await create_pin(page, p, img, board)

            # If failed and page is now closed, retry once
            if not pin_id:
                try:
                    closed = page.is_closed()
                except Exception:
                    closed = True

                if closed:
                    logger.warning("⚠️ Browser crashed during pin creation. Retrying once...")
                    try:
                        if context:
                            await context.close()
                        if pw:
                            await pw.stop()
                    except Exception:
                        pass
                    pw, context, page = await create_stealth_browser(headless=True)
                    await ensure_logged_in(page, email, password)
                    pin_id = await create_pin(page, p, img, board)

            if pin_id:
                update_pin_id(sb, p["id"], pin_id)
                logger.info(f"✅ Success [{i}/{len(matched)}]: {p['slug']} -> {pin_id}")
                try:
                    shutil.move(str(img), str(ARCHIVE_DIR / img.name))
                    logger.info(f"   📦 Archived image {img.name}")
                except Exception as e:
                    logger.warning(f"   ⚠️ Could not archive image {img.name}: {e}")
            else:
                logger.warning(f"⚠️ Failed [{i}/{len(matched)}]: {p['slug']}")

            if i < len(matched):
                delay = random.uniform(60, 120)
                logger.info(f"⏱️ Sleeping {delay:.1f}s...")
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
