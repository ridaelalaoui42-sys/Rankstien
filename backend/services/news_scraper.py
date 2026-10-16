"""
RankStein News Scraper — Source-Based Content Pipeline
Scrapes search engines for articles, extracts content, validates quality.
Used by the MCP server to provide source material for content rewriting.
"""

import json
import logging
import re
import unicodedata
import urllib.parse

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger("rankstein.news")
_SESSION = None


def _get_session():
    """Get or create a requests.Session with connection pooling."""
    global _SESSION
    if _SESSION is None:
        from requests.adapters import HTTPAdapter

        _SESSION = requests.Session()
        adapter = HTTPAdapter(pool_connections=5, pool_maxsize=10)
        _SESSION.mount("http://", adapter)
        _SESSION.mount("https://", adapter)
    return _SESSION


_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
_SKIP_DOMAINS = {
    "nytimes.com",
    "wsj.com",
    "ft.com",
    "bloomberg.com",
    "economist.com",
    "recetadolce.com",
    "youtube.com",
    "google.com",
    "facebook.com",
    "instagram.com",
    "tiktok.com",
    "pinterest.com",
    "twitter.com",
}


# ═══════════════════════════════════════════════════════════════════════════════
# 1. MULTI-SOURCE ARTICLE SCRAPER
# ═══════════════════════════════════════════════════════════════════════════════


def scrape_google_news(keyword: str, lang: str = "es", country: str = "ES", count: int = 5) -> list[dict]:
    """
    Search for source articles about a keyword.
    Primary: duckduckgo_search library (uses their API, no bot detection).
    Fallback: requests-based search with multiple engines.
    Always returns direct URLs (no redirect wrappers).
    """
    # Strategy 1: duckduckgo_search library (most reliable)
    results = _ddg_api_search(keyword, count)
    if len(results) >= 2:
        logger.info("DDG API returned %d results for '%s'", len(results), keyword)
        return results[:count]

    # Strategy 2: DuckDuckGo lite (simpler HTML, less blocking)
    logger.warning("DDG API returned %d, trying DDG lite...", len(results))
    results.extend(_ddg_lite_search(keyword, count - len(results)))
    if len(results) >= 2:
        return results[:count]

    # Strategy 3: Google News RSS (titles only, may not have direct URLs)
    logger.warning("DDG lite returned %d total, trying Google News RSS...", len(results))
    results.extend(_google_news_rss(keyword, lang, country, count - len(results)))
    extractable = [item for item in results if str(item.get("url") or "").startswith("http")]
    if len(extractable) < len(results):
        logger.warning(
            "Discarded %d title-only search result(s) without extractable URLs",
            len(results) - len(extractable),
        )
    return extractable[:count]


def _ddg_api_search(keyword, count):
    """Primary: use ddgs Python library (formerly duckduckgo_search)."""
    try:
        try:
            from ddgs import DDGS
        except ImportError:
            from duckduckgo_search import DDGS
        with DDGS() as ddgs:
            raw = list(ddgs.text(f"{keyword} receta", region="es-es", max_results=count + 3))
        items = []
        for r in raw:
            href = r.get("href", "")
            domain = urllib.parse.urlparse(href).netloc.lower()
            if any(d in domain for d in _SKIP_DOMAINS):
                continue
            items.append(
                {
                    "title": r.get("title", ""),
                    "url": href,
                    "snippet": r.get("body", "")[:300],
                    "source": domain,
                    "date": "",
                }
            )
            if len(items) >= count:
                break
        return items
    except ImportError:
        logger.warning("duckduckgo_search not installed, skipping DDG API")
        return []
    except Exception as e:
        logger.warning("DDG API search error: %s", e)
        return []


def _ddg_lite_search(keyword, count):
    """DuckDuckGo Lite — simpler page, less JS, more bot-friendly."""
    try:
        q = urllib.parse.quote(f"{keyword} receta")
        url = f"https://lite.duckduckgo.com/lite/?q={q}"
        resp = _get_session().get(url, headers={"User-Agent": _UA}, timeout=15)
        soup = BeautifulSoup(resp.text, "html.parser")
        items = []
        # DDG Lite uses tables with <a> tags in specific cells
        for a in soup.find_all("a", class_="result-link"):
            href = a.get("href", "")
            if not href.startswith("http"):
                continue
            domain = urllib.parse.urlparse(href).netloc.lower()
            if any(d in domain for d in _SKIP_DOMAINS):
                continue
            items.append(
                {
                    "title": a.get_text(strip=True),
                    "url": href,
                    "snippet": "",
                    "source": domain,
                    "date": "",
                }
            )
            if len(items) >= count:
                break
        # Also try regular links
        if not items:
            for a in soup.find_all("a", href=True):
                href = a.get("href", "")
                if href.startswith("http") and "duckduckgo" not in href:
                    domain = urllib.parse.urlparse(href).netloc.lower()
                    if any(d in domain for d in _SKIP_DOMAINS):
                        continue
                    title = a.get_text(strip=True)
                    if title and len(title) > 15:
                        items.append(
                            {
                                "title": title,
                                "url": href,
                                "snippet": "",
                                "source": domain,
                                "date": "",
                            }
                        )
                    if len(items) >= count:
                        break
        return items
    except Exception as e:
        logger.warning("DDG Lite error: %s", e)
        return []


