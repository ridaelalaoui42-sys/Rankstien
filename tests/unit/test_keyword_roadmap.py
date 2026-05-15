from __future__ import annotations

from pathlib import Path

import pytest

from backend.scripts.turbo_articles import _is_retryable_model_error, _status_from_completion_output
from rankstein.keyword_roadmap import (
    KeywordRow,
    append_keyword_rows,
    clean_keyword_roadmap,
    mark_keyword_status,
    read_keyword_rows,
    reserve_pending_keywords,
    write_keyword_rows,
)


@pytest.mark.unit
def test_clean_keyword_roadmap_dedupes_resets_and_marks_db_live(tmp_path: Path) -> None:
    path = tmp_path / "keywords.md"
    write_keyword_rows(
        path,
        "Test Roadmap",
        [
            KeywordRow("Tarta Opera", "Postres", status="In Progress"),
            KeywordRow("tarta opera", "Postres", status="Pending"),
            KeywordRow("Gazpacho", "Ensaladas", status="Pending"),
        ],
    )

    report = clean_keyword_roadmap(path, "Test Roadmap", {"Gazpacho"})
    rows = read_keyword_rows(path)

    assert report["duplicates_removed"] == 1
    assert report["reset_in_progress"] == 1
    assert report["marked_live_from_db"] == 1
    assert [(row.keyword, row.status) for row in rows] == [
        ("Tarta Opera", "Pending"),
        ("Gazpacho", "Live"),
    ]


@pytest.mark.unit
def test_reserve_pending_keywords_marks_selected_rows_in_progress(tmp_path: Path) -> None:
    path = tmp_path / "keywords.md"
    write_keyword_rows(
        path,
        "Test Roadmap",
        [
            KeywordRow("One", status="Pending"),
            KeywordRow("Two", status="Pending"),
            KeywordRow("Three", status="Pending"),
        ],
    )

    selected = reserve_pending_keywords(path, "Test Roadmap", 2)
    rows = read_keyword_rows(path)

    assert [row.keyword for row in selected] == ["One", "Two"]
    assert [row.status for row in rows] == ["In Progress", "In Progress", "Pending"]


@pytest.mark.unit
def test_mark_keyword_status_updates_one_row(tmp_path: Path) -> None:
    path = tmp_path / "keywords.md"
    write_keyword_rows(path, "Test Roadmap", [KeywordRow("One", status="Pending")])

    assert mark_keyword_status(path, "Test Roadmap", "one", "Live") is True
    assert read_keyword_rows(path)[0].status == "Live"
    assert mark_keyword_status(path, "Test Roadmap", "missing", "Live") is False


@pytest.mark.unit
def test_append_keyword_rows_only_adds_unique_keywords(tmp_path: Path) -> None:
    path = tmp_path / "keywords.md"
    write_keyword_rows(path, "Test Roadmap", [KeywordRow("Tarta Opera", status="Pending")])

    added = append_keyword_rows(
        path,
        "Test Roadmap",
        [
            KeywordRow("tarta opera", status="Pending"),
            KeywordRow("Gazpacho facil", cluster="Aperitivos", status="Pending"),
        ],
    )

    rows = read_keyword_rows(path)
    assert added == 1
    assert [row.keyword for row in rows] == ["Tarta Opera", "Gazpacho facil"]


@pytest.mark.unit
def test_completion_output_requires_full_publication_proof() -> None:
    assert (
        _status_from_completion_output(
            '{"supabase_published": true, "pinterest_uploaded": true, "pin_linked": true}'
        )
        == "Live"
    )
    assert (
        _status_from_completion_output(
            '{"supabase_published": true, "pinterest_uploaded": false, "pin_linked": true}'
        )
        == "Needs Verification"
    )
    assert _status_from_completion_output("gemini completed without proof") == "Needs Verification"


@pytest.mark.unit
def test_model_capacity_errors_are_retryable() -> None:
    assert _is_retryable_model_error("MODEL_CAPACITY_EXHAUSTED")
    assert _is_retryable_model_error("No capacity available for model gemini-2.5-flash")
    assert not _is_retryable_model_error("invalid argument")
