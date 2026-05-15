"""RankStein — Web Scraper Service
URL scraping, Google autocomplete, keyword metrics with SSRF protection.
"""

from __future__ import annotations

import asyncio
import ipaddress
import json
import logging
import urllib.parse

import httpx
from bs4 import BeautifulSoup

logger = logging.getLogger("rankstein.scraper")
_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
]


def _is_url_safe(url: str) -> bool:
    """Block private IPs, localhost, and cloud metadata endpoints."""
    try:
        parsed = urllib.parse.urlparse(url)
        hostname = parsed.hostname or ""
        blocked = ("localhost", "127.0.0.1", "0.0.0.0", "::1", "169.254.169.254")
        if hostname.lower() in blocked:
            return False
        try:
            ip = ipaddress.ip_address(hostname)
            if ip.is_private or ip.is_loopback or ip.is_link_local:
                return False
        except ValueError:
            pass
        return True
    except Exception:
        return False


async def scrape_onpage(url: str, max_length: int = 50000) -> dict:
    """Extract SEO data from a URL with SSRF protection."""
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    if not _is_url_safe(url):
        return {"success": False, "error": "URL blocked for security (private/internal address)"}

    headers = {
        "User-Agent": _USER_AGENTS[0],
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }
    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=15) as client:
            resp = await client.get(url, headers=headers)
            resp.raise_for_status()
            html = resp.text[:max_length]
            soup = BeautifulSoup(html, "html.parser")
            title = soup.title.string.strip() if soup.title and soup.title.string else ""
            meta_desc_tag = soup.find("meta", attrs={"name": "description"})
            meta_desc = (
                meta_desc_tag["content"].strip()
                if meta_desc_tag and meta_desc_tag.has_attr("content")
                else ""
            )
            headings = {
                f"h{i}": [t.get_text(strip=True) for t in soup.find_all(f"h{i}") if t.get_text(strip=True)]
                for i in range(1, 7)
            }
            images = soup.find_all("img")
            domain_core = urllib.parse.urlparse(url).netloc.replace("www.", "")
            internal = sum(
                1
                for a in soup.find_all("a")
                if (a.get("href", "") or "").startswith("/") or domain_core in (a.get("href", "") or "")
            )
            external = sum(
                1
                for a in soup.find_all("a")
                if (a.get("href", "") or "").startswith("http")
                and domain_core not in (a.get("href", "") or "")
            )
            text = soup.get_text(separator=" ", strip=True)
            styles = soup.find_all("style")
            css_text = " ".join(s.get_text() for s in styles)
            import re

            hex_colors = list(set(re.findall(r"#(?:[0-9a-fA-F]{3}){1,2}\b", css_text)))
            return {
                "success": True,
                "url": url,
                "title": title,
                "meta_description": meta_desc,
                "headings": headings,
                "word_count": len(text.split()),
                "images": {
                    "total": len(images),
                    "with_alt": sum(1 for i in images if i.get("alt")),
                    "missing_alt": sum(1 for i in images if not i.get("alt")),
                },
                "links": {"internal": internal, "external": external},
                "colors_found": hex_colors[:15],
                "raw_html_snippet": html[:2000],
            }
    except Exception as e:
        return {"success": False, "error": str(e)}


async def get_google_autocomplete(query: str) -> list:
    """Fetch Google Autocomplete suggestions."""
    url = f"https://suggestqueries.google.com/complete/search?client=chrome&q={urllib.parse.quote(query)}"
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get(url)
            if resp.status_code == 200:
                data = json.loads(resp.text)
                return data[1] if len(data) > 1 else []
    except Exception:
        pass
    return []


async def estimate_keyword_metrics(seed: str, niche: str = "General") -> dict:
    """Gather keyword data from Google Autocomplete with heuristic metrics."""
    suggestions = await get_google_autocomplete(seed)
    modifiers = ["how", "best", "vs", "why", "top"]
    tasks = [get_google_autocomplete(f"{mod} {seed}") for mod in modifiers]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    long_tails = []
    for r in results:
        if isinstance(r, list):
            long_tails.extend(r)
    all_suggestions = list(set([s.lower() for s in suggestions + long_tails if s]))
    import random

    def calc_metrics(kw: str, is_seed: bool = False) -> dict:
        wc = len(kw.split())
        if is_seed:
            vol, kd = random.randint(5000, 25000), random.randint(60, 85)
        else:
            vol = max(10, int(10000 / (wc**2)) + random.randint(-50, 500))
            kd = max(5, 80 - (wc * 12) + random.randint(-5, 5))
        intent = (
            "informational"
            if any(w in kw for w in ["how", "what", "why", "guide"])
            else "transactional"
            if any(w in kw for w in ["buy", "best", "cheap"])
            else "navigational"
        )
        return {"keyword": kw, "volume": vol, "difficulty": kd, "intent": intent}

    keyword_data = [calc_metrics(seed, is_seed=True)] + [
        calc_metrics(s) for s in all_suggestions[:25] if s != seed
    ]
    keyword_data.sort(key=lambda x: x["volume"], reverse=True)
    clusters = [{"theme": f"{seed} basics", "keywords": keyword_data[1:6]}]
    long_tail = [k for k in keyword_data if len(k["keyword"].split()) > 3][:10]
    questions = [k for k in keyword_data if any(w in k["keyword"] for w in ["how", "what", "why"])][:10]
    return {
        "seed": seed,
        "clusters": clusters,
        "long_tail": long_tail,
        "questions": questions,
        "trending": keyword_data[6:10],
    }
