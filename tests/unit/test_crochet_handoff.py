import json
from pathlib import Path

import pytest
from rankstein.crochet_handoff import prepare_editorial_handoff, run_handoff


def report():
    return {
        "vertical": "crochet", "publishing_enabled": False,
        "keywords": [
            {"keyword": "free crochet tote bag pattern for beginners", "qualified": True,
             "cluster": "Free Bag Patterns", "intent": "free_pattern",
             "status": "RESEARCH_ONLY_NOT_APPROVED_TO_PUBLISH", "third_party_volume": 6600,
             "volume_source": "third-party estimate", "volume_market": "not specified"},
            {"keyword": "how to line a crochet bag", "qualified": True,
             "cluster": "Free Bag Patterns", "intent": "tutorial",
             "status": "RESEARCH_ONLY_NOT_APPROVED_TO_PUBLISH", "third_party_volume": None},
            {"keyword": "buy crochet bag", "qualified": False,
             "cluster": "Free Bag Patterns", "intent": "commercial",
             "status": "RESEARCH_ONLY_NOT_APPROVED_TO_PUBLISH"},
        ],
    }


def test_creates_unpublished_pattern_and_tutorial_proposals_only():
    result = prepare_editorial_handoff(report(), limit=10)
    assert len(result["proposals"]) == 2
    assert result["publication_enabled"] is False
    bag = result["proposals"][0]
    assert bag["status"] == "draft"
    assert bag["kind"] == "pattern"
    assert bag["images"] == []
    assert bag["body"] == ""
    assert bag["test_evidence"]["test_status"] == "untested"
    assert bag["research_evidence"]["organic_difficulty"] is None
    assert bag["research_evidence"]["verified_by_google"] is False


def test_refuses_publishing_or_wrong_vertical():
    d = report(); d["publishing_enabled"] = True
    with pytest.raises(ValueError): prepare_editorial_handoff(d)
    d = report(); d["vertical"] = "recipe"
    with pytest.raises(ValueError): prepare_editorial_handoff(d)


def test_handoff_writes_local_json_only(tmp_path: Path):
    source, destination = tmp_path / "source.json", tmp_path / "drafts.json"
    source.write_text(json.dumps(report()))
    result = run_handoff(source, destination, limit=1)
    assert len(result["proposals"]) == 1
    assert json.loads(destination.read_text())["proposals"][0]["status"] == "draft"