def _google_news_rss(keyword, lang, country, count):
    """Google News RSS — returns article titles + Google redirect URLs.
    These URLs may not resolve with requests, but titles are useful context."""
    try:
        import xml.etree.ElementTree as ET

        encoded = urllib.parse.quote(keyword)
        url = f"https://news.google.com/rss/search?q={encoded}&hl={lang}&gl={country}&ceid={country}:{lang}"
        resp = _get_session().get(url, headers={"User-Agent": _UA}, timeout=15)
        resp.raise_for_status()
        root = ET.fromstring(resp.content)
        items = []
        for el in root.findall(".//item"):
            title = el.findtext("title", "")
            source_el = el.find("source")
            source = source_el.text if source_el is not None else ""
            desc = el.findtext("description", "")
            snippet = BeautifulSoup(desc, "html.parser").get_text(strip=True)[:300]
            # Don't include the Google redirect URL — it won't work
            # Instead return empty URL so Gemini knows this is title-only
            items.append(
                {
                    "title": title.split(" - ")[0].strip(),
                    "url": "",  # Can't resolve Google News redirects without JS
                    "snippet": snippet,
                    "source": source,
                    "date": el.findtext("pubDate", ""),
                    "note": "title_only — URL not extractable from Google News RSS",
                }
            )
            if len(items) >= count:
                break
        return items
    except Exception as e:
        logger.warning("Google News RSS error: %s", e)
        return []


# ═══════════════════════════════════════════════════════════════════════════════
# 2. ARTICLE CONTENT EXTRACTOR
# ═══════════════════════════════════════════════════════════════════════════════


_STEP_IMAGE_NOISE = re.compile(
    r"(?:^|[\s/_.-])(?:logo|avatar|icon|pixel|gravatar|ads?|ad-banner|advertisement|"
    r"placeholder|blank|spacer|loading)(?:[\s/_.-]|$)",
    re.I,
)
_STEP_CONTAINER_NOISE = re.compile(
    r"(?:^|[\s_-])(?:ads?|advertisement|publicidad|banner|sidebar|related|recommended|"
    r"recommendations|recetas-relacionadas|otras-recetas|author|autor|avatar|social|share|"
    r"comments?|comentarios|newsletter|featured|thumbnail|hero)(?:[\s_-]|$)",
    re.I,
)
_PREPARATION_SECTION = re.compile(
    r"preparaci|elaboraci|instrucci|instruction|procedimiento|recipe-step|"
    r"recipe-instruction|paso|c.*?mo.*?(?:hacer|preparar)|method|direction",
    re.I,
)
_RELATED_SECTION = re.compile(
    r"otras recetas|recetas relacionadas|tambien te|te puede gustar|related|recommended|"
    r"comentarios|comments|sobre el autor",
    re.I,
)


def _image_url(value, base_url=""):
    """Resolve only usable HTTP image URLs; lazy placeholders are not source images."""
    if not isinstance(value, str) or not value.strip():
        return ""
    value = value.strip()
    try:
        if value.startswith("//"):
            value = urllib.parse.urljoin(base_url or "https://example.invalid", value)
        elif base_url:
            value = urllib.parse.urljoin(base_url, value)
        parsed = urllib.parse.urlsplit(value)
    except ValueError:
        return ""
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return ""
    if _STEP_IMAGE_NOISE.search(parsed.path) or parsed.path.lower().endswith(".svg"):
        return ""
    return urllib.parse.urldefrag(value)[0]


def _image_identity(url):
    """Deduplicate common WordPress and CDN size variants without losing asset identifiers."""
    parsed = urllib.parse.urlsplit(url)
    path = re.sub(r"-\d+x\d+(?=\.[^.]+$)", "", parsed.path)
    size_parameters = {"w", "h", "width", "height", "resize", "quality", "q", "fit"}
    query = urllib.parse.urlencode(
        [
            (key, value)
            for key, value in urllib.parse.parse_qsl(parsed.query)
            if key.lower() not in size_parameters
        ]
    )
    return urllib.parse.urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(), path, query, ""))


