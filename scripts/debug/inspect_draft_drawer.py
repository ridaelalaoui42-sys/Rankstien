import asyncio
import json
from playwright.async_api import async_playwright

async def inspect():
    async with async_playwright() as p:
        b = await p.chromium.launch_persistent_context('data/sessions/pinterest_rida_v7', headless=True)
        page = await b.new_page()
        await page.goto('https://www.pinterest.com/pin-creation-tool/', timeout=45000)
        await asyncio.sleep(4)
        buttons = await page.evaluate("""() => {
            return Array.from(document.querySelectorAll('button, [role="button"], [data-test-id]')).map(el => ({
                tag: el.tagName,
                text: (el.innerText || el.textContent || '').trim().slice(0, 50),
                testid: el.getAttribute('data-test-id') || '',
                aria: el.getAttribute('aria-label') || '',
                classes: String(el.className || '').slice(0, 50)
            })).filter(b => /draft|borrador|nav|toggle|side|collapse|expand|50/i.test(JSON.stringify(b)));
        }""")
        print(json.dumps(buttons, indent=2))
        await b.close()

if __name__ == "__main__":
    asyncio.run(inspect())
