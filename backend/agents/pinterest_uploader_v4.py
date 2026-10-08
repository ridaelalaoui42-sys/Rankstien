"""
RankStein PinRecreator — Battle-Hardened Batch Uploader
Upgraded with self-healing sessions and aggressive retry logic.
"""

import asyncio
import logging
import os
import random
import re
import shutil
from logging.handlers import RotatingFileHandler
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# ---------- Config ----------
PINTEREST_BASE = "https://es.pinterest.com"
SESSION_DIR = Path("data/sessions/pinterest_rida_v7")
DEFAULT_BOARD = "Recetas Españolas"
LOG_DIR = Path("data/logs")
LOG_DIR.mkdir(parents=True, exist_ok=True)

# Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(message)s",
    handlers=[
        RotatingFileHandler(
            str(LOG_DIR / "remaster_uploader.log"), maxBytes=5 * 1024 * 1024, backupCount=2, encoding="utf-8"
        ),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger("remaster_uploader")


class BattleHardenedUploader:
    def __init__(self, headless=True):
        self.headless = headless
        self.pw = None
        self.context = None
        self.page = None
        self.consecutive_failures = 0

    async def _cleanup_locks(self):
        """Targeted profile cleanup; keeps sibling Pinterest workers alive."""
        from backend.scripts.pinterest_batch_core import cleanup_session_artifacts

        return cleanup_session_artifacts(SESSION_DIR, "firefox")

    async def start(self):
        """Starts a fresh browser session with stealth."""
        if self.pw:
            await self.stop()

        try:
            from backend.scripts.pinterest_batch_core import (
                DEFAULT_BROWSER_MAP,
                PinterestAccount,
                create_turbo_browser,
            )

            browser = DEFAULT_BROWSER_MAP.get(
                SESSION_DIR.name, os.environ.get("PINTEREST_BROWSER", "firefox")
            )
            account = PinterestAccount(
                name=SESSION_DIR.name,
                session_dir=SESSION_DIR,
                email=os.environ.get("PINTEREST_EMAIL", ""),
                password=os.environ.get("PINTEREST_PASSWORD", ""),
                browser=browser,
            )
            self.pw, self.context, self.page = await create_turbo_browser(
                account, "battle_hardened_uploader", headless=self.headless
            )

            # Check login
            await self.page.goto(f"{PINTEREST_BASE}/", wait_until="domcontentloaded")

            is_logged_out = await self.page.query_selector(
                'button[data-test-id="simple-login-button"], button:has-text("Iniciar sesión"), button:has-text("Log in")'
            )
            if is_logged_out or "login" in self.page.url or self.page.url == f"{PINTEREST_BASE}/":
                logger.warning(f"🔑 Session invalid (URL: {self.page.url}). Attempting login...")
                await self.login()

            logger.info("🚀 Browser session established.")
            return True
        except Exception as e:
            logger.error(f"❌ Failed to launch browser: {e}")
            return False

    async def login(self):
        email = os.environ.get("PINTEREST_EMAIL")
        password = os.environ.get("PINTEREST_PASSWORD")
        if not email or not password:
            logger.error("⚠️ Pinterest credentials missing in .env")
            return False

        try:
            await self.page.goto(f"{PINTEREST_BASE}/login/", wait_until="domcontentloaded")
            await asyncio.sleep(2)

            # Dismiss overlays and wait for input visibility
            found = False
            for _ in range(12):
                email_loc = self.page.locator('input[type="email"], input#email, input[name="id"]').first
                password_loc = self.page.locator(
                    'input[type="password"], input#password, input[name="password"]'
                ).first

                if await email_loc.count() > 0 and await password_loc.count() > 0:
                    if await email_loc.is_visible() and await password_loc.is_visible():
                        found = True
                        break

                # Evaluate JS to hide Google One Tap overlays
                try:
                    await self.page.evaluate("""
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
                    btn = self.page.locator(
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
                logger.error("❌ Pinterest login form inputs not located.")
                return False

            # Fill credentials using human type
            await self.human_type('input[type="email"], input#email, input[name="id"]', email)
            await self.human_type('input[type="password"], input#password, input[name="password"]', password)

            # Click submit
            submit_clicked = False
            for selector in [
                'button[type="submit"]',
                'button:has-text("Log in")',
                'button:has-text("Iniciar sesión")',
            ]:
                try:
                    btn = self.page.locator(selector).first
                    if await btn.count() > 0 and await btn.is_visible():
                        await btn.click(force=True, timeout=3000)
                        submit_clicked = True
                        break
                except Exception:
                    continue

            if not submit_clicked:
                await self.page.keyboard.press("Enter")

            await self.page.wait_for_timeout(10000)
            logger.info("✅ Login attempt completed.")
            return True
        except Exception as e:
            logger.error(f"❌ Login failed: {e}")
            return False

    async def stop(self):
        try:
            if self.context:
                await self.context.close()
            if self.pw:
                await self.pw.stop()
        except:
            pass
        self.pw = self.context = self.page = None

    async def human_type(self, selector_or_el, text):
        try:
            if isinstance(selector_or_el, str):
                el = await self.page.wait_for_selector(selector_or_el, timeout=10000)
            else:
                el = selector_or_el

            await el.click(force=True)
            await asyncio.sleep(0.5)
            await self.page.keyboard.down("Control")
            await self.page.keyboard.press("a")
            await self.page.keyboard.up("Control")
            await self.page.keyboard.press("Backspace")
            for char in text:
                await self.page.keyboard.type(char)
                await asyncio.sleep(random.uniform(0.02, 0.08))
            return True
        except:
            return False

    async def upload_remastered_pin(self, img_path, title, link, description, alt_text="", retry=2):
        """Uploads a pin with aggressive retries and full metadata."""
        if not self.page or self.page.is_closed():
            await self.start()

        from backend.scripts.pinterest_batch_core import BrowserSessionLost, create_pin_from_fields

        try:
            pin_id = await create_pin_from_fields(
                self.page,
                img_path,
                title,
                link,
                description,
                DEFAULT_BOARD,
                "battle_hardened_uploader",
            )
            if pin_id:
                self.consecutive_failures = 0
                return pin_id
            raise RuntimeError("shared Pinterest uploader returned no pin id")
        except Exception as exc:
            logger.error(f"   âš ï¸ Upload failed: {exc}")
            self.consecutive_failures += 1
            if retry > 0:
                logger.info(f"   â™»ï¸ Retrying with a fresh shared session... ({retry} attempts left)")
                await self.start()
                return await self.upload_remastered_pin(
                    img_path, title, link, description, alt_text, retry - 1
                )
            if isinstance(exc, BrowserSessionLost):
                await self.stop()
            return None

        temp_img = Path(f"data/upload_remaster_{random.randint(1000, 9999)}.jpg")
        shutil.copy(str(img_path), str(temp_img))

        try:
            logger.info(f"📌 Attempting upload: {title[:30]}...")
            await self.page.goto(
                f"{PINTEREST_BASE}/pin-creation-tool/", wait_until="domcontentloaded", timeout=60000
            )
            await asyncio.sleep(6)

            # 1. File Drop
            f_inp = await self.page.wait_for_selector('input[type="file"]', timeout=20000)
            if not f_inp:
                raise Exception("File input not found")
            await f_inp.set_input_files(str(temp_img))
            await asyncio.sleep(5)

            # 2. Fill Data
            # Title
            await self.human_type(
                'textarea[placeholder*="título" i], [data-test-id="pin-draft-title"] textarea', title[:100]
            )
            # Desc
            await self.human_type(
                'textarea[placeholder*="descripción" i], [data-test-id="pin-draft-description"] textarea',
                description[:500],
            )
            # Alt Text
            if alt_text:
                alt_btn = await self.page.query_selector(
                    'button:has-text("Add alt text"), button:has-text("Añadir texto alternativo")'
                )
                if alt_btn:
                    await alt_btn.click()
                    await asyncio.sleep(1)
                    await self.page.fill(
                        'textarea[placeholder*="Explain" i], textarea[placeholder*="explica" i]',
                        alt_text[:500],
                    )
            # Link
            await self.human_type(
                'input[placeholder*="enlace" i], [data-test-id="pin-draft-link"] input', link
            )

            # 3. Board Selection
            try:
                b_btn = await self.page.wait_for_selector(
                    '[data-test-id="board-dropdown-select-button"]', timeout=5000
                )
                await b_btn.click(force=True)
                await asyncio.sleep(2)
                board_item = await self.page.query_selector(
                    f'div[role="option"]:has-text("{DEFAULT_BOARD}"), div[data-test-id="board-row"]:has-text("{DEFAULT_BOARD}")'
                )
                if board_item:
                    await board_item.click(force=True)
                else:
                    first = await self.page.query_selector('div[role="option"]')
                    if first:
                        await first.click(force=True)
            except:
                pass

            await asyncio.sleep(4)

            # 4. Final Publish
            published_id = None
            pub_btn = await self.page.query_selector(
                'button[data-test-id="create-pin-save-button"], button:has-text("Publicar")'
            )
            if pub_btn:
                await pub_btn.click(force=True)
                logger.info("   🚀 Publish button clicked.")
                for _ in range(25):
                    await asyncio.sleep(1)
                    if "/pin/" in self.page.url:
                        published_id = re.search(r"/pin/(\d+)", self.page.url).group(1)
                        break

            if published_id:
                self.consecutive_failures = 0
                return published_id

            # Fallback for "Success but no redirect"
            if await self.page.query_selector(':has-text("Tu Pin se ha guardado"), :has-text("Ver tu Pin")'):
                return "SUCCESS_HIDDEN_ID"

            raise Exception("Publish confirmation not detected")

        except Exception as e:
            logger.error(f"   ⚠️ Upload failed: {e}")
            self.consecutive_failures += 1
            if retry > 0:
                logger.info(f"   ♻️ Retrying... ({retry} attempts left)")
                await self.start()
                return await self.upload_remastered_pin(
                    img_path, title, link, description, alt_text, retry - 1
                )
            return None
        finally:
            if temp_img.exists():
                temp_img.unlink()


async def deploy_remastered_campaign(article_slug, title_prefix, remastered_list):
    """Orchestrates the hardened batch run."""
    uploader = BattleHardenedUploader(headless=True)
    if not await uploader.start():
        return []

    live_url = f"https://recetadolce.com/{article_slug}"
    results = []

    for i, item in enumerate(remastered_list):
        if i > 0 and i % 5 == 0:
            logger.info("🔄 Refreshing browser session for stability...")
            await uploader.start()

        res = await uploader.upload_remastered_pin(
            item["remastered_path"],
            f"{title_prefix} - {random.choice(['Gourmet', 'Fácil', 'Trend', 'Premium', 'Viral'])}",
            live_url,
            f"Descubre la mejor receta de {title_prefix}. Una guía completa paso a paso con los mejores trucos de cocina. #RecetaDolce #Cocina #Gourmet",
            alt_text=f"Receta de {title_prefix} - Fotografía gastronómica de alta calidad.",
        )

        if res:
            results.append({"pin_id": res, "source": item["original_pin_id"]})
            logger.info(f"   ✅ Pin {i + 1}/{len(remastered_list)}: {res}")

        # Anti-ban sleep
        await asyncio.sleep(random.uniform(45, 95))

    await uploader.stop()
    return results


# For the Daily Engine to use
BatchPinUploader = BattleHardenedUploader