def _srcset_image(value, base_url):
    """Read URL/descriptor tokens; commas inside CDN transformation URLs are valid."""
    value = str(value or "")
    candidates = []
    position = 0
    while position < len(value):
        while position < len(value) and (value[position].isspace() or value[position] == ","):
            position += 1
        start = position
        while position < len(value) and not value[position].isspace():
            position += 1
        url_token = value[start:position]
        descriptor = "1x"
        if url_token.endswith(","):
            url_token = url_token.rstrip(",")
        else:
            start = position
            while position < len(value) and value[position] != ",":
                position += 1
            descriptor = value[start:position].strip() or "1x"
        url = _image_url(url_token, base_url)
        match = re.fullmatch(r"(\d+(?:\.\d+)?)([wx])", descriptor)
        if url and match and float(match[1]) > 0:
            score = float(match[1]) * (1000 if match[2] == "x" else 1)
            candidates.append((score, url))
    return max(candidates, default=(0, ""), key=lambda item: item[0])[1]


def _tag_image_url(tag, base_url):
    """Prefer real lazy/responsive assets to the placeholder in img.src."""
    picture = tag.find_parent("picture")
    sources = picture.find_all("source") if picture else []
    for node in [tag, *sources]:
        for attribute in ("data-srcset", "data-lazy-srcset"):
            if url := _srcset_image(node.get(attribute), base_url):
                return url
    for attribute in ("data-src", "data-lazy-src", "data-original", "data-original-src"):
        if url := _image_url(tag.get(attribute), base_url):
            return url
    for node in [*sources, tag]:
        if url := _srcset_image(node.get("srcset"), base_url):
            return url
    return _image_url(tag.get("src"), base_url)


def _schema_images(value, base_url):
    if isinstance(value, list):
        for item in value:
            yield from _schema_images(item, base_url)
    elif isinstance(value, dict):
        yield from _schema_images(value.get("url") or value.get("contentUrl"), base_url)
    elif url := _image_url(value, base_url):
        yield url


def _recipe_nodes(value):
    if isinstance(value, list):
        for item in value:
            yield from _recipe_nodes(item)
    elif isinstance(value, dict):
        types = value.get("@type") or []
        if "Recipe" in (types if isinstance(types, list) else [types]):
            yield value
        yield from _recipe_nodes(value.get("@graph"))


def _instruction_steps(value):
    if isinstance(value, list):
        for item in value:
            yield from _instruction_steps(item)
    elif isinstance(value, dict) and value.get("itemListElement"):
        yield from _instruction_steps(value["itemListElement"])
    elif isinstance(value, (dict, str)):
        yield value


def _image_in_noise_container(tag):
    for node in [tag, *tag.parents]:
        if node.name in {"nav", "aside", "footer", "header"}:
            return True
        labels = " ".join([str(node.get("id") or ""), *node.get("class", [])])
        if _STEP_CONTAINER_NOISE.search(labels) or node.get("role") in {"navigation", "banner"}:
            return True
    dimensions = [re.fullmatch(r"\d+", str(tag.get(name) or "")) for name in ("width", "height")]
    values = [int(match[0]) for match in dimensions if match]
    return bool(values and (min(values) <= 32 or (len(values) == 2 and max(values) <= 120)))


def _step_image_text(tag, container=None):
    figure = tag.find_parent("figure")
    caption = figure.find("figcaption") if figure else None
    if caption:
        return caption.get_text(" ", strip=True)[:200]
    if tag.get("alt"):
        return str(tag["alt"]).strip()[:200]
    if container is not None:
        instruction = tag.find_parent("li")
        if instruction is not None and any(parent is container for parent in instruction.parents):
            return instruction.get_text(" ", strip=True)[:200]
        return container.get_text(" ", strip=True)[:200]
    preceding = tag.find_previous(["p", "li"])
    if preceding and any(parent is preceding.parent for parent in tag.parents):
        return preceding.get_text(" ", strip=True)[:200]
    return ""


def _plain_section_text(value):
    return "".join(c for c in unicodedata.normalize("NFKD", value.lower()) if not unicodedata.combining(c))


