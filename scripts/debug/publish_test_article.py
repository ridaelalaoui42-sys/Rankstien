import os
import sys
import asyncio

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, PROJECT_ROOT)

from rankstein.domain import get_registry
from backend.scripts.turbo_articles import process_keyword

async def main():
    reg = get_registry()
    domain = reg.get("recetadolce")
    keyword = "tarta de queso la viña"
    cluster = "Postres"

    print(f"=== GENERATING AND PUBLISHING ARTICLE FOR '{keyword}' ({domain.handle}) ===")
    status = await process_keyword(keyword, cluster, domain, source="Google Autocomplete Demand + Google News + Pinterest Trends")
    print(f"\nFinal Publish Status: {status}")

if __name__ == "__main__":
    asyncio.run(main())
