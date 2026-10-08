import asyncio
import os
import random
import re
import shutil
import sys
import time
import unicodedata
from pathlib import Path

from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv(override=False)

PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from rankstein.domain import get_registry

# ---------- Config ----------
# Config is now dynamic via DomainRegistry
PINTEREST_BASE = "https://es.pinterest.com"

# Paths
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
MEDIA_DIR = PROJECT_ROOT / "data" / "media"
SESSION_DIR = PROJECT_ROOT / "data" / "sessions" / "pinterest_rida_v7"
TEMP_IMG = PROJECT_ROOT / "data" / "upload_temp.jpg"

# EEAT Citations
EEAT_CITATIONS = {
    "seafood": "Cumpliendo con las normativas de AESAN y EFSA para la seguridad alimentaria en mariscos.",
    "meat": "Siguiendo los estándares del Codex Alimentarius para el manejo seguro de carnes.",
    "eggs": "Basado en el RD 1021/2022 para la higiene de preparaciones con huevo.",
}


def get_supabase(domain):
    try:
        from supabase import create_client

        return create_client(domain.supabase_url, domain.supabase_service_role_key.get_secret_value())
    except Exception as e:
        print(f"❌ Failed to connect to Supabase for {domain.handle}: {e}")
        sys.exit(1)


def fetch_unpinned_posts(sb, limit=None):
    for attempt in range(3):
        try:
            res = (
                sb.table("posts")
                .select("id, title, slug, excerpt, pinterest_pin_id")
                .eq("status", "published")
                .order("created_at", desc=True)
                .execute()
            )
            unpinned = [
                p for p in res.data if not p.get("pinterest_pin_id") or len(str(p["pinterest_pin_id"])) < 15
            ]
            return unpinned[:limit] if limit else unpinned
        except Exception as e:
            print(f"   ⚠️  Supabase fetch attempt {attempt + 1} failed: {e}")
            time.sleep(5)
    return []


def update_pin_id(sb, post_id, pin_id):
    try:
        sb.table("posts").update({"pinterest_pin_id": str(pin_id)}).eq("id", post_id).execute()
        print(f"   ✅ Saved pin ID {pin_id}")
    except:
        pass


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
    all_files = list(MEDIA_DIR.glob("pin_*.jpg")) + list(MEDIA_DIR.glob("pin_*.png"))
    # print(f" DEBUG: Matching slug {slug} against {len(all_files)} files")
    for f in all_files:
        n_f = normalize(f.name)
        score = sum(1 for kw in keywords if kw in n_f)
        if n_s in n_f:
            score += 10
        if score > max_score:
            max_score = score
            best_f = f

    if max_score < 2:
        # print(f" ⚠️  Low match score ({max_score}) for {slug}. Keywords: {keywords}")
        pass

    return best_f if max_score >= 2 else None


def build_pin_description(post):
    title = post["title"]
    slug = post["slug"]
    excerpt = post.get("excerpt", "") or ""
    desc_parts = [excerpt[:200] if excerpt else f"Descubre cómo preparar {title} paso a paso."]
    if any(k in slug for k in ["marisco", "pulpo", "sepia", "bogavante", "gambas"]):
        desc_parts.append(f"\n🛡️ {EEAT_CITATIONS['seafood']}")
    elif any(k in slug for k in ["pollo", "carne", "jamon", "cocido"]):
        desc_parts.append(f"\n🛡️ {EEAT_CITATIONS['meat']}")
    elif any(k in slug for k in ["tortilla", "huevo", "mayonesa"]):
        desc_parts.append(f"\n🛡️ {EEAT_CITATIONS['eggs']}")
    desc_parts.append("\n\n🔗 Receta completa en RecetaDolce.com")
    desc_parts.append("\n#RecetaDolce #CocinaEspañola #Recetas")
    return "".join(desc_parts)[:500]


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