def _extract_step_images(soup, base_url=""):
    """Extract researched preparation photos, preferring explicit steps over content heuristics."""
    recipes = []
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            recipes.extend(_recipe_nodes(json.loads(script.string or script.get_text() or "")))
        except (ValueError, TypeError):
            continue

    hero_urls = {url for recipe in recipes for url in _schema_images(recipe.get("image"), base_url)}
    for meta in soup.select(
        "meta[property='og:image'], meta[name='og:image'], meta[name='twitter:image'], meta[property='twitter:image']"
    ):
        if url := _image_url(meta.get("content"), base_url):
            hero_urls.add(url)
    hero_ids = {_image_identity(url) for url in hero_urls}
    seen = set()
    accepted_numbers = set()
    results = []

    def add(url, number, text=""):
        identity = _image_identity(url)
        if not url or identity in seen or identity in hero_ids:
            return
        # A schema step wins over an alternate numbered file for the same step. Reserve
        # the rejected file as well so content traversal cannot re-add it under a new number.
        seen.add(identity)
        if number in accepted_numbers:
            return
        accepted_numbers.add(number)
        results.append({"step_number": number, "image_url": url, "text": text[:200]})

    # Recipe instructions are the most reliable source of step numbering.
    for recipe in recipes:
        for number, step in enumerate(_instruction_steps(recipe.get("recipeInstructions")), 1):
            if isinstance(step, dict):
                text = str(step.get("text") or step.get("name") or "")
                image = next(_schema_images(step.get("image"), base_url), "")
                add(image, number, text)
    # Preserve explicitly numbered filenames/alt text, including lazy and responsive images.
    numbered = []
    for tag in soup.find_all("img"):
        if _image_in_noise_container(tag):
            continue
        url = _tag_image_url(tag, base_url)
        text = _step_image_text(tag)
        match = re.search(r"(?:^|[/_-])(?:paso|step)[-_]?(\d+)", url, re.I) or re.search(
            r"(?:paso|step)\s*[-:]?\s*(\d+)", text, re.I
        )
        if match:
            numbered.append((int(match[1]), url, text))
    for number, url, text in sorted(numbered, key=lambda item: item[0]):
        add(url, number, text or f"Paso {number}")
    # Explicit instruction containers can contain a single photo or several figures.
    selector = (
        ".recipe-instructions, .recipe-steps, .instrucciones, .pasos, .recipe-instruction, "
        ".step, .wp-block-recipe-step, [itemprop='recipeInstructions'], "
        ".wprm-recipe-instructions, .wprm-recipe-instruction, .preparacion, .elaboracion, #preparacion, #elaboracion, "
        ".tasty-recipes-instructions, .tasty-recipe-instructions"
    )
    containers = soup.select(selector)
    container_ids = {id(node) for node in containers}
    # Spanish sites often publish photos in ordinary figures between preparation paragraphs.
    root_selectors = [
        "article",
        "main",
        ".entry-content",
        ".post-content",
        ".article-content",
        ".article-body",
        ".content-body",
        ".story-body",
        ".td-post-content",
        ".article__body",
        "#article-body",
        "[itemprop='articleBody']",
        ".et_pb_post_content",
        ".et_builder_inner_content",
        ".elementor-widget-theme-post-content",
        ".elementor-post__content",
        ".wp-block-post-content",
        ".recipe-content",
        ".recipe-body",
    ]
    candidates = []
    for sel in root_selectors:
        candidates.extend(soup.select(sel))
    root = max(candidates, key=lambda el: len(el.get_text()), default=None)
    if root is None:
        root = soup.find("article") or soup.find("main")
    headings = root.find_all(re.compile(r"^h[1-6]$")) if root is not None else []
    has_preparation = any(_PREPARATION_SECTION.search(_plain_section_text(h.get_text(" "))) for h in headings)
    root_ids = {id(node) for node in root.descendants if getattr(node, "name", None)} if root else set()
    trusted_numbers = {_image_identity(item["image_url"]): item["step_number"] for item in results}
    used_numbers = set(trusted_numbers.values())
    dom_number = 1
    preparation_level = None
    related_section = False
    for node in soup.descendants:
        if not getattr(node, "name", None):
            continue
        in_content = id(node) in root_ids
        if in_content and re.fullmatch(r"h[1-6]", node.name):
            heading = _plain_section_text(node.get_text(" ", strip=True))
            level = int(node.name[1])
            if _PREPARATION_SECTION.search(heading):
                preparation_level = min(preparation_level, level) if preparation_level is not None else level
                related_section = False
            elif preparation_level is not None and level <= preparation_level:
                preparation_level = None
            if _RELATED_SECTION.search(heading):
                related_section = True
            continue
        if node.name != "img" or _image_in_noise_container(node):
            continue
        container = next((parent for parent in node.parents if id(parent) in container_ids), None)
        if container is None and (
            not in_content or related_section or (has_preparation and preparation_level is None)
        ):
            continue
        url = _tag_image_url(node, base_url)
        identity = _image_identity(url)
        if identity in trusted_numbers:
            dom_number = max(dom_number, trusted_numbers[identity] + 1)
            continue
        while dom_number in used_numbers:
            dom_number += 1
        previous_count = len(results)
        add(url, dom_number, _step_image_text(node, container))
        if len(results) > previous_count:
            used_numbers.add(dom_number)
            dom_number += 1
    return sorted(results, key=lambda item: item["step_number"])


