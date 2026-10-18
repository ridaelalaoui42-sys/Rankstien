from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from rankstein.cli import build_parser
from rankstein.crochet_vertical import (
    CROCHET_CATEGORIES,
    audit_crochet_content,
    classify_crochet_keyword,
    is_crochet_niche,
    research_crochet_csv,
)
from rankstein.niche_detector import _fallback_categories


@pytest.mark.parametrize(
    ("keyword", "expected_cluster"),
    [
        ("free crochet tote bag pattern for beginners", "Free Bag Patterns"),
        ("crochet bag strap that does not stretch", "Free Bag Patterns"),
        ("how to crochet moss stitch for beginners", "Crochet Stitches"),
        ("US vs UK crochet terminology chart", "Crochet Stitches"),
        ("crochet baby blanket size chart", "Blankets & Home"),
        ("crochet christmas ornaments free pattern", "Seasonal Projects"),
        ("crochet flower keychain free pattern", "Flowers & Amigurumi"),
        ("crochet hook size chart mm to us", "Beginner Tutorials"),
    ],
)
def test_crochet_keyword_routes_to_relevant_cluster(keyword: str, expected_cluster: str) -> None:
    decision = classify_crochet_keyword(keyword)
    assert decision.qualified
    assert decision.cluster == expected_cluster
    assert decision.priority_score > 0


@pytest.mark.parametrize(
    "keyword",
    [
        "crochet bag",  # purchase/search-mixed, not guaranteed free-pattern intent
        "crochet patterns",  # broad hub, not a validated publishable long-tail
        "buy crochet tote bag",
        "crochet purse for sale",
        "chocolate cake recipe",
        "free crochet paid pattern download paid pattern free",
        "",
    ],
)
def test_keyword_gate_rejects_commercial_broad_and_unrelated(keyword: str) -> None:
    decision = classify_crochet_keyword(keyword)
    assert not decision.qualified
    assert decision.priority_score == 0


def test_crochet_domain_detection_keeps_existing_recipe_niches_unaffected() -> None:
    assert is_crochet_niche("free crochet patterns and stitch tutorials")
    assert is_crochet_niche("amigurumi textile craft projects")
    assert not is_crochet_niche("recetas espanolas tradicionales y modernas")
    assert not is_crochet_niche("pasteleria gourmet espanola")
    assert _fallback_categories("crochet patterns and accessories", 4) == list(CROCHET_CATEGORIES[:4])
    assert _fallback_categories("spanish recipes", 2) == ["Recipes", "Quick & Easy"]


def _pattern() -> dict:
    return {
        "content_type": "pattern",
        "title": "An original open-mesh bag",
        "body": "A substantial, original, independently prepared pattern. " * 9,
        "content_rights": "original",
        "images": [{"url": "https://my-crochet-site.test/images/mesh-tote.webp", "alt": "Handmade mesh tote bag, front view", "rights_verified": True}],
        "terminology": "US",
        "steps": ["Chain the foundation.", "Work the body in the round.", "Finish the straps."],
        "materials": ["cotton yarn", "5 mm hook"],
        "hook_size_mm": "5",
        "yarn_weight": "worsted",
        "gauge": "14 stitches per 10 cm",
        "finished_dimensions": "30 cm wide, 35 cm tall",
        "test_status": "physically_tested",
        "tester": "Independent reviewer",
        "test_notes": "Swatch, count and finished prototype independently checked.",
        "editorial_reviewer": "Copy editor",
        "stitch_count_checks": [{"start": 20, "increases": 2, "decreases": 0, "end": 22}],
    }


def test_untested_patterns_are_never_approved() -> None:
    item = _pattern()
    item["test_status"] = "ai_generated_only"
    item["tester"] = ""
    audit = audit_crochet_content(item)
    assert not audit.publishable
    assert "PHYSICAL_PATTERN_TEST_REQUIRED" in audit.blocking_issues
    assert "TESTER_ATTESTATION_REQUIRED" in audit.blocking_issues


