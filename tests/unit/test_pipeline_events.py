from __future__ import annotations

import json
import sqlite3

import pytest

from rankstein.pipeline_events import (
    record_pipeline_stage,
    set_pipeline_run_status,
    start_pipeline_run,
)


def test_pipeline_event_stream_records_keyword_intake_and_stage_updates(tmp_path) -> None:
    db_path = tmp_path / "runtime" / "pipeline.db"

    run_id = start_pipeline_run(
        domain_handle="recetagenial",
        keyword="Ensalada de verano",
        cluster="Ensaladas",
        source="Pinterest Trends + Google News",
        db_path=db_path,
    )
    record_pipeline_stage(
        run_id,
        "source_scrape",
        "running",
        "Searching recipe sources",
        db_path=db_path,
    )
    record_pipeline_stage(
        run_id,
        "source_scrape",
        "complete",
        "Found 4 relevant sources",
        details={"sources_found": 4},
        db_path=db_path,
    )
    set_pipeline_run_status(run_id, "article_live", db_path=db_path)

    connection = sqlite3.connect(db_path)
    run = connection.execute(
        "SELECT domain_handle, keyword, status FROM pipeline_runs WHERE id = ?",
        (run_id,),
    ).fetchone()
    events = connection.execute(
        """
        SELECT stage, state, message, details_json
        FROM pipeline_events
        WHERE run_id = ?
        ORDER BY id
        """,
        (run_id,),
    ).fetchall()
    connection.close()

    assert run == ("recetagenial", "Ensalada de verano", "article_live")
    assert [(row[0], row[1]) for row in events] == [
        ("keyword_search", "complete"),
        ("keyword_selected", "complete"),
        ("source_scrape", "running"),
        ("source_scrape", "complete"),
    ]
    assert json.loads(events[-1][3])["sources_found"] == 4


def test_pipeline_event_stream_rejects_unknown_stages(tmp_path) -> None:
    db_path = tmp_path / "pipeline.db"
    run_id = start_pipeline_run(
        domain_handle="recetadolce",
        keyword="Tarta de limon",
        db_path=db_path,
    )

    with pytest.raises(ValueError, match="Unknown pipeline stage"):
        record_pipeline_stage(run_id, "magic", "running", db_path=db_path)
