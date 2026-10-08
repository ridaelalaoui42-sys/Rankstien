"""Fast sweep of Failed keywords with DNS-retry logic (Pollinations goes down intermittently)."""

import asyncio
import logging
import sys
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("sweep_failed")

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from backend.scripts.turbo_articles import _deterministic_publication
from rankstein.domain import get_registry, reload_registry
from rankstein.keyword_roadmap import mark_keyword_status, read_keyword_rows


async def sweep_domain(handle: str, batch_size: int = 3, pause_sec: int = 30):
    reload_registry()
    domain = get_registry().get(handle)
    rows = read_keyword_rows(domain.keywords_file)
    failed = [(r.keyword, r.cluster) for r in rows if r.status.lower() == "failed"]
    logger.info("%s: %d failed keywords to process", handle, len(failed))

    for i, (keyword, cluster) in enumerate(failed, 1):
        logger.info("[%d/%d] %s — %s", i, len(failed), handle, keyword)
        result = "Failed"

        for attempt in range(3):
            try:
                result = await _deterministic_publication(keyword, cluster, domain)
                break
            except Exception as e:
                err_str = str(e)
                if "NameResolutionError" in err_str or "getaddrinfo failed" in err_str:
                    logger.warning("DNS error on attempt %d for %s, waiting 30s...", attempt + 1, keyword)
                    await asyncio.sleep(30)
                    continue
                else:
                    logger.error("Non-retriable error for %s: %s", keyword, err_str)
                    break

        mark_keyword_status(domain.keywords_file, f"{domain.display_name} Keyword Roadmap", keyword, result)
        logger.info("→ %s", result)

        if i % batch_size == 0 and i < len(failed):
            logger.info("Batch pause: %ds...", pause_sec)
            await asyncio.sleep(pause_sec)


async def main():
    for handle in ["recetadolce", "recetagenial"]:
        await sweep_domain(handle)


if __name__ == "__main__":
    asyncio.run(main())
