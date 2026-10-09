"""
Multi-layer hero image sourcing pipeline for RankStein.

Provides production hero images through a strict three-tier fallback hierarchy:
  1. Primary (Tier 1): Codex native image generation (OpenAI gpt-image-2 via Hermes gateway)
  2. Fallback (Tier 2): Scraped recipe/food images from allowlisted culinary sources
  3. Fallback (Tier 3): Pollinations AI image generation (flux model)

Fails closed if all providers fail; programmatic placeholders are never returned.
"""

from __future__ import annotations

import logging
import os
import random
import time
import urllib.parse
from pathlib import Path

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger("rankstein.hero_image")

# --- Constants ---
OUTPUT_DIR = Path(__file__).resolve().parent.parent.parent / "nanobanana-output"
MIN_WIDTH = 800
MIN_HEIGHT = 600
MIN_BYTES = 5000
TIMEOUT = 30

# Layer 1 domains we trust for recipe/food / cooking articles.
# Any image source outside this set is rejected and we fall through.
SCRAPE_DOMAIN_ALLOWLIST = {
    "okdiario.com",
    "cookpad.com",
    "gastronomiavasca.com",
    "tasteofhome.com",
    "bbcgoodfood.com",
    "directoalpaladar.com",
    "pepepomares.es",
    "elcomidista.elpais.com",
    "comidaparaalimentar.com",
    "pequeocio.com",
    "recetasderechupete.com",
    "recetasgratis.net",
    "comida-italiana.net",
    "divinacocina.com",
    "larecetafacil.com",
    "kicpc.es",
    "elenadearaya.com",
    "comidasexpress.com",
    "tapasymas.net",
    "cookidoo.es",
    "yorkfood.es",
    "hogarmania.com",
    "keto.cookedbest.com",
    "plan-recetas.com",
    "recetasdemama.es",
    "tudecides.com",
    "tinarecetasfaciles.com",
    "recetasdepan.com",
    "miscomidasfaciles.com",
    "foodandwine.com",
    "seriouseats.com",
    "bonappetit.com",
    "elespanol.com",
    "elmundo.es",
    "elpais.com",
    "lavanguardia.com",
    "abc.es",
    "20minutos.es",
    "huffingtonpost.es",
    "tipsfarma.es",
    "madrid.es",
    "semana.com",
    "hola.com",
    "muyinteresante.es",
    "quo.es",
    "nationalgeographic.com.es",
    "tripadvisor.es",
    "cocina-familiar.com",
    "comidarapida.org",
    "gastronomiavegana.es",
    "recetasdelchef.com",
    "recetasfit.com",
    "recetasdepasteles.com",
    "recetasdesopa.com",
    "comidahoy.net",
    "cocinaconmaria.com",
    "elmenudefamilia.es",
    "recetasaludable.net",
    "cocinacasera.website",
    "recetasdehoy.com",
    "tapasybocados.es",
    "elplato.news",
    "lacocinadesiempre.com",
    "cookingclassy.com",
    "spendwithpennies.com",
    "jocooks.com",
    "simplyrecipes.com",
    "thespruceeats.com",
    "bbc.com",
    "nytimes.com",
    "recetaslidereztu.com",
    "gastronomiavasca.es",
}

# Own domains / social platforms we never want to use for scraped hero images.
NEVER_SCRAPE_DOMAINS = {
    "recetadolce.com",
    "recetagenial.com",
    "youtube.com",
    "facebook.com",
    "instagram.com",
    "pinterest.com",
    "twitter.com",
    "tiktok.com",
}

_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:132.0) Gecko/20100101 Firefox/132.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_7) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/18.1 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
]

_SESSION = requests.Session()
_SESSION.headers.update({"Accept-Language": "es-ES,es;q=0.9,en;q=0.8"})


def _random_ua() -> str:
    return random.choice(_USER_AGENTS)


def _slug_to_filename(slug: str, suffix: str = "hero") -> str:
    """Sanitize slug to a safe filename."""
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in slug)
    return f"{safe}-{suffix}.jpg"


