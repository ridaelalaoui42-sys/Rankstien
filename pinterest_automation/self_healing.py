"""
RankStein Pinterest Automation — Unified Self-Healing Engine
DOM analysis + LLM-powered selector recovery with persistent caching.
"""

import hashlib
import json
import logging
from datetime import UTC, datetime

from playwright.async_api import Page

from .config import HEALING_CACHE_DIR, get_config

logger = logging.getLogger("rankstein.healing")

HEALING_CACHE_FILE = HEALING_CACHE_DIR / "selector_cache.json"

# Fallback selector strategies organized by target type
FALLBACK_STRATEGIES: dict[str, list[str]] = {
    "title": [
        'input[id*="title" i]',
        'input[name*="title" i]',
        'input[placeholder*="title" i]',
        'input[placeholder*="título" i]',
        'h1[contenteditable="true"]',
        'textarea[id*="title" i]',
        'div[contenteditable="true"][role="textbox"]',
    ],
    "description": [
        ".public-DraftEditor-content",
        'div[role="textbox"]',
        'div[contenteditable="true"]',
        'textarea[name*="description" i]',
        'textarea[placeholder*="description" i]',
        'textarea[placeholder*="descripción" i]',
    ],
    "alt_text": [
        'textarea[id*="alt" i]',
        'textarea[placeholder*="alt" i]',
        'input[placeholder*="alt" i]',
        'textarea[aria-label*="alt" i]',
    ],
    "link": [
        'input[id*="link" i]',
        'input[name*="link" i]',
        'input[placeholder*="link" i]',
        'input[placeholder*="website" i]',
        'input[placeholder*="enlace" i]',
    ],
    "publish": [
        'button:has-text("Publish")',
        'button:has-text("Publicar")',
        'button:has-text("Save")',
        'button:has-text("Guardar")',
        'button[type="submit"]',
        '[role="button"]:has-text("Publish")',
        '[role="button"]:has-text("Publicar")',
    ],
    "board": [
        'button[data-test-id*="board" i]',
        'div[data-test-id*="board-selector" i] button',
        'button[aria-label*="board" i]',
        'button[aria-label*="tablero" i]',
    ],
    "more_options": [
        'button:has-text("More options")',
        'div:has-text("More options")',
        'button:has-text("Más opciones")',
        'div:has-text("Más opciones")',
    ],
}


def _dom_hash(dom_snippet: str) -> str:
    return hashlib.sha256(dom_snippet.encode("utf-8")).hexdigest()[:16]


class HealingCache:
    """Persistent cache for healed selectors with TTL."""

    def __init__(self):
        self.ttl_hours = get_config().self_healing.cache_ttl_hours
        self._cache: dict[str, dict] = {}
        self._load()

    def _load(self):
        if HEALING_CACHE_FILE.exists():
            try:
                self._cache = json.loads(HEALING_CACHE_FILE.read_text(encoding="utf-8"))
                # Expire old entries
                now = datetime.now(UTC).timestamp()
                self._cache = {
                    k: v for k, v in self._cache.items() if now - v.get("ts", 0) < self.ttl_hours * 3600
                }
            except Exception as e:
                logger.warning(f"Failed to load healing cache: {e}")

    def _save(self):
        try:
            import os

            tmp = HEALING_CACHE_FILE.with_suffix(".tmp")
            tmp.parent.mkdir(parents=True, exist_ok=True)
            tmp.write_text(
                json.dumps(self._cache, indent=2, ensure_ascii=False), encoding="utf-8"
            )
            # Atomic rename – on Windows NTFS this replaces atomically if target exists
            os.replace(tmp, HEALING_CACHE_FILE)
        except Exception as e:
            logger.warning(f"Failed to save healing cache: {e}")

    def get(self, page_context: str, target: str) -> str | None:
        key = f"{page_context}::{target}"
        entry = self._cache.get(key)
        if entry is None:
            return None
        now = datetime.now(UTC).timestamp()
        if now - entry["ts"] > self.ttl_hours * 3600:
            del self._cache[key]
            return None
        logger.debug(f"Healing cache hit for '{target}': {entry['selector']}")
        return entry["selector"]

    def set(self, page_context: str, target: str, selector: str):
        key = f"{page_context}::{target}"
        self._cache[key] = {
            "selector": selector,
            "ts": datetime.now(UTC).timestamp(),
            "uses": self._cache.get(key, {}).get("uses", 0) + 1,
        }
        self._save()

    def get_stats(self) -> dict:
        return {
            "cached_selectors": len(self._cache),
            "cache_file": str(HEALING_CACHE_FILE),
        }


_healing_cache: HealingCache | None = None