def _extract_hero_image(soup, base_url=""):
    """Extract lead/hero image from recipe article (JSON-LD Recipe, og:image, or featured image)."""
    # 1. JSON-LD Recipe image
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            raw_text = script.string or script.get_text() or ""
            if not raw_text.strip():
                continue
            data = json.loads(raw_text)
            candidates = (
                data.get("@graph", [data])
                if isinstance(data, dict)
                else (data if isinstance(data, list) else [])
            )
            for item in candidates:
                if isinstance(item, dict) and item.get("@type") in ("Recipe", ["Recipe"]):
                    img = item.get("image")
                    if isinstance(img, list) and img:
                        img = img[0]
                    if isinstance(img, dict):
                        img = img.get("url")
                    if isinstance(img, str) and img.startswith("http"):
                        return img
        except Exception:
            continue

    # 2. OpenGraph og:image
    og = soup.find("meta", property="og:image") or soup.find("meta", attrs={"name": "og:image"})
    if og and og.get("content"):
        img = og["content"].strip()
        if img.startswith("//"):
            img = "https:" + img
        elif img.startswith("/") and base_url:
            img = urllib.parse.urljoin(base_url, img)
        if img.startswith("http"):
            lower = img.lower()
            if not any(
                bad in lower for bad in ["logo", "avatar", "icon", "pixel", "default", "placeholder", "blank"]
            ):
                return img

    # 3. Twitter image
    tw = soup.find("meta", attrs={"name": "twitter:image"}) or soup.find("meta", property="twitter:image")
    if tw and tw.get("content"):
        img = tw["content"].strip()
        if img.startswith("//"):
            img = "https:" + img
        elif img.startswith("/") and base_url:
            img = urllib.parse.urljoin(base_url, img)
        if img.startswith("http"):
            lower = img.lower()
            if not any(
                bad in lower for bad in ["logo", "avatar", "icon", "pixel", "default", "placeholder", "blank"]
            ):
                return img

    # 4. Featured / Header / Article Image Selectors
    for sel in [
        ".featured-image img",
        ".post-thumbnail img",
        ".entry-thumbnail img",
        ".lead-image img",
        "article header img",
        "figure.wp-block-post-featured-image img",
        "article img",
    ]:
        tag = soup.select_one(sel)
        if tag:
            src = tag.get("src") or tag.get("data-src") or tag.get("data-lazy-src") or ""
            if src and not src.startswith("http") and base_url:
                src = urllib.parse.urljoin(base_url, src)
            if src.startswith("http"):
                lower = src.lower()
                if not any(bad in lower for bad in ["logo", "avatar", "icon", "pixel", "ad", "spacer"]):
                    return src

    return ""


def extract_article(url: str) -> dict:
    """
    Extract full article content from any URL.
    Multi-strategy: <article> → content selectors → largest text block → all <p>.
    Returns: {success, url, title, content, author, date, word_count, key_sections, step_images, hero_image}
    """
    if not url or not url.startswith("http"):
        return {"success": False, "error": "Invalid or empty URL", "url": url}

    try:
        resp = _get_session().get(
            url,
            headers={
                "User-Agent": _UA,
                "Accept": "text/html,application/xhtml+xml",
                "Accept-Language": "es-ES,es;q=0.9,en;q=0.5",
            },
            timeout=20,
            allow_redirects=True,
        )
        resp.raise_for_status()

        # Use final URL (after redirects)
        url = resp.url
        try:
            resp.content.decode("utf-8")
            resp.encoding = "utf-8"
        except (UnicodeDecodeError, AttributeError):
            resp.encoding = resp.apparent_encoding or "utf-8"
        soup = BeautifulSoup(resp.text, "html.parser")

        # Extract step and hero images BEFORE stripping scripts and tags
        step_images = _extract_step_images(soup, url)
        hero_image = _extract_hero_image(soup, url)

        # Strip noise
        for tag in soup.select(
            "script, style, nav, footer, header, aside, .ad, .advertisement, "
            ".sidebar, .comments, .social-share, [role='navigation'], [role='banner'], "
            ".cookie-banner, .newsletter-signup, .popup, .modal"
        ):
            tag.decompose()

        title = _title(soup)
        author = _author(soup)
        date = _date(soup)

        # Extract YouTube URLs before decomposing iframes
        videos = []
        for iframe in soup.find_all("iframe"):
            src = iframe.get("src", "")
            if "youtube.com" in src or "youtu.be" in src:
                # Clean URL (remove autoplay, etc if needed)
                clean_url = src.split("?")[0]
                if clean_url not in videos:
                    videos.append(clean_url)

        # Also check for direct links in case they aren't embedded
        for a in soup.find_all("a", href=True):
            href = a.get("href", "")
            if ("youtube.com/watch" in href or "youtu.be/" in href) and href not in videos:
                # Convert watch?v= to embed/ if needed for later iframe use
                if "watch?v=" in href:
                    video_id = href.split("v=")[1].split("&")[0]
                    href = f"https://www.youtube.com/embed/{video_id}"
                elif "youtu.be/" in href:
                    video_id = href.split("youtu.be/")[1].split("?")[0]
                    href = f"https://www.youtube.com/embed/{video_id}"
                if href not in videos:
                    videos.append(href)

        content = _content(soup)
        sections = _sections(soup)

        if not content or len(content.split()) < 80:
            return {"success": False, "error": "Content too thin to use as source", "url": url}

        wc = len(content.split())
        logger.info("Extracted %d words and %d videos from %s", wc, len(videos), url)
        return {
            "success": True,
            "url": url,
            "title": title,
            "content": content[:15000],
            "author": author,
            "date": date,
            "word_count": wc,
            "key_sections": sections[:10],
            "videos": videos,
            "step_images": step_images,
            "hero_image": hero_image,
        }
    except requests.exceptions.Timeout:
        return {"success": False, "error": f"Timeout: {url}", "url": url}
    except requests.exceptions.HTTPError as e:
        return {"success": False, "error": f"HTTP {e.response.status_code}", "url": url}
    except Exception as e:
        return {"success": False, "error": str(e), "url": url}


