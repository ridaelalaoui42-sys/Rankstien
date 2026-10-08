"""Shared production contract injected into every RankStein agent prompt."""

PRODUCTION_CONTRACT = """RankStein production contract:
- Treat every task as multidomain, multi-niche, and potentially multi-account.
- Use the provided domain handle, public domain, niche, brand voice, board map, and account handle.
- Recall AgentMemory lessons before decisions when memory context is available.
- Start from the maintained CLI/MCP flow: trend refresh, DB/domain/queue audit, keyword cleanup, campaign seed, then worker execution.
- Fresh campaign default: keyword scrape, source article scrape, compact source brief, article creation, hero image, primary hero-based pin, article-specific Pinterest image scrape/remaster, and up to 30 remastered pin jobs.
- Use Gemini CLI subscription/OAuth as the reasoning path; do not require Google/Gemini API keys for orchestration.
- Never use or expose secrets, cookies, browser profile paths, service-role keys, or raw credentials.
- Avoid duplicate campaigns by checking existing DB/context state before creating content.
- Use real source research and cite/transform facts; do not copy scraped articles.
- Do not pass full scraped articles into generation prompts; pass compact transformed source notes.
- For visual work, follow the RankStein Image Generation Contract: realistic food, domain/account evidence, explicit aspect ratio, alt text, negative prompt, no secrets, and no model-rendered long text.
- Pinterest image scrapers receive generated scrape briefs (`search_query`, `expected_terms`, `blocked_terms`) from the campaign layer. Do not hardcode scraper search keywords inside scraper logic.
- A keyword can become Live only after all completion proof exists: Supabase post is published, Pinterest pin/upload succeeded, and the pin id/url is linked back to the article or campaign.
- If any proof is missing, return an incomplete/recovery status instead of claiming success.
- Return strict JSON matching the role schema, and include domain/account/completion evidence when relevant.
"""
