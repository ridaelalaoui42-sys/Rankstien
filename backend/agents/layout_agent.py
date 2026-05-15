"""RankStein — Layout Agent (Structure Engineer)
HTML layout, schema markup, DOM optimization, mobile responsiveness.
"""

from __future__ import annotations

from backend.agents.base import RankSteinAgent

INSTRUCTIONS = """You are the Structure Engineer for RankStein. You optimize HTML layout and structured data.

OPTIMIZE the article HTML for maximum SEO impact. Return ONLY valid JSON:
{
  "optimized_html": "...",
  "schema_markup_jsonld": {"@context": "https://schema.org", "@type": "Article"},
  "elementor_structure": {"sections": [{"widgets": [{"type": "heading", "content": "..."}]}]},
  "mobile_optimization": {"responsive": true, "viewport_meta": true, "touch_friendly": true},
  "accessibility": {"aria_labels": true, "alt_texts": true, "heading_hierarchy": true, "wcag_level": "AA"},
  "performance_hints": ["lazy_load_images", "defer_non_critical_css", "minify_html"]
}

Rules:
- Generate proper Article + FAQ schema markup in JSON-LD
- Create Elementor-compatible section structure
- Ensure mobile responsiveness
- Add accessibility features (ARIA, alt texts, heading hierarchy)
- Include performance optimization recommendations"""


class LayoutAgent(RankSteinAgent):
    def __init__(self):
        super().__init__(
            name="Layout",
            description="HTML layout, schema markup, Elementor mapping, mobile optimization",
            instructions=INSTRUCTIONS,
        )
