"""Convert evidence-tagged crochet SEO topics to an editorial draft handoff.

NO database write, Pinterest upload, pattern generation or publication occurs.
Every proposal is human-review-required and intentionally lacks content/test proof.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

CATEGORY_MAP = {
    "Free Bag Patterns": "bags",
    "Crochet Stitches": "stitches",
    "Beginner Tutorials": "beginners",
    "Blankets & Home": "home",
    "Accessories & Wearables": "accessories",
    "Flowers & Amigurumi": "amigurumi",
    "Seasonal Projects": "seasonal",
}


def slugify(keyword: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", keyword.casefold()).strip("-")
    if not slug or len(slug) > 110:
        raise ValueError(f"Invalid crochet keyword for slug: {keyword!r}")
    return slug


def prepare_editorial_handoff(report: dict[str, Any], *, limit: int = 40) -> dict[str, Any]:
    """Return draft proposals with keyword/source provenance and no generated facts."""
    if report.get("vertical") != "crochet" or report.get("publishing_enabled") is not False:
        raise ValueError("Requires nonpublishing crochet keyword research report")
    if not isinstance(report.get("keywords"), list) or not 1 <= limit <= 200:
        raise ValueError("Expected keyword report and limit from 1 to 200")
    proposals: list[dict[str, Any]] = []
    seen: set[str] = set()
    for candidate in report["keywords"]:
        if not isinstance(candidate, dict) or candidate.get("status") != "RESEARCH_ONLY_NOT_APPROVED_TO_PUBLISH":
            continue
        if candidate.get("qualified") is not True:
            continue
        kind = "pattern" if candidate.get("intent") == "free_pattern" else "tutorial"
        category = CATEGORY_MAP.get(candidate.get("cluster"))
        if not category:
            continue
        keyword = " ".join(str(candidate.get("keyword", "")).split())
        slug = slugify(keyword)
        if slug in seen:
            continue
        seen.add(slug)
        evidence = {
            "market": str(candidate.get("volume_market") or "unknown"),
            "source_type": candidate.get("volume_source"),
            "source_url": candidate.get("source_url"),
            "third_party_volume": candidate.get("third_party_volume"),
            "verified_by_google": False,
            "organic_difficulty": None,
        }
        proposals.append({
            "title": keyword[:180],
            "slug": slug,
            "seo_keyword": keyword[:180],
            "kind": kind,
            "category": category,
            "status": "draft",
            "description": "",
            "body": "",
            "content_rights": "unverified",
            "terminology": "US",
            "images": [],
            "steps": [],
            "materials": [],
            "source_links": [],
            "stitch_count_checks": [],
            "test_evidence": {"test_status": "untested", "human_attested": False},
            "research_evidence": evidence,
        })
        if len(proposals) >= limit:
            break
    return {
        "format_version": "stitch-atlas-editorial-handoff-v1",
        "vertical": "crochet",
        "business_model": "display_ads",
        "publication_enabled": False,
        "requires_human_editor": True,
        "notes": "These are unpublished SEO research proposals, not completed or tested patterns. Nothing is pushed to a database or Pinterest.",
        "proposals": proposals,
    }


def run_handoff(input_path: Path, output_path: Path, limit: int = 40) -> dict[str, Any]:
    report = json.loads(input_path.read_text(encoding="utf-8"))
    handoff = prepare_editorial_handoff(report, limit=limit)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(handoff, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return handoff

if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='Export unpublished Stitch Atlas research proposals; never writes to the CMS or Pinterest')
    parser.add_argument('--research-json', type=Path, required=True, help='Output of Rankstien crochet research')
    parser.add_argument('--output', type=Path, default=Path('data/reports/stitch-atlas-draft-handoff.json'))
    parser.add_argument('--limit', type=int, default=40)
    args = parser.parse_args()
    report = run_handoff(args.research_json, args.output, args.limit)
    print(json.dumps({'proposals': len(report['proposals']), 'publication_enabled': False, 'output': str(args.output)}))