def _title(soup):
    og = soup.find("meta", property="og:title")
    if og and og.get("content"):
        return og["content"].strip()
    if soup.title and soup.title.string:
        return soup.title.string.strip()
    h1 = soup.find("h1")
    return h1.get_text(strip=True) if h1 else ""


def _author(soup):
    m = soup.find("meta", attrs={"name": "author"})
    if m and m.get("content"):
        return m["content"].strip()
    for sel in [".author", "[rel='author']", ".byline", ".post-author"]:
        el = soup.select_one(sel)
        if el:
            return el.get_text(strip=True)
    return ""


def _date(soup):
    t = soup.find("time")
    if t:
        return t.get("datetime", "") or t.get_text(strip=True)
    for attr in ["article:published_time", "datePublished"]:
        m = soup.find("meta", property=attr) or soup.find("meta", attrs={"name": attr})
        if m and m.get("content"):
            return m["content"].strip()
    return ""


def _content(soup):
    """Multi-strategy content extraction."""
    # Strategy 1: <article> tag
    art = soup.find("article")
    if art:
        t = art.get_text(separator="\n", strip=True)
        if len(t.split()) > 150:
            return _clean(t)

    # Strategy 2: Common CSS selectors
    for sel in [
        ".post-content",
        ".article-content",
        ".article-body",
        ".entry-content",
        ".content-body",
        ".story-body",
        '[itemprop="articleBody"]',
        ".td-post-content",
        ".article__body",
        "#article-body",
        "main .content",
    ]:
        el = soup.select_one(sel)
        if el:
            t = el.get_text(separator="\n", strip=True)
            if len(t.split()) > 150:
                return _clean(t)

    # Strategy 3: Largest text block
    best, best_score = "", 0
    for tag in soup.find_all(["div", "section", "main"]):
        t = tag.get_text(separator="\n", strip=True)
        wc = len(t.split())
        pc = len(tag.find_all("p"))
        score = wc + pc * 50
        if wc > 150 and score > best_score:
            best, best_score = t, score
    if best:
        return _clean(best)

    # Strategy 4: All paragraphs
    paras = [p.get_text(strip=True) for p in soup.find_all("p") if len(p.get_text(strip=True)) > 30]
    return _clean("\n\n".join(paras)) if paras else ""


def _sections(soup):
    """Extract heading→content pairs for structural analysis."""
    result = []
    for h in soup.find_all(["h2", "h3"]):
        heading = h.get_text(strip=True)
        if not heading or len(heading) < 3:
            continue
        following = []
        for sib in h.find_next_siblings():
            if sib.name in ["h1", "h2", "h3"]:
                break
            t = sib.get_text(strip=True)
            if t:
                following.append(t)
        if following:
            result.append({"heading": heading, "content": " ".join(following)[:500]})
    return result


def _clean(text):
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r" {2,}", " ", text)
    text = re.sub(
        r"(Leer más|Read more|Continuar leyendo|Suscríbete|Newsletter|Acepto cookies).*$",
        "",
        text,
        flags=re.MULTILINE,
    )
    return text.strip()


# ═══════════════════════════════════════════════════════════════════════════════
# 3. ARTICLE QUALITY VALIDATOR
# ═══════════════════════════════════════════════════════════════════════════════