def _validate_image_dimensions(path: str) -> dict:
    """Check image dimensions, return {valid, width, height}."""
    try:
        from PIL import Image

        with Image.open(path) as img:
            w, h = img.size
        if w < MIN_WIDTH or h < MIN_HEIGHT:
            logger.warning(
                "Image too small: %dx%d (min %dx%d): %s",
                w,
                h,
                MIN_WIDTH,
                MIN_HEIGHT,
                path,
            )
            return {"valid": False, "width": w, "height": h, "reason": "too_small"}
        return {"valid": True, "width": w, "height": h}
    except Exception as exc:
        logger.warning("Dimension check failed for %s: %s", path, exc)
        return {"valid": False, "reason": str(exc)}


def _save_image_from_response(response: requests.Response, slug: str, suffix: str = "hero") -> dict:
    """Save HTTP response bytes as a validated JPEG image."""
    filename = _slug_to_filename(slug, suffix)
    out_path = OUTPUT_DIR / filename
    os.makedirs(str(OUTPUT_DIR), exist_ok=True)

    raw = response.content
    if len(raw) < MIN_BYTES:
        return {"success": False, "error": f"too small: {len(raw)} bytes"}

    is_jpeg = raw[:3] in (b"\xff\xd8\xff",)
    try:
        if is_jpeg:
            out_path.write_bytes(raw)
        else:
            import io

            from PIL import Image

            img = Image.open(io.BytesIO(raw))
            if img.mode != "RGB":
                img = img.convert("RGB")
            img.save(str(out_path), "JPEG", quality=95)
        size = out_path.stat().st_size
    except Exception as exc:
        logger.warning("Save image failed: %s", exc)
        return {"success": False, "error": str(exc)}

    dims = _validate_image_dimensions(str(out_path))
    if not dims.get("valid"):
        try:
            out_path.unlink()
        except OSError:
            pass
        return {"success": False, "error": dims.get("reason", "invalid dimensions")}

    return {
        "success": True,
        "output_path": str(out_path),
        "format": "jpg",
        "size_bytes": size,
        "width": dims.get("width", 0),
        "height": dims.get("height", 0),
    }


def _download_image(url: str, slug: str, suffix: str = "hero") -> dict:
    """Download an image from a URL and save to nanobanana-output."""
    try:
        resp = _SESSION.get(
            url,
            headers={"User-Agent": _random_ua()},
            timeout=TIMEOUT,
        )
        resp.raise_for_status()
        return _save_image_from_response(resp, slug, suffix)
    except Exception as exc:
        logger.debug("Download failed for %s: %s", url, exc)
        return {"success": False, "error": str(exc)}


# ============================= Layer 1 =============================

_FOOD_WORDS = [
    "receta",
    "recetas",
    "pastel",
    "galleta",
    "tarta",
    "ensalada",
    "arroz",
    "paella",
    "croqueta",
    "horno",
    "puchero",
    "plato",
    "menú",
    "postre",
    "cocina",
    "sopa",
    "pasta",
    "pizza",
    "pan",
    "pollo",
    "pescado",
    "solomillo",
    "jamón",
    "queso",
    "chocolate",
    "helado",
    "café",
    "fruta",
    "verdura",
    "carne",
    "marisco",
    "croqueta",
    "empanada",
    "tortilla",
    "natillas",
    "flan",
    "yogur",
    "lechazo",
    "pulpo",
    "gambas",
    "alioli",
    "gazpacho",
    "salmorejo",
    "fideuá",
    "chuletón",
    "entrecot",
    "pulpo",
]


def _looks_foodish(url: str, candidate_text: str) -> bool:
    joined = f"{url} {candidate_text}".lower()
    return any(token in joined for token in _FOOD_WORDS)


def _is_allowed_scrape_domain(url: str) -> bool:
    parsed = urllib.parse.urlparse(url)
    host = parsed.netloc.lower().replace("www.", "")
    if host in NEVER_SCRAPE_DOMAINS:
        return False
    if host in SCRAPE_DOMAIN_ALLOWLIST:
        return True
    return False


