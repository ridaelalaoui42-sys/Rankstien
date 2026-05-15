import asyncio
import os
import sys

from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Ensure backend is in path
sys.path.append(os.getcwd())

from backend.agents.pinterest_uploader_v4 import deploy_remastered_campaign
from backend.services.remasterer import run_remasterer


async def main():
    keyword = sys.argv[1]
    title = sys.argv[2]
    slug = sys.argv[3]

    print(f"🚀 Starting Social Funnel for: {keyword}")
    pins = await run_remasterer(keyword, title)
    if pins:
        print(f"📤 Deploying {len(pins)} pins to Pinterest for {slug}...")
        await deploy_remastered_campaign(slug, keyword, pins)
    else:
        print(f"⚠️ No pins remastered for {keyword}")


if __name__ == "__main__":
    asyncio.run(main())
