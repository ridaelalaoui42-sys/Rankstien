"""Generate fresh remastered Pinterest pins for all Live articles.

Pulls Live keywords from keyword roadmaps, generates hero images via Pollinations,
applies luxury overlay with domain branding, and saves to data/media/remaster_final/.

Usage: python scripts/ops/generate_campaign_pins.py [--limit N] [--domain HANDLE]
"""

import logging
import re
import sys
import unicodedata
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("CampaignPins")

REMASTER_DIR = PROJECT_ROOT / "data" / "media" / "remaster_final"
REMASTER_DIR.mkdir(parents=True, exist_ok=True)


def slugify(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text)
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", "-", ascii_text.lower()).strip("-")


def get_live_keywords() -> list[dict]:
    """Read all Live keywords from domain keyword roadmaps."""
    from rankstein.domain import get_registry, reload_registry

    reload_registry()
    registry = get_registry()

    results = []
    junk_patterns = re.compile(
        r"pin page|Nestl|many different|sweet berry|Assorted|including cream|"
        r"Recetas que realmente|Cocina Abierta|El Mejor Pastel|El Secreto|"
        r"aperitivos que se hacen en"
    )

    for domain in registry.all():
        kf = domain.keywords_file
        if not kf or not kf.exists():
            continue
        for line in kf.read_text(encoding="utf-8").splitlines():
            if "| Live |" not in line or not line.startswith("|"):
                continue
            parts = [p.strip() for p in line.split("|") if p.strip()]
            if len(parts) < 2 or parts[0] in ("Keyword", "---"):
                continue
            kw = parts[0]
            if len(kw) < 6 or junk_patterns.search(kw):
                continue
            results.append(
                {
                    "keyword": kw,
                    "cluster": parts[1] if len(parts) > 1 else "",
                    "domain": domain,
                    "slug": slugify(kw),
                }
            )
    return results


def generate_hero_image(keyword: str, slug: str, timeout: int = 90, max_retries: int = 4) -> str | None:
    """Generate a hero image via Pollinations API with exponential backoff."""
    import time
    from urllib.parse import quote

    import requests

    prompt = (
        f"editorial food photography of {keyword}, Spanish recipe, premium plating, "
        "natural window light, clean marble table, appetizing texture, warm tones, "
        "no text, no watermark, no logo, professional studio quality, 16:9"
    )
    url = f"https://image.pollinations.ai/prompt/{quote(prompt)}?width=1280&height=960&nologo=true&seed={hash(slug) % 999999}"

    output_path = REMASTER_DIR / f"hero_{slug}.jpg"
    if output_path.exists():
        logger.info("Hero already exists: %s", output_path.name)
        return str(output_path)

    backoff = 30  # seconds
    for attempt in range(max_retries + 1):
        try:
            resp = requests.get(url, timeout=timeout, stream=True)
            if resp.status_code == 200 and len(resp.content) > 5000:
                output_path.write_bytes(resp.content)
                logger.info("Generated hero: %s (%d KB)", output_path.name, len(resp.content) // 1024)
                return str(output_path)
            elif resp.status_code == 402 and attempt < max_retries:
                logger.warning(
                    "Pollinations 402 rate limit for %s — backing off %ds (attempt %d/%d)",
                    keyword,
                    backoff,
                    attempt + 1,
                    max_retries,
                )
                time.sleep(backoff)
                backoff = min(backoff * 2, 300)  # max 5 min
                continue
            else:
                logger.warning("Pollinations returned %d for %s", resp.status_code, keyword)
                return None
        except Exception as e:
            if attempt < max_retries:
                logger.warning("Hero generation error for %s, retrying in %ds: %s", keyword, backoff, e)
                time.sleep(backoff)
                backoff = min(backoff * 2, 300)
                continue
            logger.warning("Hero generation failed for %s after %d attempts: %s", keyword, max_retries, e)
            return None
    return None


def create_pin_image(hero_path: str, title: str, brand: str, style: str = "classic") -> str | None:
    """Apply luxury overlay to create a Pinterest pin image (1000x1500)."""
    try:
        from rankstein_mcp_server import create_article_pin

        result = create_article_pin(
            hero_image_path=hero_path,
            title_text=title,
            brand=brand,
            style_variant=style,
        )
        if result.get("success"):
            logger.info("Pin created: %s", result["output_path"])
            return result["output_path"]
        else:
            logger.warning("Pin creation failed: %s", result)
            return None
    except Exception as e:
        logger.warning("Pin creation error: %s", e)
        return None


def move_to_remaster(pin_path: str, slug: str, domain_handle: str) -> str:
    """Move/copy final pin to remaster_final with proper naming."""
    src = Path(pin_path)
    from datetime import datetime as _dt

    day = _dt.now().strftime("%Y-%m-%d")
    target_dir = REMASTER_DIR / domain_handle / day / slug
    target_dir.mkdir(parents=True, exist_ok=True)
    dst = target_dir / f"remastered_v4_{domain_handle}_{slug}.jpg"
    if src.exists():
        import shutil

        shutil.copy2(str(src), str(dst))
        logger.info("Saved to remaster_final: %s", dst)
        return str(dst)
    return ""


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Generate campaign pins for Live articles")
    parser.add_argument("--limit", type=int, default=0, help="Max pins to generate (0=all)")
    parser.add_argument("--domain", type=str, default="", help="Filter by domain handle")
    parser.add_argument(
        "--styles", type=str, default="classic,dark,warm", help="Comma-separated style variants"
    )
    args = parser.parse_args()

    keywords = get_live_keywords()
    if args.domain:
        keywords = [k for k in keywords if k["domain"].handle == args.domain]
    if args.limit:
        keywords = keywords[: args.limit]

    styles = [s.strip() for s in args.styles.split(",")]

    logger.info("=== NEW PINTEREST CAMPAIGN ===")
    logger.info("Articles to process: %d", len(keywords))
    logger.info("Style variants: %s", styles)
    logger.info("Output: %s", REMASTER_DIR)

    generated = 0
    failed = 0

    for i, item in enumerate(keywords, 1):
        kw = item["keyword"]
        slug = item["slug"]
        domain = item["domain"]
        brand = getattr(domain, "brand_name_short", "") or f"{domain.display_name.upper()} | 2026"

        logger.info("[%d/%d] %s (%s)", i, len(keywords), kw, domain.handle)

        # Generate hero image
        hero = generate_hero_image(kw, slug)
        if not hero:
            failed += 1
            continue

        # Create pin with style variant (rotate through styles)
        style = styles[(i - 1) % len(styles)]
        title = kw[:1].upper() + kw[1:]
        pin = create_pin_image(hero, title, brand, style)
        if not pin:
            failed += 1
            continue

        # Move to remaster_final
        final = move_to_remaster(pin, slug, domain.handle)
        if final:
            generated += 1
        else:
            failed += 1

    logger.info("=== CAMPAIGN GENERATION COMPLETE ===")
    logger.info("Generated: %d | Failed: %d | Total: %d", generated, failed, len(keywords))
    logger.info("Output directory: %s", REMASTER_DIR)

    # Count final files
    final_count = len(list(REMASTER_DIR.rglob("*.jpg")) + list(REMASTER_DIR.rglob("*.png")))
    logger.info("Files in remaster_final: %d", final_count)


if __name__ == "__main__":
    main()