async def gemini_heal_selector(page, target_description: str) -> str:
    js_code = """
    () => {
        const elements = [];
        const selectors = ['input', 'textarea', 'select', 'button', 'a', '[role="button"]', '[role="textbox"]', '[role="checkbox"]', '[role="radio"]', '[contenteditable="true"]'];
        
        for (const sel of selectors) {
            try {
                const els = document.querySelectorAll(sel);
                for (const el of els) {
                    const rect = el.getBoundingClientRect();
                    if (rect.width > 0 && rect.height > 0) {
                        const style = window.getComputedStyle(el);
                        if (style.display !== 'none' && style.visibility !== 'hidden' && style.opacity !== '0') {
                            elements.push({
                                tag: el.tagName.toLowerCase(),
                                type: el.type || '',
                                name: el.name || '',
                                id: el.id || '',
                                className: el.className || '',
                                placeholder: el.placeholder || '',
                                ariaLabel: el.getAttribute('aria-label') || '',
                                text: (el.innerText || '').substring(0, 50),
                                selector: ''
                            });
                        }
                    }
                }
            } catch(e) {}
        }
        
        // Generate unique selectors
        for (let i = 0; i < elements.length; i++) {
            const el = elements[i];
            if (el.id) {
                elements[i].selector = `#${el.id}`;
            } else if (el.name) {
                elements[i].selector = `${el.tag}[name="${el.name}"]`;
            } else if (el.className && typeof el.className === 'string') {
                const cls = el.className.split(' ')[0];
                if (cls) elements[i].selector = `${el.tag}.${cls}`;
            }
        }
        
        return JSON.stringify(elements.slice(0, 50));
    }
    """
    try:
        dom_context = await page.evaluate(js_code)
    except Exception as e:
        print(f"   ⚠️  Failed to extract elements for self-healing: {e}")
        return ""

    if not dom_context or dom_context == "[]":
        return ""

    prompt = f"""You are an expert Playwright automation engineer.
The standard locator for "{target_description}" on Pinterest just failed.

Here is a JSON list of all visible interactive elements currently on the page:
```json
{dom_context}
```

Identify the single element that most likely represents "{target_description}".
Return ONLY a valid Playwright CSS selector string that will uniquely match this element.
DO NOT wrap the response in code blocks, quotes, or JSON. Just return the raw selector string.
Example valid responses:
input[name="title"]
div[role="textbox"]
textarea[id="pin-draft-alttext"]
"""
    models_to_try = [
        "gemini-3.1-pro-preview",
        "gemini-3.1-flash-lite-preview",
        "gemini-3-pro-preview",
        "gemini-3-flash-preview",
    ]

    for model in models_to_try:
        try:
            import subprocess

            print(f"   🤖 Invoking Gemini CLI ({model}) self-healing for: {target_description}...")

            # Let Gemini CLI inherit the configured API key for selector recovery.
            env = os.environ.copy()
            if env.get("GEMINI_API_KEY") and not env.get("GOOGLE_API_KEY"):
                env["GOOGLE_API_KEY"] = env["GEMINI_API_KEY"]
            elif env.get("GOOGLE_API_KEY") and not env.get("GEMINI_API_KEY"):
                env["GEMINI_API_KEY"] = env["GOOGLE_API_KEY"]

            result = subprocess.run(
                ["gemini", "-p", prompt, "--model", model],
                capture_output=True,
                text=True,
                check=True,
                env=env,
            )
            selector = result.stdout.strip().strip("`").strip('"').strip("'")
            if "\\n" in selector or len(selector) > 150:
                print(f"   ⚠️  Gemini returned invalid selector format: {selector[:50]}...")
                continue
            print(f"   ✨ Gemini proposed new selector: {selector}")
            return selector
        except Exception as e:
            if "ModelNotFoundError" in str(e) or "404" in str(e):
                print(f"   ⚠️  {model} not found. Trying next...")
                continue
            print(f"   ⚠️  Gemini self-healing failed with {model}: {e}")
            continue

    return ""


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
    return await create_turbo_browser(account, "pinterest_uploader_v4", headless=headless)