def validate_article(data: dict) -> dict:
    """
    Pre-publish quality gate. Scores article on word count, E-E-A-T markers,
    humanization signals, schema completeness, and excerpt quality.
    Returns: {score, passed, issues[], recommendations[]}
    """
    issues = []
    recs = []
    score = 100
    content = data.get("content") or data.get("content_markdown") or ""
    wc = len(content.split())
    low = content.lower()

    # 1. Word count
    if wc < 900:
        issues.append(f"Too short: {wc} words (min 900)")
        score -= 30
    elif wc < 1200:
        recs.append(f"Currently {wc} words — aim for 1200-1500 for SEO")
        score -= 5
    elif wc > 2000:
        recs.append(f"Currently {wc} words — article is quite long, consider trimming to 1500")

    # 2. E-E-A-T citations
    eeat = [
        "aesan",
        "efsa",
        "codex alimentarius",
        "seguridad alimentaria",
        "normativa",
        "según estudios",
        "organización mundial",
    ]
    found = sum(1 for m in eeat if m in low)
    if found == 0:
        issues.append("No E-E-A-T authority citations (AESAN, EFSA, etc.)")
        score -= 20
    elif found < 2:
        recs.append("Add more authority citations for stronger E-E-A-T")
        score -= 5

    # 3. Humanization markers
    human = [
        "mi experiencia",
        "he probado",
        "recomiendo",
        "personalmente",
        "en mi cocina",
        "mi abuela",
        "truco del chef",
        "años cocinando",
        "te cuento",
        "mi secreto",
    ]
    hf = sum(1 for m in human if m in low)
    if hf == 0:
        issues.append("No first-person / experiential markers — sounds AI-generated")
        score -= 15
    elif hf < 2:
        recs.append("Add more personal anecdotes for natural tone")
        score -= 5

    # 4. Structural markers
    if content.count("##") < 3:
        recs.append("Add more H2/H3 subheadings for scannability")
        score -= 5
    if "**" not in content and "__" not in content:
        recs.append("Add bold text to highlight key points")
        score -= 3

    # 5. Excerpt
    excerpt = data.get("excerpt", "")
    if not excerpt:
        issues.append("Missing excerpt")
        score -= 10
    elif len(excerpt) > 155:
        issues.append(f"Excerpt too long: {len(excerpt)} chars (max 155)")
        score -= 5

    # 6. Category with domain enforcement
    cat = str(data.get("category", "")).strip()
    domain_handle = (data.get("domain_handle") or data.get("domain") or "").strip().lower()

    dolce_categories = {
        "fresas-y-nata",
        "tartas-y-pasteles",
        "chocolates",
        "dulces-saludables",
        "Fresas y Nata",
        "Tartas y Pasteles",
        "Chocolates",
        "Dulces Saludables",
        "pasteles",
        "galletas",
        "repostería",
        "helados",
    }
    genial_categories = {
        "Aperitivos",
        "Arroces",
        "Carnes",
        "Pescados",
        "Ensaladas",
        "Postres",
        "aperitivos",
        "arroces",
        "carnes",
        "pescados",
        "ensaladas",
        "postres",
    }

    if domain_handle in ("recetadolce", "dolce"):
        valid = dolce_categories
        if cat and cat not in valid:
            issues.append(
                f"Invalid category '{cat}' for RecetaDolce. Must be one of {sorted(dolce_categories)}"
            )
            score -= 30
    elif domain_handle in ("recetagenial", "genial"):
        valid = genial_categories
        if cat and cat not in valid:
            issues.append(
                f"Invalid category '{cat}' for RecetaGenial. Must be one of {sorted(genial_categories)}"
            )
            score -= 30
    else:
        valid = dolce_categories | genial_categories
        if cat and cat not in valid:
            issues.append(f"Invalid category '{cat}'. Must be one of {sorted(valid)}")
            score -= 10

    # Cross-brand leak guards
    if domain_handle in ("recetadolce", "dolce"):
        if "recetagenial" in low or "receta genial" in low or "hokcljsrrnjxzgdhjice" in content:
            issues.append(
                "Cross-brand contamination: RecetaGenial text or storage bucket found on RecetaDolce"
            )
            score -= 40
    elif domain_handle in ("recetagenial", "genial"):
        if "recetadolce" in low or "receta dolce" in low or "xjvmnmfczvwkjiasirsl" in content:
            issues.append(
                "Cross-brand contamination: RecetaDolce text or storage bucket found on RecetaGenial"
            )
            score -= 40

    # 7. Recipe schema. Google recipe rich-result eligibility depends on a
    # complete Recipe object, not just any JSON blob with @type=Recipe.
    schema = data.get("recipe_schema", {})
    if isinstance(schema, str):
        try:
            schema = json.loads(schema)
        except Exception:
            schema = {}
    if not schema:
        issues.append("Missing recipe_schema")
        score -= 10
    else:
        required_text = {
            "name": "Recipe schema missing name",
            "description": "Recipe schema missing description",
            "recipeYield": "Recipe schema missing recipeYield",
            "recipeCategory": "Recipe schema missing recipeCategory",
            "recipeCuisine": "Recipe schema missing recipeCuisine",
            "prepTime": "Recipe schema missing prepTime",
            "cookTime": "Recipe schema missing cookTime",
            "totalTime": "Recipe schema missing totalTime",
        }
        for field, message in required_text.items():
            if not str(schema.get(field) or "").strip():
                issues.append(message)
                score -= 6
        image = schema.get("image")
        if not image:
            issues.append("Recipe schema missing image")
            score -= 8
        author = schema.get("author")
        if not author or not (isinstance(author, dict) and str(author.get("name") or "").strip()):
            issues.append("Recipe schema missing author.name")
            score -= 6
        for time_field in ("prepTime", "cookTime", "totalTime"):
            value = str(schema.get(time_field) or "")
            if value and not re.fullmatch(r"PT(?=\d)(?:(?:\d+)H)?(?:(?:\d+)M)?", value):
                issues.append(f"{time_field} must be ISO-8601 duration like PT15M")
                score -= 5

        ingredients = schema.get("recipeIngredient") or schema.get("ingredients") or []
        instructions = schema.get("recipeInstructions") or schema.get("instructions") or []
        if not isinstance(ingredients, list) or len([x for x in ingredients if str(x).strip()]) < 5:
            issues.append("Recipe schema needs at least 5 populated recipeIngredient items")
            score -= 15
        if not isinstance(instructions, list) or len(instructions) < 5:
            issues.append("Recipe schema needs at least 5 populated recipeInstructions steps")
            score -= 15
        generic_schema_text = " ".join(str(item).lower() for item in ingredients)
        generic_schema_text += " " + " ".join(str(item).lower() for item in instructions)
        generic_markers = (
            "ingrediente principal",
            "base cremosa o caldo",
            "toque aromático",
            "toque aromatico",
            "cocina la base",
            "integra el ingrediente principal",
            "ingrediente de calidad",
        )
        if any(marker in generic_schema_text for marker in generic_markers):
            issues.append("FATAL: Recipe schema contains generic placeholder ingredients or steps")
            score = 0

    # 8. FAQ schema
    faq = data.get("faq_schema", [])
    if isinstance(faq, str):
        try:
            faq = json.loads(faq)
        except Exception:
            faq = []
    if not faq or len(faq) < 3:
        issues.append("Add at least 3 FAQ items for rich snippets")
        score -= 5

    # 9. Unreplaced placeholders, template leaks, and content-quality hazards
    # Note: [HERO_IMAGE] and [PINTEREST_IFRAME*] are valid assembly placeholders replaced by build_supabase_content.
    for ph in ["[TODO]", "[INSERT", "[IMAGE]"]:
        if ph in content:
            issues.append(f"Unreplaced template placeholder found: {ph}")
            score -= 20
    if r"\n\n" in content:
        issues.append("Unescaped literal \\n\\n detected in content markdown")
        score -= 20
    if re.search(r"\bprompt:\s*", content, re.IGNORECASE):
        issues.append("Internal workflow leak: 'prompt:' marker found in content")
        score -= 25
    if re.search(r"<blockquote(?![^>]*(?:pinterest-pin|data-pin-id))", content, flags=re.I):
        issues.append(
            "Article contains a non-Pinterest blockquote; summarize sources instead of copying text"
        )
        score -= 20
    boilerplate_markers = (
        "organización de campaña",
        "imagen subida",
        "pinterest actualizado",
        "campaña multidominio",
        "ingrediente principal",
        "base cremosa o caldo",
        "toque aromático",
        "cocina la base",
        "integra el ingrediente principal",
    )
    for marker in boilerplate_markers:
        if marker in low:
            issues.append(f"Article contains internal/generic boilerplate: {marker}")
            score -= 30
            break
    sentences = [
        re.sub(r"\s+", " ", part.strip().casefold())
        for part in re.split(r"[.!?]\s+", content)
        if len(part.split()) >= 8
    ]
    repeated = sorted({sentence for sentence in sentences if sentences.count(sentence) > 1})
    if repeated:
        issues.append("Repeated sentence detected; article needs more varied, original prose")
        score -= 10

    score = max(0, score)
    return {
        "score": score,
        "passed": score >= 60 and len(issues) == 0,
        "word_count": wc,
        "issues": issues,
        "recommendations": recs,
    }