def scrape_hero_from_news(keyword: str, slug: str) -> dict:
    """Scrape images from trusted recipe/cooking article sources only."""
    try:
        from rankstein_mcp_server import scrape_news_sources

        sources = scrape_news_sources(keyword, language="es", count=8)
        if not sources.get("success") or not sources.get("articles"):
            logger.info("No news sources for %s — skipping scrape fallback", keyword)
            return {"success": False, "error": "no_news_sources"}

        articles = sources["articles"]
        logger.info(
            "Layer 1: %d articles for %s (allowlisted sources only)",
            len(articles),
            keyword,
        )

        for article in articles:
            url = article.get("url") or article.get("link", "")
            if not url:
                continue
            if not _is_allowed_scrape_domain(url):
                continue

            try:
                result = _extract_image_from_article(url, slug, keyword=keyword)
                if result.get("success"):
                    logger.info(
                        "Layer 1: trusted source hero for %s from %s -> %s",
                        keyword,
                        url,
                        result.get("output_path"),
                    )
                    return result
            except Exception as exc:
                logger.debug("Layer 1: skipped %s: %s", url, exc)
                continue

        logger.info("Layer 1: no trusted food hero found for %s", keyword)
        return {"success": False, "error": "no_trusted_food_image_from_sources"}
    except Exception as exc:
        logger.warning("Layer 1: news scrape failed for %s: %s", keyword, exc)
        return {"success": False, "error": str(exc)}


def _extract_image_from_article(article_url: str, slug: str, keyword: str = "") -> dict:
    """Visit an article URL and extract the best trusted food/recipe hero image.

    Priority:
      1. og:image from a trusted food page context
      2. twitter:image from a trusted food page context
      3. first large image from <article>/<main> that matches food heuristic

    Operational update 2026-06-05: allowlisted domains are now trusted
    to carry real food photography even when image URLs themselves are generic
    CDN paths. Food heuristic is applied only as a tie-breaker alongside page
    context, not as a hard reject on image URL alone.
    """
    try:
        resp = _SESSION.get(
            article_url,
            headers={"User-Agent": _random_ua()},
            timeout=TIMEOUT,
        )
        resp.raise_for_status()

        soup = BeautifulSoup(resp.text, "lxml")

        domain_ok = _is_allowed_scrape_domain(article_url)

        def foodish(text: str) -> bool:
            return _looks_foodish(article_url, text)

        def _ok_candidate(img_url: str, page_text: str = "") -> bool:
            lower = img_url.lower().replace("www.", "")
            if any(token in lower for token in ("pixel", "track", "analytics", "1x1", "spacer")):
                return False
            if domain_ok:
                return True
            return foodish(img_url) or foodish(page_text)

        og_img = soup.find("meta", property="og:image") or soup.find("meta", attrs={"name": "og:image"})
        if og_img and og_img.get("content"):
            img_url = og_img["content"].strip()
            if img_url.startswith("//"):
                img_url = "https:" + img_url
            if img_url.startswith("/"):
                parsed = urllib.parse.urlparse(article_url)
                img_url = f"{parsed.scheme}://{parsed.netloc}{img_url}"
            if img_url.startswith(("http://", "https://")) and _ok_candidate(img_url, resp.text):
                result = _download_image(img_url, slug)
                if result.get("success"):
                    return result

        tw_img = soup.find("meta", attrs={"name": "twitter:image"})
        if tw_img and tw_img.get("content"):
            img_url = tw_img["content"].strip()
            if _ok_candidate(img_url, resp.text):
                result = _download_image(img_url, slug)
                if result.get("success"):
                    return result

        container = soup.find("article") or soup.find("main") or soup.find("body")
        if container:
            seen = set()
            for img in container.find_all("img"):
                src = img.get("src") or img.get("data-src") or ""
                if not src:
                    continue
                if src in seen:
                    continue
                seen.add(src)
                if src.startswith("//"):
                    src = "https:" + src
                if src.startswith("/"):
                    parsed = urllib.parse.urlparse(article_url)
                    src = f"{parsed.scheme}://{parsed.netloc}{src}"
                if not src.startswith(("http://", "https://")):
                    continue
                w = img.get("width")
                if w and w.isdigit() and int(w) < 300:
                    continue
                alt = (img.get("alt") or "").strip()
                page_context = f"{alt} {resp.text}"
                if _ok_candidate(src, page_context):
                    result = _download_image(src, slug)
                    if result.get("success"):
                        return result

        return {"success": False, "error": "no_acceptable_food_image_on_page"}
    except Exception as exc:
        logger.debug("Extract image from %s failed: %s", article_url, exc)
        return {"success": False, "error": str(exc)}