def get_healing_cache() -> HealingCache:
    global _healing_cache
    if _healing_cache is None:
        _healing_cache = HealingCache()
    return _healing_cache


async def extract_interactive_elements(page: Page, limit: int = 50) -> list[dict]:
    """Extract visible interactive elements from the page."""
    js_code = """
    (limitArg) => {
        const elements = [];
        const selectors = [
            'input', 'textarea', 'select', 'button', 'a',
            '[role="button"]', '[role="textbox"]', '[role="combobox"]',
            '[role="checkbox"]', '[role="radio"]', '[contenteditable="true"]'
        ];
        const seen = new Set();

        for (const sel of selectors) {
            try {
                const els = document.querySelectorAll(sel);
                for (const el of els) {
                    const rect = el.getBoundingClientRect();
                    if (rect.width > 0 && rect.height > 0) {
                        const style = window.getComputedStyle(el);
                        if (style.display !== 'none' && style.visibility !== 'hidden' && style.opacity !== '0') {
                            const key = el.tagName + (el.id || '') + (el.className || '');
                            if (seen.has(key)) continue;
                            seen.add(key);

                            let selector = '';
                            if (el.id) {
                                selector = `#${el.id}`;
                            } else if (el.name) {
                                selector = `${el.tagName.toLowerCase()}[name="${el.name}"]`;
                            } else if (el.className && typeof el.className === 'string') {
                                const cls = el.className.split(' ').filter(c => c).slice(0, 2).join('.');
                                if (cls) selector = `${el.tagName.toLowerCase()}.${cls}`;
                            }

                            elements.push({
                                tag: el.tagName.toLowerCase(),
                                type: el.type || '',
                                name: el.name || '',
                                id: el.id || '',
                                className: (el.className || '').split(' ').slice(0, 3).join(' '),
                                placeholder: el.placeholder || '',
                                ariaLabel: el.getAttribute('aria-label') || '',
                                text: (el.innerText || '').substring(0, 80).replace(/\\s+/g, ' '),
                                selector: selector,
                                rect: {x: rect.x, y: rect.y, w: rect.width, h: rect.height}
                            });
                        }
                    }
                }
            } catch(e) {}
        }
        return elements.slice(0, limitArg);
    }
    """
    try:
        result = await page.evaluate(js_code, limit)
        return result
    except Exception as e:
        logger.warning(f"Failed to extract interactive elements: {e}")
        return []


async def get_accessibility_snapshot(page: Page) -> list[dict]:
    """
    Get a simplified accessibility tree snapshot.
    Uses the native Chrome accessibility tree if available, otherwise falls back to basic extraction.
    """
    try:
        # If we have an MCP client active, we could use its tool.
        # But for local Playwright, we'll use a specialized JS script that mimics MCP's snapshotting.
        js_code = """
        () => {
            const getAriaInfo = (el) => {
                const rect = el.getBoundingClientRect();
                if (rect.width === 0 || rect.height === 0) return null;
                const style = window.getComputedStyle(el);
                if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') return null;

                return {
                    role: el.getAttribute('role') || el.tagName.toLowerCase(),
                    name: el.getAttribute('aria-label') || el.innerText?.substring(0, 50).trim() || el.placeholder || el.value || '',
                    description: el.getAttribute('aria-description') || '',
                    selector: el.id ? `#${el.id}` : (el.name ? `[name="${el.name}"]` : ''),
                    tag: el.tagName.toLowerCase(),
                    visible: true
                };
            };

            const walk = (node, depth = 0) => {
                if (depth > 10) return null;
                const info = getAriaInfo(node);
                if (!info) return null;

                const children = [];
                for (const child of node.children) {
                    const childInfo = walk(child, depth + 1);
                    if (childInfo) children.push(childInfo);
                }

                if (children.length > 0) info.children = children;
                return info;
            };

            const roots = document.querySelectorAll('main, [role="main"], body');
            for (const root of roots) {
                const snap = walk(root);
                if (snap) return snap;
            }
            return null;
        }
        """
        return await page.evaluate(js_code)
    except Exception as e:
        logger.warning(f"Failed to get accessibility snapshot: {e}")
        return []


