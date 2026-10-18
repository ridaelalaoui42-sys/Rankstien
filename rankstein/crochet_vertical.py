"""Crochet editorial vertical: independent keyword research and fail-closed craft QA.

This module intentionally performs NO publishing, database, Pinterest, or site
provisioning operations. Crochet cannot be published through the food Recipe
schema and recipe image-remaster workflow.
"""

from __future__ import annotations

import csv
import json
import re
import unicodedata
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

CROCHET_CATEGORIES = (
    "Free Bag Patterns",
    "Crochet Stitches",
    "Beginner Tutorials",
    "Blankets & Home",
    "Accessories & Wearables",
    "Flowers & Amigurumi",
    "Seasonal Projects",
)

# Hub pages may be researched, but broad commercial head terms must not be
# treated as verified how-to intent or automatically routed to publication.
_SHOPPING = re.compile(
    r"\b(?:buy|shop|shopping|sale|for sale|amazon|etsy listing|wholesale|price|prices)\b", re.I
)
_CRAFT = re.compile(
    r"\b(?:crochet|amigurumi|granny square|yarn|stitch(?:es)?|hook size)\b", re.I
)
_INFORMATIONAL = re.compile(
    r"\b(?:free|pattern|tutorial|guide|how to|beginner|step by step|"
    r"chart|instructions?|size chart|compare|vs|why|fix|border|gauge|"
    r"stitches|stitch|lining|strap|calculator|how many|how much)\b", re.I
)
_FAKE_URL = re.compile(
    r"https?://(?:[\w-]+\.)*(?:example\.(?:com|org|net)|"
    r"placehold\.co|dummyimage\.com|via\.placeholder\.com)(?:[/:?#]|$)", re.I
)
_UNSAFE_OR_UNRELATED = re.compile(
    r"\b(?:recipe ingredients|recipe instructions|how to cook|"
    r"casino|loan|crypto|mod apk|download paid pattern free)\b", re.I
)


def is_crochet_niche(niche: str) -> bool:
    """Explicit craft niche detection; never alter Spanish food campaigns."""
    return bool(re.search(r"\b(?:crochet|amigurumi|fiber arts|fibre arts)\b", niche, re.I))


@dataclass(frozen=True)
class KeywordDecision:
    keyword: str
    qualified: bool
    cluster: str
    intent: str
    priority_score: int
    reason: str


def classify_crochet_keyword(keyword: str) -> KeywordDecision:
    """Editorial intent filter, not a search-volume or ranking predictor."""
    clean = " ".join(str(keyword).strip().split())
    folded = unicodedata.normalize("NFKD", clean).encode("ascii", "ignore").decode().lower()
    if not clean or len(clean.split()) > 13 or len(clean) > 125:
        return KeywordDecision(clean, False, "", "unknown", 0, "INVALID_KEYWORD")
    if _UNSAFE_OR_UNRELATED.search(folded) or not _CRAFT.search(folded):
        return KeywordDecision(clean, False, "", "irrelevant", 0, "OFF_NICHE")
    if _SHOPPING.search(folded):
        return KeywordDecision(clean, False, "", "commercial", 0, "SHOPPING_NOT_ADS_INTENT")
    if re.fullmatch(r"(free )?crochet( patterns?| bags?| tops?| cardigans?)?", folded):
        return KeywordDecision(clean, False, "", "mixed", 0, "BROAD_OR_MIXED_INTENT")
    if not _INFORMATIONAL.search(folded):
        return KeywordDecision(clean, False, "", "mixed", 0, "INSUFFICIENT_INFO_INTENT")

    if re.search(r"\b(?:bag|tote|market bag|purse|strap|lining)\b", folded):
        cluster = "Free Bag Patterns"
    elif re.search(r"\b(?:stitch|gauge|abbreviation|terminology|uneven edges|curling)\b", folded):
        cluster = "Crochet Stitches"
    elif re.search(r"\b(?:beginner|learn|hook size|hold yarn|magic ring|read patterns)\b", folded):
        cluster = "Beginner Tutorials"
    elif re.search(r"\b(?:blanket|afghan|throw|home decor)\b", folded):
        cluster = "Blankets & Home"
    elif re.search(r"\b(?:flower|daisy|amigurumi|bunny|octopus)\b", folded):
        cluster = "Flowers & Amigurumi"
    elif re.search(r"\b(?:christmas|halloween|easter|valentine|pumpkin|snowflake)\b", folded):
        cluster = "Seasonal Projects"
    else:
        cluster = "Accessories & Wearables"

    intent = "free_pattern" if re.search(r"\b(?:free|pattern)\b", folded) else "tutorial"
    score = 45
    if re.search(r"\b(?:how to|why|fix|beginner|step by step)\b", folded):
        score += 15
    if re.search(r"\b(?:free|pattern)\b", folded):
        score += 12
    if re.search(r"\b(?:without|no sewing|does not stretch|size chart|vs)\b", folded):
        score += 10
    if 5 <= len(folded.split()) <= 11:
        score += 8
    return KeywordDecision(clean, True, cluster, intent, min(100, score), "RESEARCH_CANDIDATE")


@dataclass(frozen=True)
class CraftAudit:
    publishable: bool
    content_type: str
    blocking_issues: tuple[str, ...]
    warnings: tuple[str, ...]