# ============================= Layer 2 =============================


def _pollinations_stealth_request(
    prompt: str,
    slug: str,
    model: str = "flux",
    width: int = 1280,
    height: int = 960,
    seed: int = 0,
    enhance: bool = True,
    safe: bool = True,
) -> dict:
    """Make a single Pollinations request with stealth headers and timing."""
    delay = random.uniform(0.5, 2.5)
    time.sleep(delay)

    encoded = urllib.parse.quote(prompt, safe="")

    params_parts = [
        f"width={width}",
        f"height={height}",
        f"model={model}",
    ]
    if enhance:
        params_parts.append("enhance=true")
    if seed > 0:
        params_parts.append(f"seed={seed}")
    if not safe:
        params_parts.append("safe=false")

    params = "&".join(params_parts)
    url = f"https://image.pollinations.ai/prompt/{encoded}?{params}"

    headers = {
        "User-Agent": _random_ua(),
        "Accept": "image/jpeg,image/png,*/*;q=0.8",
        "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
        "Referer": "https://pollinations.ai/",
    }

    try:
        resp = _SESSION.get(url, headers=headers, timeout=120, stream=True)
        if resp.status_code == 429:
            logger.warning("Pollinations rate-limited; will fallback to Layer 3")
            return {"success": False, "error": "rate_limited"}
        resp.raise_for_status()
        return _save_image_from_response(resp, slug, suffix="hero")
    except Exception as exc:
        logger.debug("Pollinations request failed: %s", exc)
        return {"success": False, "error": str(exc)}


# ============================= Layer 3 =============================