async def gemini_heal_selector(
    page: Page,
    target_description: str,
    page_context: str = "pin_creation_tool",
) -> str | None:
    """
    Use Gemini CLI to heal a broken selector.
    Returns a valid Playwright CSS selector or None.
    """
    config = get_config().self_healing
    if not config.enabled:
        return None

    cache = get_healing_cache()
    cached = cache.get(page_context, target_description)
    if cached:
        return cached

    elements = await extract_interactive_elements(page, config.dom_element_limit)
    snapshot = await get_accessibility_snapshot(page)

    if not elements and not snapshot:
        logger.warning("Self-healing: no interactive elements or snapshot found")
        return None

    dom_json = json.dumps(elements, ensure_ascii=False, indent=2)
    a11y_json = json.dumps(snapshot, ensure_ascii=False, indent=2)

    prompt = f"""You are an expert Playwright automation engineer.
The standard locator for "{target_description}" on Pinterest just failed.

Here is a simplified accessibility tree of the page:
```json
{a11y_json}
```

And a list of interactive elements:
```json
{dom_json}
```

Identify the single element that most likely represents "{target_description}".
Return ONLY a valid Playwright CSS selector string. No explanations, no code blocks, no quotes.
Example: input[name="title"]
"""

    try:
        import shutil
        import subprocess

        gemini_path = shutil.which("gemini")
        if not gemini_path:
            logger.warning("Gemini CLI ('gemini') not found in PATH")
            return None

        logger.info(f"Invoking Gemini self-healing for: {target_description}")
        result = subprocess.run(
            [gemini_path, "-p", prompt, "--model", config.llm_model],
            capture_output=True,
            text=True,
            check=True,
            timeout=30,
        )
        selector = result.stdout.strip().strip("`").strip('"').strip("'")

        if "\n" in selector or len(selector) > config.max_selector_length:
            logger.warning(f"Gemini returned invalid selector format: {selector[:50]}...")
            return None

        # Validate selector is not empty and looks like a selector
        if not selector or (" " in selector.strip() and not any(c in selector for c in "[]#.")):
            logger.warning(f"Gemini returned suspicious selector: {selector}")
            return None

        logger.info(f"Gemini proposed selector: {selector}")
        cache.set(page_context, target_description, selector)
        return selector

    except subprocess.TimeoutExpired:
        logger.warning("Gemini self-healing timed out after 30s")
        return None
    except Exception as e:
        logger.warning(f"Gemini self-healing failed: {e}")
        return None


async def fallback_heal(
    page: Page,
    target_type: str,
) -> str | None:
    """
    Non-LLM fallback: try known selector strategies for a target type.
    Returns the first selector that matches a visible element.
    """
    strategies = FALLBACK_STRATEGIES.get(target_type, [])
    for sel in strategies:
        try:
            loc = page.locator(sel).first
            if await loc.count() > 0 and await loc.is_visible():
                logger.info(f"Fallback healing found '{target_type}' via: {sel}")
                return sel
        except Exception:
            continue
    logger.debug(f"Fallback healing found no match for '{target_type}'")
    return None


async def robust_fill(
    page: Page,
    target_type: str,
    target_description: str,
    value: str,
    use_keyboard: bool = False,
) -> bool:
    """
    Attempt to fill a field using multiple strategies:
    1. Known fallback selectors
    2. Cached healed selectors
    3. LLM self-healing
    4. JS injection fallback
    """
    # Strategy 1: Fallback selectors
    selector = await fallback_heal(page, target_type)

    # Strategy 2: Cached healing
    if not selector:
        cache = get_healing_cache()
        selector = cache.get("pin_creation_tool", target_description)

    # Strategy 3: LLM healing
    if not selector:
        selector = await gemini_heal_selector(page, target_description)

    if selector:
        try:
            loc = page.locator(selector).first
            if await loc.count() > 0 and await loc.is_visible():
                await loc.scroll_into_view_if_needed()
                await page.wait_for_timeout(150)
                await loc.click(force=True)
                await page.wait_for_timeout(100)
                if use_keyboard:
                    await page.keyboard.press("Control+A")
                    await page.keyboard.type(value, delay=30)
                else:
                    await loc.fill(value, timeout=5000)
                if target_type == "link":
                    if await _verify_link_value(page, value):
                        logger.info(f"Filled '{target_type}' via healed selector")
                        return True
                    logger.debug("Healed selector accepted link fill but verification failed")
                    return await _js_fill_link(page, value)
                logger.info(f"Filled '{target_type}' via healed selector")
                return True
        except Exception as e:
            logger.debug(f"Healed selector failed for '{target_type}': {e}")

    # Strategy 4: JS fallback for specific types
    if target_type == "title":
        return await _js_fill_title(page, value)
    elif target_type == "description":
        return await _js_fill_description(page, value)
    elif target_type == "link":
        return await _js_fill_link(page, value)

    logger.warning(f"All fill strategies failed for '{target_type}'")
    return False