def _nonempty(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _valid_image(url: Any) -> bool:
    if not _nonempty(url) or _FAKE_URL.search(url):
        return False
    parsed = urlparse(url)
    return parsed.scheme == "https" and bool(parsed.netloc) and not parsed.username


def audit_crochet_content(payload: dict[str, Any]) -> CraftAudit:
    """Gate claims of 'tested' patterns. No AI-only pattern gets a pass.

    This verifies submitted evidence fields, not the physical correctness of
    a pattern. Tester attestations/photographs still need a genuine reviewer.
    """
    issues: list[str] = []
    warnings: list[str] = []
    kind = str(payload.get("content_type") or "").lower()
    if kind not in {"pattern", "tutorial", "stitch_guide", "roundup"}:
        issues.append("INVALID_CONTENT_TYPE")
    if not _nonempty(payload.get("title")):
        issues.append("TITLE_REQUIRED")
    if not _nonempty(payload.get("body")) or len(payload.get("body", "")) < 200:
        issues.append("ORIGINAL_SUBSTANTIVE_BODY_REQUIRED")
    if payload.get("schema_type") in {"Recipe", "Product", "HowTo"}:
        issues.append("UNSUPPORTED_RICH_RESULT_SCHEMA")
    if _FAKE_URL.search(json.dumps(payload, ensure_ascii=False)):
        issues.append("PLACEHOLDER_URL")
    if payload.get("content_rights") not in {"original", "licensed"}:
        issues.append("CONTENT_RIGHTS_NOT_VERIFIED")

    media = payload.get("images")
    if not isinstance(media, list) or not any(
        isinstance(m, dict) and _valid_image(m.get("url")) and m.get("rights_verified") is True
        and _nonempty(m.get("alt"))
        for m in media
    ):
        issues.append("VERIFIED_ORIGINAL_OR_LICENSED_IMAGE_REQUIRED")

    if kind in {"pattern", "tutorial", "stitch_guide"}:
        steps = payload.get("steps")
        if not isinstance(steps, list) or len(steps) < 3 or any(not _nonempty(s) for s in steps):
            issues.append("CLEAR_STEP_BY_STEP_INSTRUCTIONS_REQUIRED")
        if payload.get("terminology") not in {"US", "UK"}:
            issues.append("US_OR_UK_TERMINOLOGY_REQUIRED")

    if kind == "pattern":
        for field in ("materials", "hook_size_mm", "yarn_weight", "gauge", "finished_dimensions"):
            value = payload.get(field)
            if not _nonempty(value) and not (field == "materials" and isinstance(value, list) and value):
                issues.append(f"{field.upper()}_REQUIRED")
        if payload.get("test_status") != "physically_tested":
            issues.append("PHYSICAL_PATTERN_TEST_REQUIRED")
        if not _nonempty(payload.get("tester")) or not _nonempty(payload.get("test_notes")):
            issues.append("TESTER_ATTESTATION_REQUIRED")
        rows = payload.get("stitch_count_checks")
        if not isinstance(rows, list) or not rows:
            issues.append("STITCH_COUNT_CHECKS_REQUIRED")
        else:
            for index, row in enumerate(rows):
                if not isinstance(row, dict):
                    issues.append(f"ROW_{index + 1}_INVALID")
                    continue
                values = [row.get(k) for k in ("start", "increases", "decreases", "end")]
                if any(type(v) is not int or v < 0 for v in values) or values[0] == 0:
                    issues.append(f"ROW_{index + 1}_COUNT_INCOMPLETE")
                elif values[0] + values[1] - values[2] != values[3]:
                    issues.append(f"ROW_{index + 1}_STITCH_MATH_MISMATCH")
    elif kind == "roundup":
        if not isinstance(payload.get("source_links"), list) or not payload["source_links"]:
            issues.append("ROUNDUP_SOURCES_REQUIRED")
    if not _nonempty(payload.get("editorial_reviewer")):
        warnings.append("EDITORIAL_REVIEW_NOT_RECORDED")

    return CraftAudit(
        publishable=not issues,
        content_type=kind,
        blocking_issues=tuple(dict.fromkeys(issues)),
        warnings=tuple(dict.fromkeys(warnings)),
    )


def research_crochet_csv(path: Path) -> dict[str, Any]:
    """Read research pack without pretending volume or KD has been verified."""
    with path.open(encoding="utf-8-sig", newline="") as handle:
        records = list(csv.DictReader(handle))
    if not records or "keyword" not in records[0]:
        raise ValueError("Expected CSV with keyword field")
    candidates: list[dict[str, Any]] = []
    rejected: list[dict[str, str]] = []
    seen: set[str] = set()
    for record in records:
        decision = classify_crochet_keyword(record.get("keyword", ""))
        key = decision.keyword.casefold()
        if key in seen:
            continue
        seen.add(key)
        if not decision.qualified:
            rejected.append({"keyword": decision.keyword, "reason": decision.reason})
            continue
        priority = record.get("editorial_priority", "unmeasured")
        raw_volume = str(record.get("estimated_monthly_searches") or "").strip()
        # Only retain third-party volume with its explicit provenance. No
        # guessed organic difficulty and no inferred US search volume.
        volume = int(raw_volume) if raw_volume.isdecimal() else None
        candidates.append({
            **asdict(decision),
            "editorial_priority": priority,
            "third_party_volume": volume,
            "volume_market": record.get("market") or "Not specified",
            "volume_source": record.get("source_type") if volume is not None else None,
            "source_url": record.get("source_url") or None,
            "volume_verified_by_google": False,
            "keyword_difficulty": None,
            "status": "RESEARCH_ONLY_NOT_APPROVED_TO_PUBLISH",
        })
    order = {"P1": 0, "P2": 1, "P3": 2}
    candidates.sort(key=lambda x: (order.get(x["editorial_priority"], 3), -x["priority_score"], x["keyword"]))
    return {
        "vertical": "crochet",
        "business_model": "display_ads",
        "total_input_rows": len(records),
        "qualified": len(candidates),
        "rejected": rejected,
        "publishing_enabled": False,
        "notes": "Search demand is third-party/market-unspecified where present. Never treat a proxy as Google Ads volume.",
        "keywords": candidates,
    }