def _pillow_fallback(slug: str) -> dict:
    try:
        from PIL import Image, ImageDraw, ImageFont
    except Exception as exc:
        logger.warning("Pillow fallback unavailable: %s", exc)
        return {"success": False, "error": str(exc)}

    width, height = 1280, 960
    img = Image.new("RGB", (width, height), color=(245, 240, 230))
    draw = ImageDraw.Draw(img)

    try:
        font_path = "arial.ttf"
        title_font = ImageFont.truetype(font_path, 64)
        body_font = ImageFont.truetype(font_path, 36)
    except Exception:
        title_font = ImageFont.load_default()
        body_font = ImageFont.load_default()

    text = "Receta del día"
    bbox = draw.textbbox((0, 0), text, font=title_font)
    text_width = bbox[2] - bbox[0]
    draw.text(((width - text_width) // 2, height // 2 - 40), text, fill=(60, 40, 20), font=title_font)

    sub = slug.replace("-", " ").title()
    bbox = draw.textbbox((0, 0), sub, font=body_font)
    text_width = bbox[2] - bbox[0]
    draw.text(((width - text_width) // 2, height // 2 + 20), sub, fill=(90, 70, 50), font=body_font)

    filename = _slug_to_filename(slug, "hero")
    out_path = OUTPUT_DIR / filename
    img.save(str(out_path), "JPEG", quality=92)
    return {
        "success": True,
        "output_path": str(out_path),
        "format": "jpg",
        "size_bytes": out_path.stat().st_size,
        "width": width,
        "height": height,
        "source": "pillow",
    }


# ============================= Orchestrator =============================


def get_hero_image(
    keyword: str,
    slug: str,
    domain_handle: str = "",
    image_prompt: str | None = None,
) -> dict:
    os.makedirs(str(OUTPUT_DIR), exist_ok=True)

    prompt = (image_prompt or "").strip()
    if not prompt:
        return {
            "success": False,
            "error": "Production hero generation requires a recipe-aware image prompt",
            "source": "none",
            "provider": "none",
            "domain": domain_handle or "",
        }

    from rankstein_mcp_server import create_hero_image_codex

    # --- Tier 1 (Primary): Codex native image generation ---
    codex = create_hero_image_codex(
        prompt=prompt,
        slug=slug,
        suffix="hero",
        aspect="landscape",
        quality=os.environ.get("RANKSTEIN_CODEX_IMAGE_QUALITY", "medium"),
    )
    if codex.get("success"):
        result = dict(codex)
        result["source"] = "codex"
        result.setdefault("provider", "codex")
        result["domain"] = domain_handle or ""
        return result

    logger.warning(
        "Codex hero generation failed for %s: %s. Attempting Tier 2 (scraped recipe images)...",
        keyword,
        codex.get("error"),
    )

    # --- Tier 2 (Fallback 1): Scraped recipe/food image from allowlisted culinary sources ---
    scraped = scrape_hero_from_news(keyword, slug)
    if scraped.get("success"):
        result = dict(scraped)
        result["source"] = "scraped"
        result.setdefault("provider", "scraped")
        result["domain"] = domain_handle or ""
        logger.info(
            "Scraped hero fallback succeeded for %s: %s",
            keyword,
            result.get("output_path"),
        )
        return result

    logger.warning(
        "Scraped hero fallback failed for %s: %s. Attempting Tier 3 (Pollinations AI)...",
        keyword,
        scraped.get("error"),
    )

    # --- Tier 3 (Fallback 2): Pollinations AI image generation ---
    if os.environ.get("RANKSTEIN_DISABLE_POLLINATIONS", "").lower() in ("1", "true"):
        logger.warning("Pollinations hero generation is disabled per policy. Failing closed without Tier 3.")
        return {
            "success": False,
            "error": (
                f"All approved hero generation options failed (Codex: {codex.get('error', 'unknown error')}, "
                f"Scraped: {scraped.get('error', 'unknown error')}; Pollinations disabled by policy)"
            ),
            "source": "failed",
            "provider": "failed",
            "domain": domain_handle or "",
        }

    pollinations = create_hero_image_pollinations(
        keyword=keyword,
        domain=domain_handle,
        prompt=prompt,
        slug=slug,
    )
    if pollinations.get("success"):
        result = dict(pollinations)
        result["source"] = "pollinations"
        result.setdefault("provider", "pollinations")
        result["domain"] = domain_handle or ""
        logger.info(
            "Pollinations hero fallback succeeded for %s: %s",
            keyword,
            result.get("output_path"),
        )
        return result

    logger.error("All hero generation providers failed for %s", keyword)
    return {
        "success": False,
        "error": (
            f"All hero generation options failed (Codex: {codex.get('error', 'unknown error')}, "
            f"Scraped: {scraped.get('error', 'unknown error')}, "
            f"Pollinations: {pollinations.get('error', 'unknown error')})"
        ),
        "source": "failed",
        "provider": "failed",
        "domain": domain_handle or "",
    }


def create_hero_image_pollinations(
    keyword: str,
    domain: object = "",
    prompt: str = "",
    slug: str = "",
) -> dict:
    d_handle = getattr(domain, "handle", str(domain))
    eff_slug = slug or keyword.replace(" ", "-")
    eff_prompt = prompt or f"Photorealistic editorial food photography of {keyword}, high quality"
    try:
        from rankstein_mcp_server import create_hero_image_pollinations as _mcp_pollinations

        res = _mcp_pollinations(
            prompt=eff_prompt,
            slug=eff_slug,
            suffix="hero",
            width=1920,
            height=1280,
            model="flux",
            enhance=True,
            upscale_if_smaller=True,
        )
        if res.get("success"):
            res["source"] = "pollinations"
            res["provider"] = "pollinations"
            res["domain"] = d_handle
            return res
    except Exception as exc:
        logger.warning("MCP pollinations call failed: %s, falling back to stealth request", exc)

    res = _pollinations_stealth_request(eff_prompt, eff_slug, model="flux")
    if res.get("success"):
        res["source"] = "pollinations"
        res["provider"] = "pollinations"
        res["domain"] = d_handle
    return res