async def ensure_logged_in(page, email, password):
    print("🔐 Checking session...")
    try:
        await page.goto(f"{PINTEREST_BASE}/", wait_until="domcontentloaded")
        await asyncio.sleep(5)
        if await page.query_selector('[data-test-id="header-profile"], [data-test-id="header-avatar"]'):
            print("✅ Session valid.")
            return True

        print("🔑 Not logged in. Attempting login flow...")
        await page.goto(f"{PINTEREST_BASE}/login/", wait_until="domcontentloaded")
        await asyncio.sleep(3)

        # Dismiss overlays and wait for input visibility
        found = False
        for _ in range(12):
            email_loc = page.locator('input[type="email"], input#email, input[name="id"]').first
            password_loc = page.locator(
                'input[type="password"], input#password, input[name="password"]'
            ).first

            if await email_loc.count() > 0 and await password_loc.count() > 0:
                if await email_loc.is_visible() and await password_loc.is_visible():
                    found = True
                    break

            # Evaluate JS to hide Google One Tap overlays
            try:
                await page.evaluate("""
                    () => {
                        const selectors = [
                            '#credential_picker_container',
                            '.L5Fo6c-PQbLGe',
                            '[title="Sign in with Google Dialog"]'
                        ];
                        selectors.forEach(sel => {
                            const el = document.querySelector(sel);
                            if (el) el.style.display = 'none';
                        });
                    }
                """)
            except Exception:
                pass

            # Try clicking Log in button overlay if visible
            try:
                btn = page.locator(
                    'div[data-test-id="login-button"], button:has-text("Log in"), button:has-text("Iniciar sesión"), a:has-text("Log in"), a:has-text("Iniciar sesión")'
                ).first
                if await btn.count() > 0 and await btn.is_visible():
                    await btn.click(timeout=1000)
                    await asyncio.sleep(1)
                    continue
            except Exception:
                pass

            await asyncio.sleep(1)

        if not found:
            print("❌ Pinterest login form inputs not located.")
            await page.screenshot(path="data/debug_login_fail_batch.jpg")
            return False

        await human_type(page, 'input#email, input[name="id"], input[type="email"]', email)
        await human_type(page, "input#password, input[name='password']", password)

        # Click submit
        submit_clicked = False
        for selector in [
            'button[type="submit"]',
            'button:has-text("Log in")',
            'button:has-text("Iniciar sesión")',
        ]:
            try:
                btn = page.locator(selector).first
                if await btn.count() > 0 and await btn.is_visible():
                    await btn.click(force=True, timeout=3000)
                    submit_clicked = True
                    break
            except Exception:
                continue

        if not submit_clicked:
            await page.keyboard.press("Enter")

        await asyncio.sleep(10)
        success = (
            await page.query_selector('[data-test-id="header-profile"], [data-test-id="header-avatar"]')
            is not None
        )
        if success:
            print("✅ Login successful.")
        else:
            print("❌ Login failed.")
            await page.screenshot(path="data/debug_login_fail_batch.jpg")
        return success
    except Exception as e:
        print(f"Login error: {e}")
    return False


