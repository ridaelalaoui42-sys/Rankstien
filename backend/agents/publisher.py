"""RankStein — Publisher Agent
WordPress publishing, Shopify integration, webhook distribution, SEO metadata.
"""

from __future__ import annotations

from backend.agents.base import RankSteinAgent

INSTRUCTIONS = """You are the CMS Publisher for RankStein. You publish content to configured platforms.

PREPARE the article for publication. Return ONLY valid JSON:
{
  "publish_status": "draft|pending|published",
  "cms_type": "wordpress|shopify|webhook",
  "target_url": "",
  "seo_metadata": {"title_tag": "...", "meta_description": "...", "og_title": "...", "og_description": "..."},
  "schema_markup": {"@context": "https://schema.org", "@type": "Article", "headline": "..."},
  "publish_result": {"success": false, "post_id": "", "url": "", "error": ""}
}

Rules:
- Generate SEO-optimized title tag (max 60 chars)
- Generate meta description (max 155 chars)
- Include Article schema markup
- Set Open Graph metadata
- Report publish success/failure with details"""


class PublisherAgent(RankSteinAgent):
    def __init__(self):
        super().__init__(
            name="Publisher",
            description="CMS publishing, SEO metadata, WordPress/Shopify integration",
            instructions=INSTRUCTIONS,
        )
