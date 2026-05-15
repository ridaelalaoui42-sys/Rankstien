"""Daily trend intelligence for RankStein domains.

The pipeline blends Pinterest Trends discovery with Google News RSS validation,
then writes a per-domain "best keywords today" list and appends new Pending
roadmap rows. It is intentionally deterministic after scraping so autonomous
runs stay explainable.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import threading
import urllib.parse
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

import requests
from bs4 import BeautifulSoup
from defusedxml import ElementTree as ET

from rankstein.domain import Domain
from rankstein.keyword_roadmap import KeywordRow, append_keyword_rows

logger = logging.getLogger("rankstein.trends")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)
DEFAULT_REGION = "ES"
DEFAULT_LANGUAGE = "es"
PINTEREST_TRENDS_URL = "https://trends.pinterest.com/"

NOISE_TERMS = {
    "pinterest",
    "trends",
    "explore",
    "login",
    "sign up",
    "business",
    "privacy",
    "cookies",
    "home",
}


@dataclass(frozen=True)
class NewsSignal:
    title: str
    source: str = ""
    published: str = ""


@dataclass(frozen=True)
class TrendCandidate:
    keyword: str
    domain: str
    cluster: str
    priority: str
    score: float
    pinterest_score: float
    google_news_hits: int
    google_news_titles: list[str]
    source: str


GoogleNewsProvider = Callable[[str, str, str, int], list[NewsSignal]]


def refresh_domain_trend_lists(
    domains: list[Domain],
    *,
    limit_per_domain: int = 10,
    region: str | None = None,
    language: str | None = None,
    append_to_roadmap: bool = True,
    pinterest_terms: list[str] | None = None,
    google_news_provider: GoogleNewsProvider | None = None,
    use_playwright: bool = True,
) -> dict[str, object]:
    """Create fresh daily trend shortlists for each domain.

    Returns a machine-readable report and writes:
    - ``data/domains/<handle>/daily_best_keywords.json``
    - ``data/domains/<handle>/daily_best_keywords.md``
    """

    region = (region or os.environ.get("RANKSTEIN_TRENDS_REGION") or DEFAULT_REGION).upper()
    language = (language or os.environ.get("RANKSTEIN_TRENDS_LANGUAGE") or DEFAULT_LANGUAGE).lower()
    limit_per_domain = max(1, limit_per_domain)
    google_news_provider = google_news_provider or fetch_google_news_signals

    generated_at = datetime.now(UTC).isoformat()
    report: dict[str, object] = {
        "generated_at": generated_at,
        "region": region,
        "language": language,
        "collector": "playwright_pinterest_trends" if use_playwright else "http_fallback",
        "domains": {},
    }

    for domain in domains:
        if pinterest_terms is not None:
            raw_terms = pinterest_terms
        elif use_playwright:
            raw_terms = fetch_pinterest_niche_trending_terms(
                domain, region=region, limit=limit_per_domain * 8
            )
        else:
            raw_terms = fetch_pinterest_trending_terms(region, limit=limit_per_domain * 8)
        normalized_terms = _dedupe_terms(raw_terms)
        if not normalized_terms:
            normalized_terms = fallback_seed_terms()
        candidates = rank_terms_for_domain(
            domain,
            normalized_terms,
            limit=limit_per_domain,
            region=region,
            language=language,
            google_news_provider=google_news_provider,
        )
        write_daily_best_list(domain, candidates, generated_at)
        added = 0
        if append_to_roadmap:
            title = f"{domain.display_name} Keyword Roadmap"
            added = append_keyword_rows(
                domain.keywords_file,
                title,
                [
                    KeywordRow(
                        keyword=item.keyword,
                        cluster=item.cluster,
                        source="Pinterest Trends + Google News",
                        target_blog=domain.display_name,
                        priority=item.priority,
                        status="Pending",
                    )
                    for item in candidates
                ],
            )
        report["domains"][domain.handle] = {
            "pinterest_terms_found": len(raw_terms),
            "terms_considered": len(normalized_terms),
            "daily_best": [asdict(item) for item in candidates],
            "roadmap_added": added,
            "output_json": str(domain.root / "daily_best_keywords.json"),
            "output_md": str(domain.root / "daily_best_keywords.md"),
        }

    return report


def fetch_pinterest_niche_trending_terms(
    domain: Domain,
    *,
    region: str = DEFAULT_REGION,
    limit: int = 80,
) -> list[str]:
    """Use Playwright to open Pinterest Trends/Search for domain-specific niche queries."""

    try:
        return _run_playwright_collector(domain, region, limit)
    except Exception as exc:
        logger.warning("Playwright Pinterest trend collection failed for %s: %s", domain.handle, exc)
        return fetch_pinterest_trending_terms(region, limit=limit)


def _run_playwright_collector(domain: Domain, region: str, limit: int) -> list[str]:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(_fetch_pinterest_niche_trending_terms_async(domain, region, limit))

    result: list[str] = []
    error: Exception | None = None

    def runner() -> None:
        nonlocal result, error
        try:
            result = asyncio.run(_fetch_pinterest_niche_trending_terms_async(domain, region, limit))
        except Exception as exc:  # pragma: no cover - defensive thread handoff
            error = exc

    thread = threading.Thread(target=runner, name="rankstein-pinterest-trends", daemon=True)
    thread.start()
    thread.join()
    if error is not None:
        raise error
    return result


async def _fetch_pinterest_niche_trending_terms_async(
    domain: Domain,
    region: str,
    limit: int,
) -> list[str]:
    from playwright.async_api import async_playwright

    session_dir = domain.sessions_dir
    if not session_dir.is_absolute():
        session_dir = PROJECT_ROOT / session_dir
    session_dir.mkdir(parents=True, exist_ok=True)

    queries = _pinterest_seed_queries(domain)
    collected: list[str] = []

    async with async_playwright() as p:
        browser = await p.firefox.launch_persistent_context(
            str(session_dir),
            headless=True,
            locale="es-ES",
            viewport={"width": 1365, "height": 1000},
            args=["--no-remote", "--allow-downgrade"],
            timeout=60000,
        )
        page = browser.pages[0] if browser.pages else await browser.new_page()
        for query in queries:
            if len(collected) >= limit:
                break
            collected.extend(await _collect_terms_from_pinterest_trends_page(page, query, region))
            if len(collected) < limit:
                collected.extend(await _collect_terms_from_pinterest_search_page(page, query))
        await browser.close()

    return _dedupe_terms(collected)[:limit]


async def _collect_terms_from_pinterest_trends_page(page, query: str, region: str) -> list[str]:
    encoded_query = urllib.parse.quote(query)
    urls = [
        f"https://trends.pinterest.com/?country={urllib.parse.quote(region)}&q={encoded_query}",
        f"https://trends.pinterest.com/search/?q={encoded_query}&country={urllib.parse.quote(region)}",
    ]
    terms: list[str] = []
    for url in urls:
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=60000)
            await page.wait_for_timeout(4000)
            await _try_pinterest_trends_search_box(page, query)
            terms.extend(await _visible_keyword_terms(page, query))
        except Exception as exc:
            logger.debug("Pinterest Trends page failed for %r at %s: %s", query, url, exc)
    return terms


async def _try_pinterest_trends_search_box(page, query: str) -> None:
    selectors = [
        'input[type="search"]',
        'input[placeholder*="Search" i]',
        'input[placeholder*="buscar" i]',
        'input[aria-label*="Search" i]',
        'input[aria-label*="buscar" i]',
    ]
    for selector in selectors:
        loc = page.locator(selector).first
        try:
            if await loc.count() > 0 and await loc.is_visible(timeout=1000):
                await loc.fill(query)
                await loc.press("Enter")
                await page.wait_for_timeout(4000)
                return
        except Exception as exc:
            logger.debug("Pinterest search box selector failed (%s): %s", selector, exc)
            continue


async def _collect_terms_from_pinterest_search_page(page, query: str) -> list[str]:
    try:
        await page.goto(
            f"https://www.pinterest.com/search/pins/?q={urllib.parse.quote(query)}",
            wait_until="domcontentloaded",
            timeout=60000,
        )
        await page.wait_for_timeout(5000)
        return await _visible_keyword_terms(page, query)
    except Exception as exc:
        logger.debug("Pinterest search page failed for %r: %s", query, exc)
        return []


async def _visible_keyword_terms(page, query: str) -> list[str]:
    payload = await page.evaluate(
        """() => {
            const values = [];
            const selectors = [
                '[data-test-id*="trend"]',
                '[data-test-id*="search"]',
                'a[href*="/search/"]',
                'a[href*="/pin/"]',
                'h1', 'h2', 'h3', 'button', 'span', 'div[role="button"]'
            ];
            for (const selector of selectors) {
                for (const el of document.querySelectorAll(selector)) {
                    const rect = el.getBoundingClientRect();
                    const style = getComputedStyle(el);
                    if (rect.width <= 0 || rect.height <= 0 || style.display === 'none' || style.visibility === 'hidden') {
                        continue;
                    }
                    const text = (el.innerText || el.getAttribute('aria-label') || el.getAttribute('title') || '').trim();
                    if (text.length >= 3 && text.length <= 120) values.push(text);
                    const href = el.getAttribute('href') || '';
                    if (href.includes('/search/')) values.push(decodeURIComponent(href));
                }
            }
            return values.slice(0, 300);
        }"""
    )
    terms: list[str] = []
    for item in payload:
        terms.extend(_extract_candidate_terms(str(item)))
    return terms


def fetch_pinterest_trending_terms(region: str = DEFAULT_REGION, *, limit: int = 80) -> list[str]:
    """HTTP fallback for Pinterest Trends when Playwright is unavailable."""

    token = os.environ.get("PINTEREST_ACCESS_TOKEN", "").strip()
    if token:
        api_terms = _fetch_pinterest_api_terms(region, token, limit)
        if api_terms:
            return api_terms

    terms = _fetch_pinterest_public_page_terms(region, limit)
    if terms:
        return terms

    logger.warning("Pinterest Trends scrape returned no terms; using seed fallback.")
    return []


def _fetch_pinterest_api_terms(region: str, token: str, limit: int) -> list[str]:
    """Best-effort official API path for accounts with Pinterest API access."""
    url = f"https://api.pinterest.com/v5/trends/keywords/{region}/top/growing"
    try:
        response = requests.get(
            url,
            headers={"Authorization": f"Bearer {token}", "User-Agent": USER_AGENT},
            params={"limit": min(limit, 50)},
            timeout=20,
        )
        if response.status_code >= 400:
            logger.warning("Pinterest Trends API returned HTTP %s", response.status_code)
            return []
        payload = response.json()
    except Exception as exc:
        logger.warning("Pinterest Trends API failed: %s", exc)
        return []

    terms = []
    for item in payload.get("items", payload if isinstance(payload, list) else []):
        if isinstance(item, str):
            terms.append(item)
        elif isinstance(item, dict):
            terms.append(str(item.get("keyword") or item.get("term") or item.get("name") or ""))
    return _dedupe_terms(terms)[:limit]


def _fetch_pinterest_public_page_terms(region: str, limit: int) -> list[str]:
    """Best-effort scrape of the public Pinterest Trends page."""
    url = f"{PINTEREST_TRENDS_URL}?country={urllib.parse.quote(region)}"
    try:
        response = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=25)
        response.raise_for_status()
    except Exception as exc:
        logger.warning("Pinterest Trends page request failed: %s", exc)
        return []

    soup = BeautifulSoup(response.text, "html.parser")
    text_blobs: list[str] = []
    for script in soup.find_all("script"):
        text = script.get_text(" ", strip=True)
        if any(marker in text.lower() for marker in ["trend", "keyword", "query"]):
            text_blobs.append(text)
    for tag in soup.find_all(["h1", "h2", "h3", "a", "button", "span", "div"]):
        text = tag.get_text(" ", strip=True)
        if 3 <= len(text) <= 80:
            text_blobs.append(text)

    terms: list[str] = []
    for blob in text_blobs:
        terms.extend(_extract_candidate_terms(blob))
    return _dedupe_terms(terms)[:limit]


def fetch_google_news_signals(
    keyword: str,
    language: str = DEFAULT_LANGUAGE,
    region: str = DEFAULT_REGION,
    limit: int = 5,
) -> list[NewsSignal]:
    query = urllib.parse.quote(f"{keyword} receta OR cocina OR food")
    url = f"https://news.google.com/rss/search?q={query}&hl={language}&gl={region}&ceid={region}:{language}"
    try:
        response = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=20)
        response.raise_for_status()
        root = ET.fromstring(response.content)
    except Exception as exc:
        logger.warning("Google News RSS failed for %r: %s", keyword, exc)
        return []

    signals: list[NewsSignal] = []
    for item in root.findall(".//item"):
        title = _clean_news_title(item.findtext("title", ""))
        if not title:
            continue
        source_node = item.find("source")
        signals.append(
            NewsSignal(
                title=title,
                source=source_node.text if source_node is not None and source_node.text else "",
                published=item.findtext("pubDate", ""),
            )
        )
        if len(signals) >= limit:
            break
    return signals


def rank_terms_for_domain(
    domain: Domain,
    terms: list[str],
    *,
    limit: int,
    region: str,
    language: str,
    google_news_provider: GoogleNewsProvider,
) -> list[TrendCandidate]:
    domain_tokens = _domain_tokens(domain)
    scored: list[TrendCandidate] = []
    for index, term in enumerate(terms):
        keyword = _normalize_keyword(term)
        if not keyword or len(keyword) < 4:
            continue
        if _is_generic_domain_seed(domain, keyword):
            continue
        if not _looks_food_relevant(keyword, domain_tokens):
            continue
        news = google_news_provider(keyword, language, region, 5)
        cluster = _cluster_for_keyword(domain, keyword)
        pinterest_score = max(1.0, 100.0 - index)
        relevance = _relevance_score(keyword, domain_tokens)
        news_score = min(25, len(news) * 5)
        score = pinterest_score + relevance + news_score
        scored.append(
            TrendCandidate(
                keyword=keyword,
                domain=domain.handle,
                cluster=cluster,
                priority=_priority(score),
                score=round(score, 2),
                pinterest_score=round(pinterest_score, 2),
                google_news_hits=len(news),
                google_news_titles=[item.title for item in news],
                source="Pinterest Trends + Google News",
            )
        )

    scored.sort(key=lambda item: item.score, reverse=True)
    return scored[:limit]


def write_daily_best_list(domain: Domain, candidates: list[TrendCandidate], generated_at: str) -> None:
    domain.root.mkdir(parents=True, exist_ok=True)
    json_path = domain.root / "daily_best_keywords.json"
    md_path = domain.root / "daily_best_keywords.md"
    payload = {
        "generated_at": generated_at,
        "domain": domain.handle,
        "items": [asdict(item) for item in candidates],
    }
    json_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    lines = [
        f"# Daily Best Keywords - {domain.display_name}",
        "",
        f"Generated: {generated_at}",
        "",
        "| Keyword | Cluster | Priority | Score | Google News Hits |",
        "|---|---|---|---:|---:|",
    ]
    for item in candidates:
        lines.append(
            f"| {item.keyword} | {item.cluster} | {item.priority} | "
            f"{item.score:.2f} | {item.google_news_hits} |"
        )
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def fallback_seed_terms() -> list[str]:
    return [
        "postres faciles",
        "tarta de queso",
        "recetas saludables",
        "aperitivos faciles",
        "cenas rapidas",
        "pasteles de chocolate",
        "ensaladas frescas",
        "recetas con freidora de aire",
        "galletas caseras",
        "helados artesanales",
        "comida española",
        "recetas para invitados",
    ]


def _pinterest_seed_queries(domain: Domain) -> list[str]:
    """Build niche searches that Pinterest Trends/Search can expand into live ideas."""

    niche = domain.niche.casefold()
    queries: list[str] = []
    for category in domain.categories:
        queries.extend([category, f"{category} recetas", f"{category} ideas"])

    if any(marker in niche for marker in ["pasteler", "postre", "reposter", "dulce"]):
        queries.extend(
            [
                "postres gourmet",
                "tarta de queso",
                "pasteles elegantes",
                "reposteria fina",
                "galletas caseras",
                "helados artesanales",
                "chocolate recetas",
            ]
        )
    if any(marker in niche for marker in ["saludable", "espanol", "español", "tradicional", "receta"]):
        queries.extend(
            [
                "recetas saludables",
                "recetas espanolas",
                "cenas rapidas",
                "aperitivos faciles",
                "ensaladas frescas",
                "recetas de temporada",
                "freidora de aire recetas",
            ]
        )

    queries.extend(["recetas virales", "recetas faciles", "ideas de comida", domain.display_name])
    return _dedupe_terms(queries)[:12]


def _extract_candidate_terms(text: str) -> list[str]:
    terms = re.findall(r'"(?:keyword|term|query|name|label)"\s*:\s*"([^"]{3,80})"', text, re.I)
    terms.extend(re.findall(r"\b[a-záéíóúñü][a-záéíóúñü ]{3,58}\b", text, re.I))
    return terms


def _dedupe_terms(terms: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for term in terms:
        keyword = _normalize_keyword(term)
        if not keyword or keyword.casefold() in seen or keyword.casefold() in NOISE_TERMS:
            continue
        seen.add(keyword.casefold())
        result.append(keyword)
    return result


def _normalize_keyword(term: str) -> str:
    term = BeautifulSoup(term or "", "html.parser").get_text(" ", strip=True)
    term = urllib.parse.unquote(term)
    term = re.sub(r"\s+", " ", term).strip(" -_.,:;|")
    if len(term.split()) > 8:
        return ""
    return term


def _clean_news_title(title: str) -> str:
    title = BeautifulSoup(title or "", "html.parser").get_text(" ", strip=True)
    return re.sub(r"\s+-\s+[^-]+$", "", title).strip()


def _domain_tokens(domain: Domain) -> set[str]:
    text = " ".join([domain.niche, domain.display_name, *domain.categories]).casefold()
    return {token for token in re.findall(r"[a-záéíóúñü]{4,}", text) if token}


def _looks_food_relevant(keyword: str, domain_tokens: set[str]) -> bool:
    food_markers = {
        "receta",
        "recetas",
        "cocina",
        "postre",
        "postres",
        "tarta",
        "pastel",
        "galleta",
        "chocolate",
        "helado",
        "aperitivo",
        "ensalada",
        "carne",
        "pescado",
        "saludable",
        "cena",
        "comida",
    }
    tokens = set(re.findall(r"[a-záéíóúñü]{4,}", keyword.casefold()))
    return bool(tokens & (food_markers | domain_tokens))


def _is_generic_domain_seed(domain: Domain, keyword: str) -> bool:
    lower = keyword.casefold().strip()
    generic = {domain.display_name.casefold(), domain.handle.casefold()}
    generic.update(category.casefold() for category in domain.categories)
    return lower in generic


def _cluster_for_keyword(domain: Domain, keyword: str) -> str:
    lower = keyword.casefold()
    for category in domain.categories:
        if category.casefold() in lower:
            return category
    category_aliases = {
        "Postres": ["postre", "tarta", "dulce", "crema"],
        "Pasteles": ["pastel", "bizcocho", "cake"],
        "Galletas": ["galleta", "cookie"],
        "Chocolates": ["chocolate", "cacao"],
        "Helados": ["helado", "sorbete"],
        "Aperitivos": ["aperitivo", "tapa", "canape", "entrante"],
        "Ensaladas": ["ensalada"],
        "Carnes": ["carne", "pollo", "ternera"],
        "Pescados": ["pescado", "atun", "salmon", "merluza"],
    }
    for category in domain.categories:
        if any(alias in lower for alias in category_aliases.get(category, [])):
            return category
    return domain.categories[0] if domain.categories else "General"


def _relevance_score(keyword: str, domain_tokens: set[str]) -> float:
    tokens = set(re.findall(r"[a-záéíóúñü]{4,}", keyword.casefold()))
    return float(len(tokens & domain_tokens) * 12)


def _priority(score: float) -> str:
    if score >= 120:
        return "High"
    if score >= 90:
        return "Medium"
    return "Low"