async def create_pin(page, post, image_path, board_name, domain):
    title = post["title"]
    # Dynamic base URL from domain registry
    base_url = f"https://{domain.domain}" if not domain.domain.startswith("http") else domain.domain
    url = f"{base_url}/{post['slug']}"
    desc = build_pin_description(post)
    from pinterest_batch_core import create_pin_from_fields

    return await create_pin_from_fields(
        page,
        image_path,
        title,
        url,
        desc,
        board_name,
        f"pinterest_uploader_v4-{domain.handle}",
    )
    print(f"\n📌 Pinning: {title[:50]}...")

    # Shorten path to avoid WinError 3
    shutil.copy(str(image_path), str(TEMP_IMG))

    try:
        await page.goto(f"{PINTEREST_BASE}/pin-creation-tool/", wait_until="domcontentloaded")
        await asyncio.sleep(12)
        await page.keyboard.press("Escape")

        # CLEAR DRAFTS TO PREVENT LIMITS
        bulk = await page.query_selector('input[id="storyboard-drafts-sidebar-bulk-select-checkbox"]')
        if bulk:
            await bulk.evaluate("el => el.click()")
            await asyncio.sleep(1)
            for sel in [
                'button[aria-label="Delete"]',
                'button[aria-label="Eliminar"]',
                'button[aria-label*="drafts"]',
                '[data-test-id="delete-draft-button"]',
            ]:
                trash = await page.query_selector(sel)
                if trash and await trash.is_visible():
                    await trash.click(force=True)
                    await asyncio.sleep(1)
                    confirm = await page.query_selector('div[role="dialog"] button:last-child')
                    if confirm:
                        await confirm.click(force=True)
                    await asyncio.sleep(4)
                    print("   🧹 Cleared old drafts")
                    break

        f_inp = await page.wait_for_selector('input[type="file"]', timeout=30000)
        await f_inp.set_input_files(str(TEMP_IMG))
        print("   📤 Image uploaded")
        await asyncio.sleep(12)

        # Title
        title_selectors = [
            'input[id="storyboard-selector-title"]',
            'textarea[id*="pin-draft-title"]',
            'input[placeholder*="título"]',
            'input[placeholder*="Title"]',
            '[data-test-id="pin-builder-draft-title"]',
        ]
        title_el = None
        for sel in title_selectors:
            title_el = await page.query_selector(sel)
            if title_el and await title_el.is_visible():
                break

        if not title_el:
            healed_sel = await gemini_heal_selector(page, "the pin title input field")
            if healed_sel:
                title_el = await page.query_selector(healed_sel)

        try:
            if title_el:
                await human_type(page, title_el, title[:100])
                print(f"   🏷️ Title filled: {title[:30]}...")
            else:
                print("   ⚠️  Title field not found")
        except Exception as e:
            print(f"   ⚠️  Title error: {e}")

        # Description
        desc_selectors = [
            '[aria-label="Add a detailed description"]',
            ".public-DraftEditor-content",
            'div[role="textbox"]',
            'textarea[id*="description"]',
            '[placeholder*="consiste"]',
            '[placeholder*="Tell us"]',
            '[data-test-id="pin-builder-draft-description"]',
        ]
        desc_el = None
        for sel in desc_selectors:
            desc_el = await page.query_selector(sel)
            if desc_el and await desc_el.is_visible():
                break

        if not desc_el:
            healed_sel = await gemini_heal_selector(page, "the pin description input field")
            if healed_sel:
                desc_el = await page.query_selector(healed_sel)

        try:
            if desc_el:
                await human_type(page, desc_el, desc[:500])
                print("   📝 Description filled")
            else:
                print("   ⚠️  Description field not found")
        except Exception as e:
            print(f"   ⚠️  Desc error: {e}")

        # Link
        link_selectors = [
            'input[id="WebsiteField"]',
            'input[id*="link"]',
            'input[placeholder*="link"]',
            '[placeholder*="destination"]',
            '[placeholder*="destino"]',
            '[data-test-id="pin-builder-draft-link"]',
        ]
        link_el = None
        for sel in link_selectors:
            link_el = await page.query_selector(sel)
            if link_el and await link_el.is_visible():
                break

        if not link_el:
            healed_sel = await gemini_heal_selector(page, "the destination link input field")
            if healed_sel:
                link_el = await page.query_selector(healed_sel)

        try:
            if link_el:
                await human_type(page, link_el, url)
                await page.keyboard.press("Enter")
                await asyncio.sleep(1)
                print(f"   🔗 Link filled: {url[:40]}...")
            else:
                print("   ⚠️  Link field not found")
        except Exception as e:
            print(f"   ⚠️  Link error: {e}")

        # Board Selection
        try:
            b_btn = await page.wait_for_selector(
                '[data-test-id="board-dropdown-select-button"]', timeout=10000
            )
            await b_btn.click(force=True)
            await asyncio.sleep(3)
            board_item = await page.query_selector(
                f'div[role="option"]:has-text("{board_name}"), div[data-test-id="board-row"]:has-text("{board_name}")'
            )
            if board_item:
                await board_item.click(force=True)
            else:
                first_option = await page.query_selector('div[role="option"]')
                if first_option:
                    await first_option.click(force=True)
                else:
                    await page.keyboard.press("Escape")
        except:
            pass

        await asyncio.sleep(5)
        # Diagnostic screenshot before publish
        await page.screenshot(path=f"data/pre_publish_{post['slug'][:20]}.png")

        publish_clicked = False
        # Broader publish selectors
        publish_selectors = [
            'button[data-test-id="board-dropdown-save-button"]',
            'button[data-test-id="create-pin-save-button"]',
            'button:has-text("Publish")',
            'button:has-text("Publicar")',
            'button:has-text("Guardar")',
            '[role="button"]:has-text("Publish")',
            '[role="button"]:has-text("Publicar")',
        ]
        for sel in publish_selectors:
            btn = await page.query_selector(sel)
            if btn and await btn.is_visible():
                await btn.click(force=True)
                print("   🚀 Clicked publish")
                publish_clicked = True
                break

        if not publish_clicked:
            healed_sel = await gemini_heal_selector(page, "the publish or save pin button")
            if healed_sel:
                btn = await page.query_selector(healed_sel)
                if btn and await btn.is_visible():
                    await btn.click(force=True)
                    print("   🚀 Clicked publish (via self-healing)")
                    publish_clicked = True

        if not publish_clicked:
            print("   ⚠️  Publish button not found or not visible.")
            await page.screenshot(path=f"data/debug_publish_fail_{post['slug'][:30]}.png")
            return False

        await asyncio.sleep(5)
        return True
    except Exception as e:
        print(f"   ❌ Error: {e}")
    finally:
        if TEMP_IMG.exists():
            os.remove(str(TEMP_IMG))
    return False


