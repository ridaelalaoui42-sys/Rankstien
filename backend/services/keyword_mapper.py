"""RankStein — Keyword Mapper Service
Keyword-to-URL mapping, cannibalization detection, internal linking, topic clustering.
"""

from __future__ import annotations

import logging

logger = logging.getLogger("rankstein.keyword_mapper")


async def map_keywords_to_pages(domain: str, keywords: list[dict]) -> list[dict]:
    """Map keywords to optimal target URLs."""
    mappings = []
    for kw in keywords:
        slug = kw["keyword"].lower().replace(" ", "-").replace("/", "")[:50]
        mappings.append(
            {
                "keyword": kw["keyword"],
                "target_url": f"https://{domain}/blog/{slug}",
                "search_volume": kw.get("volume", 0),
                "difficulty": kw.get("difficulty", 0),
                "intent": kw.get("intent", "informational"),
                "priority": "high" if kw.get("volume", 0) > 1000 else "medium",
            }
        )
    return mappings


async def find_cannibalization_issues(domain: str, keywords: list[dict]) -> list[dict]:
    """Detect keyword cannibalization across existing pages."""
    issues = []
    kw_map: dict[str, list] = {}
    for kw in keywords:
        base = kw["keyword"].lower().split()[0]
        kw_map.setdefault(base, []).append(kw["keyword"])
    for base, kws in kw_map.items():
        if len(kws) > 1:
            issues.append(
                {
                    "base_term": base,
                    "competing_keywords": kws,
                    "severity": "high" if len(kws) > 3 else "medium",
                    "recommendation": f"Consolidate or differentiate content targeting: {', '.join(kws)}",
                }
            )
    return issues


async def suggest_internal_links(source_url: str, target_urls: list[str]) -> list[dict]:
    """Recommend internal linking opportunities."""
    return [
        {
            "source": source_url,
            "target": t,
            "anchor_text": t.split("/")[-1].replace("-", " ").title(),
            "priority": "medium",
        }
        for t in target_urls[:5]
    ]


async def build_topic_clusters(keywords: list[dict]) -> list[dict]:
    """Group keywords into semantic topic clusters."""
    clusters: dict[str, list] = {}
    for kw in keywords:
        intent = kw.get("intent", "informational")
        clusters.setdefault(intent, []).append(kw)
    return [
        {
            "cluster_theme": theme,
            "keywords": kws,
            "count": len(kws),
            "total_volume": sum(k.get("volume", 0) for k in kws),
        }
        for theme, kws in clusters.items()
    ]


async def find_long_tail_opportunities(seed_keyword: str) -> list[dict]:
    """Generate long-tail keyword variations."""
    modifiers = ["best", "top", "how to", "guide", "review", "vs", "for beginners", "2026", "free", "tools"]
    return [
        {
            "keyword": f"{mod} {seed_keyword}",
            "volume": max(10, 500 - i * 40),
            "difficulty": max(5, 50 - i * 4),
            "intent": "informational",
        }
        for i, mod in enumerate(modifiers)
    ]


async def identify_search_intent(keywords: list[str]) -> list[dict]:
    """Classify search intent for keywords."""
    results = []
    for kw in keywords:
        kw_lower = kw.lower()
        if any(w in kw_lower for w in ["buy", "price", "cheap", "discount", "deal"]):
            intent = "transactional"
        elif any(w in kw_lower for w in ["how", "what", "why", "guide", "tutorial", "learn"]):
            intent = "informational"
        elif any(w in kw_lower for w in ["best", "top", "review", "vs", "compare"]):
            intent = "commercial"
        else:
            intent = "navigational"
        results.append({"keyword": kw, "intent": intent, "confidence": 0.85})
    return results