async def _js_fill_title(page: Page, value: str) -> bool:
    script = f"""
    () => {{
        const editors = document.querySelectorAll('div[contenteditable="true"][role="textbox"]');
        for (const el of editors) {{
            const rect = el.getBoundingClientRect();
            if (rect.width > 0 && rect.height > 0 && rect.top < 600) {{
                el.focus();
                document.execCommand('selectAll', false, null);
                document.execCommand('insertText', false, {json.dumps(value[:100])});
                el.dispatchEvent(new Event('input', {{bubbles: true}}));
                el.dispatchEvent(new Event('change', {{bubbles: true}}));
                return true;
            }}
        }}
        const inputs = document.querySelectorAll('input[type="text"], input:not([type])');
        for (const inp of inputs) {{
            const ph = (inp.placeholder || '').toLowerCase();
            if (ph.includes('title') || ph.includes('título') || ph.includes('add a title') || inp.id.includes('title')) {{
                const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
                setter.call(inp, {json.dumps(value[:100])});
                inp.dispatchEvent(new Event('input', {{bubbles: true}}));
                inp.dispatchEvent(new Event('change', {{bubbles: true}}));
                return true;
            }}
        }}
        return false;
    }}
    """
    try:
        result = await page.evaluate(script)
        if result:
            logger.info("Title filled via JS fallback")
        return bool(result)
    except Exception as e:
        logger.debug(f"JS title fallback failed: {e}")
        return False


async def _js_fill_description(page: Page, value: str) -> bool:
    script = f"""
    () => {{
        const boxes = document.querySelectorAll('div[role="textbox"], div[role="combobox"], textarea');
        for (const el of boxes) {{
            const rect = el.getBoundingClientRect();
            if (rect.width > 100 && rect.height > 40) {{
                el.focus();
                if (el.tagName === 'TEXTAREA' || el.tagName === 'INPUT') {{
                    el.value = {json.dumps(value[:499])};
                }} else {{
                    document.execCommand('selectAll', false, null);
                    document.execCommand('insertText', false, {json.dumps(value[:499])});
                }}
                el.dispatchEvent(new Event('input', {{bubbles: true}}));
                el.dispatchEvent(new Event('change', {{bubbles: true}}));
                return true;
            }}
        }}
        return false;
    }}
    """
    try:
        result = await page.evaluate(script)
        if result:
            logger.info("Description filled via JS fallback")
        return bool(result)
    except Exception as e:
        logger.debug(f"JS description fallback failed: {e}")
        return False


async def _js_fill_link(page: Page, value: str) -> bool:
    script = f"""
    () => {{
        const inputs = document.querySelectorAll('input, textarea');
        for (const inp of inputs) {{
            const rect = inp.getBoundingClientRect();
            const style = window.getComputedStyle(inp);
            if (rect.width <= 0 || rect.height <= 0 || style.display === 'none' || style.visibility === 'hidden') {{
                continue;
            }}
            const ph = (inp.placeholder || '').toLowerCase();
            const aria = (inp.getAttribute('aria-label') || '').toLowerCase();
            const testId = (inp.closest('[data-test-id]')?.getAttribute('data-test-id') || '').toLowerCase();
            const labelText = (inp.closest('label')?.innerText || inp.parentElement?.innerText || '').toLowerCase();
            if (ph.includes('link') || ph.includes('enlace') || ph.includes('website') ||
                ph.includes('destination') || aria.includes('link') || aria.includes('enlace') ||
                aria.includes('destination') || inp.id.includes('link') || inp.name.includes('link') ||
                testId.includes('link') || labelText.includes('link') || labelText.includes('destination')) {{
                const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value')?.set ||
                    Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, 'value')?.set;
                setter.call(inp, {json.dumps(value)});
                inp.focus();
                inp.dispatchEvent(new Event('input', {{bubbles: true}}));
                inp.dispatchEvent(new Event('change', {{bubbles: true}}));
                inp.dispatchEvent(new KeyboardEvent('keydown', {{bubbles: true, key: 'Enter'}}));
                inp.dispatchEvent(new KeyboardEvent('keyup', {{bubbles: true, key: 'Enter'}}));
                return true;
            }}
        }}
        return false;
    }}
    """
    try:
        result = await page.evaluate(script)
        if result and await _verify_link_value(page, value):
            logger.info("Link filled via JS fallback")
            return True
        return False
    except Exception as e:
        logger.debug(f"JS link fallback failed: {e}")
        return False


async def _verify_link_value(page: Page, value: str) -> bool:
    script = f"""
    () => {{
        const expected = {json.dumps(value)}.trim();
        const inputs = Array.from(document.querySelectorAll('input, textarea'));
        return inputs.some((inp) => {{
            const current = (inp.value || inp.getAttribute('value') || '').trim();
            return current === expected;
        }});
    }}
    """
    try:
        return bool(await page.evaluate(script))
    except Exception:
        return False
