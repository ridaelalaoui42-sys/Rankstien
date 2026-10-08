"""
RankStein News Scraper — Source-Based Content Pipeline
Scrapes search engines for articles, extracts content, validates quality.
Used by the MCP server to provide source material for content rewriting.
"""

import json
import logging
import re
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


def extract_article(url: str) -> dict:
    """
    Extract full article content from any URL.
    Multi-strategy: <article> → content selectors → largest text block → all <p>.
    Returns: {success, url, title, content, author, date, word_count, key_sections}
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
        resp.encoding = resp.apparent_encoding or "utf-8"
        soup = BeautifulSoup(resp.text, "html.parser")

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

    # 6. Category
    cat = data.get("category", "")
    valid = {
        # RecetaGenial canonical
        "Aperitivos",
        "Arroces",
        "Carnes",
        "Pescados",
        "Ensaladas",
        "Postres",
        # RecetaDolce canonical
        "fresas-y-nata",
        "tartas-y-pasteles",
        "chocolates",
        "dulces-saludables",
        # Common aliases & subsets
        "Pasteles",
        "Galletas",
        "Chocolates",
        "Repostería",
        "Helados",
    }
    if cat and cat not in valid:
        issues.append(f"Invalid category '{cat}'. Must be one of {sorted(valid)}")
        score -= 10

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
        )
        if any(marker in generic_schema_text for marker in generic_markers):
            issues.append("Recipe schema contains generic placeholder ingredients or steps")
            score -= 20

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

    # 9. Unreplaced placeholders and duplicate/content-quality hazards
    for ph in ["[TODO]", "[INSERT"]:
        if ph in content:
            issues.append(f"Unreplaced placeholder found: {ph}")
            score -= 10
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
    )
    for marker in boilerplate_markers:
        if marker in low:
            issues.append(f"Article contains internal/generic boilerplate: {marker}")
            score -= 10
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