async def main():
    # Handle domain selection
    domain_handle = sys.argv[1] if len(sys.argv) > 1 else None
    registry = get_registry()
    try:
        domain = registry.get(domain_handle)
    except KeyError as e:
        print(f"❌ {e}")
        return

    print(f"🚀 Starting Pinterest Uploader for domain: {domain.handle} ({domain.domain})")

    sb = get_supabase(domain)
    posts = fetch_unpinned_posts(sb)

    # Optional filtering for specific slugs
    target_slugs = [
        "bizcocho-en-taza-mug-cake-de-zanahoria",
        "churros-en-freidora-de-aire-el-truco-definitivo-para-que-queden-crujientes",
        "bowl-tofu-marinado-algas-wakame",
        "ensalada-de-lentejas-crujientes-y-tzatziki",
        "ensalada-espinacas-fresas-nueces-pecanas-gourmet-2026",
        "tabule-coliflor-menta-saludable",
        "tarta-tatin-de-dulce-de-leche",
        "tiramisu-de-limon-y-albahaca",
    ]
    # If target_slugs is provided, filter. Otherwise process all unpinned.
    if target_slugs:
        posts = [p for p in posts if any(s in p["slug"] for s in target_slugs)]

    matched = [
        (p, find_local_image_for_slug(p["slug"])) for p in posts if find_local_image_for_slug(p["slug"])
    ]

    if not matched:
        print(f"✅ No targeted pins found for {domain.handle}. Everything looks live.")
        return

    print(f"Matched {len(matched)} targeted pins. Starting upload sequence...")

    # Default board from domain config
    default_board = domain.boards_default.get("_default", "Recetas Españolas")

    for i, (p, img) in enumerate(matched, 1):
        print(f"\n--- Processing Pin {i}/{len(matched)}: {p['slug']} ---")
        pw, context, page = await create_stealth_browser(headless=True)
        try:
            email = domain.pinterest_email
            password = domain.pinterest_password.get_secret_value()

            if await ensure_logged_in(page, email, password):
                pin_id = await create_pin(page, p, img, default_board, domain)
                if pin_id:
                    print(f"   ✅ Upload successful for {p['slug']}")
                    # Update Supabase
                    update_pin_id(sb, p["id"], pin_id)
                    new_name = MEDIA_DIR / f"uploaded_{img.name}"
                    img.rename(new_name)
                else:
                    print(f"   ❌ Failed to upload Pin for {p['slug']}")
            else:
                print(f"   ❌ Login failed for {email}")
        except Exception as e:
            print(f"   ❌ Critical loop error: {e}")
        finally:
            await context.close()
            await pw.stop()

        if i < len(matched):
            delay = random.uniform(60, 120)
            print(f"   ⏱️  Cooling down. Next pin in {delay:.1f}s...")
            await asyncio.sleep(delay)


if __name__ == "__main__":
    asyncio.run(main())
