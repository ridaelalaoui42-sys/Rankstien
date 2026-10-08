"""Direct deterministic publication for all remaining pending keywords.

Bypasses Gemini CLI — uses template articles + Pollinations hero images
to publish directly to Supabase. Pin upload is best-effort.
"""
import asyncio
import json
import logging
import sys
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("publish_pending")

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from rankstein.domain import get_registry, reload_registry
from rankstein.keyword_roadmap import mark_keyword_status, read_keyword_rows
from backend.scripts.turbo_articles import (
    _build_article_payload,
    _deterministic_publication,
    _slugify,
)


async def process_pending(domain_handle: str, keyword: str, cluster: str) -> str:
    reload_registry()
    domain = get_registry().get(domain_handle)
    logger.info("Processing %s for %s", keyword, domain_handle)
    result = await _deterministic_publication(keyword, cluster, domain)
    logger.info("Result for %s: %s", keyword, result)
    return result


async def main():
    reload_registry()
    domains = get_registry().all()

    pending_by_domain = {}
    for domain in domains:
        path = domain.keywords_file
        rows = read_keyword_rows(path)
        pending = [(r.keyword, r.cluster) for r in rows if r.status.lower() == "pending"]
        if pending:
            pending_by_domain[domain.handle] = pending

    logger.info("Pending keywords: %s", pending_by_domain)

    for handle, kws in pending_by_domain.items():
        domain = get_registry().get(handle)
        for keyword, cluster in kws:
            logger.info("=== Processing %s/%s ===", handle, keyword)
            result = await process_pending(handle, keyword, cluster)
            mark_keyword_status(domain.keywords_file, f"{domain.display_name} Keyword Roadmap", keyword, result)

if __name__ == "__main__":
    asyncio.run(main())
