import asyncio
import os
from pathlib import Path

from dotenv import load_dotenv
from playwright.async_api import async_playwright

# Load .env
load_dotenv()


async def login_account(name, email, password, session_dir):
    print(f"--- Logging in: {name} ({email}) ---")
    async with async_playwright() as p:
        browser_type = p.chromium

        # Cleanup locks
        for lock in ["parent.lock", "singletonlock", "lock"]:
            lp = Path(session_dir) / lock
            if lp.exists():
                try:
                    lp.unlink()
                except:
                    pass

        context = await browser_type.launch_persistent_context(
            user_data_dir=str(session_dir), headless=True, viewport={"width": 1280, "height": 800}
        )
        page = context.pages[0] if context.pages else await context.new_page()

        try:
            await page.goto("https://www.pinterest.com/login/", timeout=60000)
            await asyncio.sleep(5)

            # Check if already logged in
            if "login" not in page.url and "pinterest.com" in page.url:
                print(f"Already logged in as {name}")
                await context.close()
                return True

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
                print(f"[ERROR] Login form inputs not located for {name}")
                await page.screenshot(path=f"data/login_no_inputs_{name}.png")
                await context.close()
                return False

            print("Filling credentials...")
            await page.fill('input[type="email"], input#email, input[name="id"]', email)
            await asyncio.sleep(1)
            await page.fill('input[type="password"], input#password, input[name="password"]', password)
            await asyncio.sleep(1)

            print("Submitting (Click + Enter)...")
            try:
                await page.click('button[type="submit"]', timeout=5000)
            except:
                await page.keyboard.press("Enter")

            print("Waiting for redirection (30s max)...")
            for _ in range(30):
                await asyncio.sleep(1)
                if "login" not in page.url and "pinterest.com" in page.url:
                    print(f"Login SUCCESS for {name}")
                    await context.close()
                    return True
                # Check for "Confirmation" or "Two-factor"
                if "two-factor" in page.url or "confirm" in page.url:
                    print(f"Login BLOCKED by security check for {name}: {page.url}")
                    await page.screenshot(path=f"data/login_blocked_{name}.png")
                    break

            print(f"Login check finished for {name}. Final URL: {page.url}")
            await page.screenshot(path=f"data/login_final_{name}.png")
            await context.close()
            return "login" not in page.url

        except Exception as e:
            print(f"Error during login for {name}: {e}")
            await context.close()
            return False


async def main():
    import json

    raw_accounts = os.environ.get("PINTEREST_ACCOUNTS", "")
    if not raw_accounts:
        print("PINTEREST_ACCOUNTS not found in env")
        return

    try:
        # robust parse
        if (raw_accounts.startswith("'") and raw_accounts.endswith("'")) or (
            raw_accounts.startswith('"') and raw_accounts.endswith('"')
        ):
            raw_accounts = raw_accounts[1:-1].strip()
        raw_accounts = raw_accounts.replace('\\"', '"')

        parsed = json.loads(raw_accounts)
    except Exception as e:
        print(f"Failed to parse PINTEREST_ACCOUNTS: {e}")
        return

    password = os.environ.get("PINTEREST_PASSWORD")

    for entry in parsed:
        name = entry.get("name")
        email = entry.get("email")
        pwd = entry.get("password") or password
        session = entry.get("session") or entry.get("session_dir")

        if not session:
            print(f"No session path for {name}")
            continue

        session_path = Path("data/sessions") / session

        if not pwd:
            print(f"No password found for {name}")
            continue

        # Ensure session dir exists
        session_path.mkdir(parents=True, exist_ok=True)
        await login_account(name, email, pwd, session_path)


if __name__ == "__main__":
    asyncio.run(main())