def test_row_count_mismatch_blocks_publication() -> None:
    item = _pattern()
    item["stitch_count_checks"][0]["end"] = 23
    assert "ROW_1_STITCH_MATH_MISMATCH" in audit_crochet_content(item).blocking_issues


def test_math_complete_attested_pattern_passes_structural_audit_only() -> None:
    audit = audit_crochet_content(_pattern())
    assert audit.publishable
    assert not audit.blocking_issues


def test_placeholder_media_and_recipe_markup_cannot_be_published_as_crochet() -> None:
    item = _pattern()
    item["schema_type"] = "Recipe"
    item["images"][0]["url"] = "https://example.com/fake.jpg"
    item["content_rights"] = "unknown"
    issues = audit_crochet_content(item).blocking_issues
    assert "UNSUPPORTED_RICH_RESULT_SCHEMA" in issues
    assert "PLACEHOLDER_URL" in issues
    assert "VERIFIED_ORIGINAL_OR_LICENSED_IMAGE_REQUIRED" in issues
    assert "CONTENT_RIGHTS_NOT_VERIFIED" in issues


def test_incomplete_tutorial_is_blocked_without_testing_claim() -> None:
    item = {
        "content_type": "tutorial",
        "title": "Crochet bag lining tutorial",
        "body": "Original step-by-step explanation. " * 15,
        "content_rights": "original",
        "images": [{"url": "https://site.test/photo.webp", "alt": "Finished fabric lining", "rights_verified": True}],
        "steps": ["Cut fabric."],
        "terminology": "US",
    }
    assert "CLEAR_STEP_BY_STEP_INSTRUCTIONS_REQUIRED" in audit_crochet_content(item).blocking_issues


def test_research_csv_retains_source_and_never_invents_volume_or_kd(tmp_path: Path) -> None:
    path = tmp_path / "research.csv"
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=[
            "keyword", "editorial_priority", "estimated_monthly_searches",
            "market", "source_type", "source_url",
        ])
        writer.writeheader()
        writer.writerow({
            "keyword": "free crochet tote bag pattern for beginners",
            "editorial_priority": "P1",
            "estimated_monthly_searches": "",
            "market": "US", "source_type": "", "source_url": "",
        })
        writer.writerow({
            "keyword": "crochet stitches for blankets",
            "editorial_priority": "P2",
            "estimated_monthly_searches": "14800",
            "market": "Market not specified", "source_type": "Third-party estimate",
            "source_url": "https://source.test",
        })
        writer.writerow({
            "keyword": "buy crochet bag",
            "editorial_priority": "P1",
            "estimated_monthly_searches": "",
            "market": "", "source_type": "", "source_url": "",
        })
    report = research_crochet_csv(path)
    assert report["total_input_rows"] == 3
    assert report["qualified"] == 2
    assert report["publishing_enabled"] is False
    assert report["keywords"][0]["keyword"] == "free crochet tote bag pattern for beginners"
    assert report["keywords"][0]["third_party_volume"] is None
    assert report["keywords"][0]["keyword_difficulty"] is None
    assert report["keywords"][1]["third_party_volume"] == 14800
    assert report["keywords"][1]["volume_verified_by_google"] is False
    assert report["rejected"] == [{"keyword": "buy crochet bag", "reason": "SHOPPING_NOT_ADS_INTENT"}]


def test_cli_exposes_crochet_research_and_draft_audit_without_publishing(tmp_path: Path) -> None:
    parser = build_parser()
    parsed = parser.parse_args(["crochet", "research", "--csv", "keywords.csv"])
    assert parsed.crochet_action == "research"
    assert parsed.csv == Path("keywords.csv")
    draft_path = tmp_path / "draft.json"
    draft_path.write_text(json.dumps({"title": "Untested pattern", "content_type": "pattern"}))
    args = parser.parse_args(["crochet", "audit", "--input", str(draft_path)])
    assert args.func(args) == 1
