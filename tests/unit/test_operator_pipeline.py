from __future__ import annotations

import json
import shutil
import sqlite3
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path

import pytest

from backend.services.operator_pipeline import (
    STAGE_DEFINITIONS,
    STALE_RUNNING_SECONDS,
    _apply_primary_proof,
    _apply_queue_evidence,
    _apply_remaster_report,
    _campaign_is_ongoing,
    _finalize_campaign,
    _new_campaign,
    _read_current_production_batch,
    _remaster_contract_status,
    _set_stage,
    build_pipeline_payload,
)


def _create_event_db(root) -> sqlite3.Connection:
    path = root / "data" / "runtime" / "pipeline_events.db"
    path.parent.mkdir(parents=True)
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        CREATE TABLE pipeline_runs (
            id TEXT, domain_handle TEXT, keyword TEXT, slug TEXT, cluster TEXT,
            source TEXT, status TEXT, created_at REAL, updated_at REAL
        );
        CREATE TABLE pipeline_events (
            id INTEGER, run_id TEXT, stage TEXT, state TEXT, message TEXT,
            details_json TEXT, created_at REAL
        );
        """
    )
    return connection


def _create_queue_db(root) -> sqlite3.Connection:
    path = root / "data" / "queue" / "jobs.db"
    path.parent.mkdir(parents=True)
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        CREATE TABLE jobs (
            id TEXT,
            payload_json TEXT,
            status TEXT,
            created_at REAL,
            started_at REAL,
            completed_at REAL,
            result_json TEXT
        );
        CREATE TABLE completed_log (job_json TEXT, completed_at REAL);
        CREATE TABLE dlq (job_json TEXT, moved_at REAL);
        """
    )
    return connection


def _payload(status: str = "pending") -> dict:
    return {
        "id": f"job-{status}",
        "payload": {
            "title": "Tarta de limon",
            "link": "https://recetadolce.com/tarta-de-limon",
            "domain_handle": "recetadolce",
            "extra": {
                "slug": "tarta-de-limon",
                "domain_handle": "recetadolce",
                "campaign_type": "article_remaster_30",
            },
        },
        "status": status,
    }


def test_pipeline_payload_renders_every_live_event_stage(tmp_path) -> None:
    path = tmp_path / "data" / "runtime" / "pipeline_events.db"
    path.parent.mkdir(parents=True)
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        CREATE TABLE pipeline_runs (
            id TEXT, domain_handle TEXT, keyword TEXT, slug TEXT, cluster TEXT,
            source TEXT, status TEXT, created_at REAL, updated_at REAL
        );
        CREATE TABLE pipeline_events (
            id INTEGER, run_id TEXT, stage TEXT, state TEXT, message TEXT,
            details_json TEXT, created_at REAL
        );
        """
    )
    now = time.time()
    connection.execute(
        "INSERT INTO pipeline_runs VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            "run-1",
            "recetagenial",
            "Ensalada de verano",
            "ensalada-de-verano",
            "Ensaladas",
            "Pinterest Trends",
            "running",
            now - 30,
            now,
        ),
    )
    connection.executemany(
        "INSERT INTO pipeline_events VALUES (?, ?, ?, ?, ?, ?, ?)",
        [
            (1, "run-1", "keyword_search", "complete", "Found keyword", "{}", now - 30),
            (
                2,
                "run-1",
                "source_scrape",
                "complete",
                "Found 4 sources",
                "{}",
                now - 20,
            ),
            (
                3,
                "run-1",
                "article_write",
                "running",
                "Hermes Codex is writing",
                '{"provider":"hermes-codex"}',
                now,
            ),
        ],
    )
    connection.commit()
    connection.close()

    payload = build_pipeline_payload(tmp_path)
    campaign = payload["campaigns"][0]

    assert len(campaign["stages"]) == len(STAGE_DEFINITIONS) == 16
    assert campaign["overall_state"] == "active"
    assert campaign["current_stage"] == "article_write"
    assert campaign["current_detail"] == "Hermes Codex is writing"


def test_pipeline_separates_ongoing_lanes_from_terminal_history(tmp_path) -> None:
    connection = _create_event_db(tmp_path)
    now = time.time()
    connection.executemany(
        "INSERT INTO pipeline_runs VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            (
                "active-run",
                "recetagenial",
                "Ensalada de tomate",
                "ensalada-de-tomate",
                "Ensaladas",
                "Pinterest",
                "running",
                now - 30,
                now,
            ),
            (
                "failed-run",
                "recetadolce",
                "Tarta fallida",
                "tarta-fallida",
                "Postres",
                "Pinterest",
                "failed",
                now - 60,
                now - 20,
            ),
        ],
    )
    connection.executemany(
        "INSERT INTO pipeline_events VALUES (?, ?, ?, ?, ?, ?, ?)",
        [
            (
                1,
                "active-run",
                "article_write",
                "running",
                "Hermes is writing",
                "{}",
                now,
            ),
            (
                2,
                "failed-run",
                "hero_upload",
                "failed",
                "Upload failed",
                "{}",
                now - 20,
            ),
        ],
    )
    connection.commit()
    connection.close()

    payload = build_pipeline_payload(tmp_path)

    assert {item["id"] for item in payload["campaigns"]} == {
        "active-run",
        "failed-run",
    }
    assert [item["id"] for item in payload["ongoing_campaigns"]] == ["active-run"]
    assert [item["id"] for item in payload["history_campaigns"]] == ["failed-run"]
    assert payload["ongoing_total"] == payload["summary"]["ongoing"] == 1
    assert payload["history_total"] == 1


def test_ongoing_classifier_keeps_waiting_work_but_excludes_stale_interruptions() -> None:
    now = time.time()
    waiting = _new_campaign(
        domain="recetagenial",
        keyword="Sopa esperando pin",
        title="Sopa esperando pin",
        slug="sopa-esperando-pin",
        updated_at=now,
        run_id="waiting-run",
    )
    waiting["run_status"] = "running"
    _set_stage(waiting, "verification", "waiting", "Waiting for pin proof", now)
    _finalize_campaign(waiting, now=now)

    stale = _new_campaign(
        domain="recetadolce",
        keyword="Tarta interrumpida",
        title="Tarta interrumpida",
        slug="tarta-interrumpida",
        updated_at=now - STALE_RUNNING_SECONDS - 1,
        run_id="stale-run",
    )
    stale["run_status"] = "running"
    _set_stage(
        stale,
        "article_write",
        "running",
        "Old writer checkpoint",
        now - STALE_RUNNING_SECONDS - 1,
    )
    _finalize_campaign(stale, now=now)

    assert _campaign_is_ongoing(waiting) is True
    assert waiting["overall_state"] == "attention"
    assert _campaign_is_ongoing(stale) is False
    assert stale["run_status"] == "interrupted"


def test_ongoing_classifier_excludes_stale_researching_lane() -> None:
    now = time.time()
    stale = _new_campaign(
        domain="recetadolce",
        keyword="Investigacion abandonada",
        title="Investigacion abandonada",
        slug="investigacion-abandonada",
        updated_at=now - STALE_RUNNING_SECONDS - 1,
        run_id="stale-research",
    )
    stale["run_status"] = "researching"
    _set_stage(
        stale,
        "keyword_search",
        "running",
        "Old Pinterest research checkpoint",
        now - STALE_RUNNING_SECONDS - 1,
    )
    _finalize_campaign(stale, now=now)

    assert _campaign_is_ongoing(stale) is False


def test_pipeline_batch_reader_does_not_fall_back_past_corrupt_newest_report(
    tmp_path,
) -> None:
    report_dir = tmp_path / "data" / "reports" / "production_batches"
    report_dir.mkdir(parents=True)
    old = report_dir / "production-20260729-153510.json"
    newest = report_dir / "production-20261003-124403.json"
    old.write_text(
        json.dumps({"batch_id": "production-20260729-153510", "state": "running", "domains": {}}),
        encoding="utf-8",
    )
    newest.write_bytes(bytes(512))
    old_time = old.stat().st_mtime - 10
    import os

    os.utime(old, (old_time, old_time))

    assert _read_current_production_batch(tmp_path) == {"batch_id": "", "articles": {}}


def test_pipeline_batch_reader_orders_by_batch_id_not_last_write_time(tmp_path) -> None:
    report_dir = tmp_path / "data" / "reports" / "production_batches"
    report_dir.mkdir(parents=True)
    old_batch = report_dir / "production-20260729-153510.json"
    latest_batch = report_dir / "production-20261003-124403.json"
    old_batch.write_text(
        json.dumps({"batch_id": "production-20260729-153510", "state": "running", "domains": {}}),
        encoding="utf-8",
    )
    latest_batch.write_text(
        json.dumps({"batch_id": "production-20261003-124403", "state": "running", "domains": {}}),
        encoding="utf-8",
    )
    old_time = latest_batch.stat().st_mtime + 60
    import os

    os.utime(old_batch, (old_time, old_time))

    assert _read_current_production_batch(tmp_path)["batch_id"] == "production-20261003-124403"


def test_ongoing_classifier_excludes_queue_only_asset_rows() -> None:
    now = time.time()
    queue_asset = _new_campaign(
        domain="recetadolce",
        keyword="Native remaster source 11",
        title="Native remaster source 11",
        slug="native-remaster-source-11",
        updated_at=now,
        run_id="queue:recetadolce:native-remaster-source-11",
    )
    queue_asset["queue"] = {
        "total": 1,
        "active": 1,
        "completed": 0,
        "dead": 0,
        "failed": 0,
    }
    _set_stage(queue_asset, "distribution", "running", "0 published · 1 waiting", now)
    _finalize_campaign(queue_asset, now=now)

    assert _campaign_is_ongoing(queue_asset) is False


@pytest.mark.skipif(shutil.which("node") is None, reason="node binary not on PATH")
def test_frontend_renders_only_ongoing_campaigns_and_clean_empty_state() -> None:
    source = (Path(__file__).parents[2] / "backend" / "static" / "operator" / "operator.js").read_text(
        encoding="utf-8"
    )
    selector = source[source.index("function campaigns(") : source.index("function indexCampaigns(")]
    script = (
        """
      const terminal = {id: 'old-failed', run_status: 'failed', is_ongoing: false};
      const state = {data: {pipeline: {campaigns: [terminal], ongoing_campaigns: [], history_campaigns: [terminal]}}};
      const domainScope = () => '';
    """
        + selector
        + """
      console.log(JSON.stringify({selected: campaigns('active').length, history: campaigns('history').length}));
    """
    )
    result = subprocess.run(["node", "-e", script], capture_output=True, text=True, timeout=20, check=False)
    assert result.returncode == 0, result.stderr
    rendered = json.loads(result.stdout)
    assert rendered["selected"] == 0
    assert rendered["history"] == 1


def test_pipeline_payload_collapses_keyword_retries_to_latest_run(tmp_path) -> None:
    path = tmp_path / "data" / "runtime" / "pipeline_events.db"
    path.parent.mkdir(parents=True)
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        CREATE TABLE pipeline_runs (
            id TEXT, domain_handle TEXT, keyword TEXT, slug TEXT, cluster TEXT,
            source TEXT, status TEXT, created_at REAL, updated_at REAL
        );
        CREATE TABLE pipeline_events (
            id INTEGER, run_id TEXT, stage TEXT, state TEXT, message TEXT,
            details_json TEXT, created_at REAL
        );
        """
    )
    now = time.time()
    connection.executemany(
        "INSERT INTO pipeline_runs VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            (
                "new-run",
                "recetagenial",
                "Postres de fin de ano",
                "tarta-de-turron-nueva",
                "Postres",
                "Google News",
                "running",
                now - 10,
                now,
            ),
            (
                "old-run",
                "recetagenial",
                "Postres de fin de ano",
                "tarta-de-turron-anterior",
                "Postres",
                "Google News",
                "failed",
                now - 100,
                now - 50,
            ),
        ],
    )
    connection.executemany(
        "INSERT INTO pipeline_events VALUES (?, ?, ?, ?, ?, ?, ?)",
        [
            (1, "new-run", "hero_upload", "running", "Uploading new hero", "{}", now),
            (
                2,
                "old-run",
                "hero_upload",
                "failed",
                "Old upload failed",
                "{}",
                now - 50,
            ),
        ],
    )
    connection.commit()
    connection.close()

    payload = build_pipeline_payload(tmp_path)

    assert payload["total_campaigns"] == 1
    assert payload["campaigns"][0]["id"] == "new-run"
    assert payload["campaigns"][0]["current_detail"] == "Uploading new hero"


def test_pipeline_attention_points_to_latest_unresolved_checkpoint() -> None:
    now = time.time()
    campaign = _new_campaign(
        domain="recetagenial",
        keyword="Postre de fiesta",
        title="Postre de fiesta",
        slug="postre-de-fiesta",
        updated_at=now,
        run_id="run-attention",
    )
    _set_stage(
        campaign,
        "source_extract",
        "warning",
        "No compact sources passed relevance",
        now - 20,
    )
    _set_stage(
        campaign,
        "verification",
        "waiting",
        "Article is live but primary pin proof is pending",
        now,
    )

    _finalize_campaign(campaign, now=now)

    assert campaign["overall_state"] == "attention"
    assert campaign["current_stage"] == "verification"
    assert campaign["current_detail"] == "Article is live but primary pin proof is pending"


def test_pipeline_payload_merges_remaster_report_and_queue_progress(tmp_path) -> None:
    report_dir = tmp_path / "data" / "reports" / "campaigns"
    report_dir.mkdir(parents=True)
    (report_dir / "tarta-de-limon_remaster_20260728_120000.json").write_text(
        json.dumps(
            {
                "success": True,
                "completed_at": "2026-07-28T12:00:00+00:00",
                "campaign_type": "article_remaster_30",
                "keyword": "Tarta de limon",
                "title": "Tarta de limon",
                "slug": "tarta-de-limon",
                "domain_handle": "recetadolce",
                "domain_url": "recetadolce.com",
                "target_count": 30,
                "source_target": 15,
                "pair_count": 15,
                "generated_count": 30,
                "variant_contract": {"variants_per_source": 2},
                "source_counts": {"pinterest": 7, "native": 23},
                "enqueue": {"success": True, "jobs_enqueued": 30, "accounts": ["rida"]},
            }
        ),
        encoding="utf-8",
    )
    connection = _create_queue_db(tmp_path)
    now = time.time()
    active = _payload()["payload"]
    connection.execute(
        "INSERT INTO jobs VALUES ('job-active', ?, 'pending', ?, NULL, NULL, NULL)",
        (json.dumps(active), now),
    )
    complete = _payload("completed")
    complete["result"] = {
        "success": True,
        "pin_id": "123456789012345",
        "pin_url": "https://www.pinterest.com/pin/123456789012345/",
    }
    connection.execute(
        "INSERT INTO completed_log VALUES (?, ?)",
        (json.dumps(complete), now),
    )
    connection.commit()
    connection.close()

    payload = build_pipeline_payload(tmp_path)
    campaign = payload["campaigns"][0]
    stages = {stage["key"]: stage for stage in campaign["stages"]}

    assert campaign["overall_state"] == "active"
    assert campaign["queue"] == {
        "total": 2,
        "active": 1,
        "completed": 1,
        "dead": 0,
        "failed": 0,
        "unknown": 0,
    }
    assert campaign["pin_url"] == ""
    assert campaign["latest_campaign_pin_url"] == ("https://www.pinterest.com/pin/123456789012345/")
    assert stages["pinterest_siphon"]["state"] == "warning"
    assert campaign["verification_contract"]["campaign_report_complete"] is False
    assert stages["remaster"]["detail"] == "15 of 15 source pairs · 30 of 30 pin assets"
    assert stages["distribution"]["detail"] == "1 published · 1 waiting"
    assert payload["summary"]["pins_pending"] == 1


def test_queue_campaign_pin_never_replaces_primary_pin_and_filters_old_jobs() -> None:
    campaign = _new_campaign(
        domain="recetagenial",
        keyword="Tarta de turron",
        title="Tarta de turron",
        slug="tarta-de-turron",
        updated_at=100.0,
        run_id="run-primary-pin",
    )
    _apply_primary_proof(
        campaign,
        {
            "pin_id": "1148488342513478894",
            "url": "https://recetagenial.com/tarta-de-turron",
            "updated_at": 101.0,
        },
    )
    campaign["campaign_job_ids"] = ["current-job"]
    _apply_queue_evidence(
        campaign,
        {
            "pending": 32,
            "dead": 24,
            "updated_at": 102.0,
            "link": "https://recetagenial.com/tarta-de-turron",
            "latest_campaign_pin_url": "https://www.pinterest.com/pin/old-pin/",
            "jobs": {
                "current-job": {
                    "status": "completed",
                    "pin_url": "https://www.pinterest.com/pin/222222222222222/",
                    "updated_at": 102.0,
                    "campaign_type": "article_remaster_pairs",
                },
                "old-remaster-job": {
                    "status": "dead",
                    "pin_url": "",
                    "updated_at": 99.0,
                    "campaign_type": "article_remaster_30",
                },
                "primary-upload-job": {
                    "status": "completed",
                    "pin_url": "https://www.pinterest.com/pin/111111111111111/",
                    "updated_at": 103.0,
                    "campaign_type": "article_publish",
                },
            },
        },
    )

    assert campaign["pin_url"] == "https://www.pinterest.com/pin/1148488342513478894/"
    assert campaign["latest_campaign_pin_url"] == ("https://www.pinterest.com/pin/222222222222222/")
    assert campaign["queue"] == {
        "total": 1,
        "active": 0,
        "completed": 1,
        "dead": 0,
        "failed": 0,
        "unknown": 0,
    }
    assert campaign["historical_queue"] == {
        "total": 1,
        "active": 0,
        "completed": 0,
        "dead": 1,
        "failed": 0,
    }
    assert campaign["other_jobs"] == {
        "total": 1,
        "active": 0,
        "completed": 1,
        "dead": 0,
        "failed": 0,
    }


def test_pipeline_payload_surfaces_dead_letter_jobs_as_attention(tmp_path) -> None:
    connection = _create_queue_db(tmp_path)
    dead = _payload("dead")
    connection.execute(
        "INSERT INTO dlq VALUES (?, ?)",
        (json.dumps(dead), time.time()),
    )
    connection.commit()
    connection.close()

    payload = build_pipeline_payload(tmp_path)
    campaign = payload["campaigns"][0]

    assert campaign["overall_state"] == "attention"
    assert campaign["current_stage"] == "distribution"
    assert campaign["queue"]["dead"] == 1


def test_pipeline_payload_exposes_domain_aware_variant_pairs(tmp_path) -> None:
    report_dir = tmp_path / "data" / "reports" / "campaigns"
    media_dir = tmp_path / "data" / "media" / "remaster_final"
    report_dir.mkdir(parents=True)
    media_dir.mkdir(parents=True)
    assets = []
    for source_index in (1, 2):
        for variant, label in (
            ("viral_visual", "Viral visual"),
            ("recipe_card", "Ingredients + steps"),
        ):
            path = media_dir / f"tarta-source-{source_index:02d}-{variant}.jpg"
            path.write_bytes(b"preview")
            assets.append(
                {
                    "pair_id": f"source-{source_index:02d}",
                    "source_index": source_index,
                    "source": "pinterest",
                    "variant": variant,
                    "variant_label": label,
                    "remastered_path": str(path),
                    "width": 1000,
                    "height": 1500,
                    "status": "complete",
                }
            )
    (report_dir / "tarta_remaster_20260729_120000.json").write_text(
        json.dumps(
            {
                "success": True,
                "completed_at": "2026-07-29T12:00:00+00:00",
                "campaign_type": "article_remaster_pairs",
                "variant_contract": {
                    "variants_per_source": 2,
                    "variants": ["viral_visual", "recipe_card"],
                },
                "keyword": "Tarta",
                "title": "Tarta de chocolate",
                "slug": "tarta-de-chocolate",
                "domain_handle": "recetadolce",
                "domain_url": "recetadolce.com",
                "target_count": 4,
                "source_target": 2,
                "pair_count": 2,
                "generated_count": 4,
                "source_counts": {"pinterest": 2, "native": 0},
                "assets": assets,
            }
        ),
        encoding="utf-8",
    )

    payload = build_pipeline_payload(tmp_path)
    campaign = payload["campaigns"][0]
    remaster = campaign["remaster"]

    assert remaster["pair_count"] == 2
    assert remaster["source_target"] == 2
    assert remaster["variants_per_source"] == 2
    assert len(remaster["pairs"]) == 2
    assert [item["variant"] for item in remaster["pairs"][0]["variants"]] == [
        "viral_visual",
        "recipe_card",
    ]
    assert remaster["pairs"][0]["variants"][0]["preview_path"].startswith("data/media/remaster_final/")


def _production_remaster_report(*, success=True, pairs=15, assets=30, jobs=30):
    asset_rows = []
    for pair_index in range(pairs):
        for variant in ("viral_visual", "recipe_card"):
            asset_rows.append(
                {
                    "pair_id": f"pair-{pair_index}",
                    "variant": variant,
                    "source": "pinterest",
                    "original_pin_id": f"pin-{pair_index}",
                }
            )
    asset_rows = asset_rows[:assets]
    enqueue_details = [{"job_id": f"job-{index}"} for index in range(jobs)]
    return {
        "success": success,
        "_updated_at": time.time(),
        "_path": "campaign-report.json",
        "_root": ".",
        "campaign_type": "article_remaster_pairs",
        "keyword": "Tarta",
        "title": "Tarta completa",
        "slug": "tarta-completa",
        "domain_handle": "recetadolce",
        "domain_url": "recetadolce.com",
        "target_count": 30,
        "source_target": 15,
        "accepted_source_count": pairs,
        "pair_count": pairs,
        "generated_count": assets,
        "missing_count": max(0, 15 - pairs),
        "variant_contract": {
            "variants_per_source": 2,
            "variants": ["viral_visual", "recipe_card"],
        },
        "source_counts": {"pinterest": pairs, "native": 0},
        "assets": asset_rows,
        "enqueue": {
            "success": True,
            "images_enqueued": jobs,
            "jobs_enqueued": jobs,
            "details": enqueue_details,
        },
    }


def test_incomplete_remaster_report_cannot_verify_even_with_primary_pin() -> None:
    now = time.time()
    campaign = _new_campaign(
        domain="recetadolce",
        keyword="Tarta",
        title="Tarta completa",
        slug="tarta-completa",
        updated_at=now,
        run_id="run-incomplete",
    )
    _apply_primary_proof(
        campaign,
        {
            "pin_id": "123456789012345",
            "url": "https://recetadolce.com/tarta-completa",
            "updated_at": now,
        },
    )
    _apply_remaster_report(
        campaign,
        _production_remaster_report(success=False, pairs=13, assets=26, jobs=26),
    )
    _finalize_campaign(campaign, now=now)

    verification = {stage["key"]: stage for stage in campaign["stages"]}["verification"]
    assert verification["state"] == "waiting"
    assert "13/15 source pairs" in verification["detail"]
    assert "26/30 pin assets" in verification["detail"]
    assert "26/30 queued jobs" in verification["detail"]
    assert campaign["overall_state"] == "attention"
    assert campaign["verification_contract"]["primary_pin_proven"] is True
    assert campaign["verification_contract"]["campaign_report_complete"] is False


def test_exact_remaster_report_and_primary_pin_complete_verification() -> None:
    now = time.time()
    campaign = _new_campaign(
        domain="recetadolce",
        keyword="Tarta",
        title="Tarta completa",
        slug="tarta-completa",
        updated_at=now,
        run_id="run-complete",
    )
    _apply_primary_proof(
        campaign,
        {
            "pin_id": "123456789012345",
            "url": "https://recetadolce.com/tarta-completa",
            "updated_at": now,
        },
    )
    _apply_remaster_report(campaign, _production_remaster_report())
    _finalize_campaign(campaign, now=now)

    verification = {stage["key"]: stage for stage in campaign["stages"]}["verification"]
    assert verification["state"] == "complete"
    assert verification["detail"] == (
        "Primary pin plus 15 unique scraped sources and 30 queued pins verified"
    )
    assert campaign["verification_contract"]["campaign_report_complete"] is True


def test_generated_remaster_sources_cannot_complete_verification() -> None:
    now = time.time()
    campaign = _new_campaign(
        domain="recetagenial",
        keyword="Tarta",
        title="Tarta completa",
        slug="tarta-completa",
        updated_at=now,
        run_id="run-generated-fill",
    )
    report = _production_remaster_report()
    report["source_counts"] = {"pinterest": 1, "native": 14}
    for asset in report["assets"][2:]:
        asset["source"] = "native"
    _apply_remaster_report(campaign, report)

    assert campaign["verification_contract"]["campaign_report_complete"] is False
    assert campaign["remaster"]["native_sources"] == 14
    siphon = next(stage for stage in campaign["stages"] if stage["key"] == "pinterest_siphon")
    assert siphon["state"] == "warning"
    assert "14 generated fills" in siphon["detail"]


def test_duplicate_queue_job_ids_cannot_complete_verification() -> None:
    report = _production_remaster_report()
    report["enqueue"]["details"][-1]["job_id"] = "job-0"

    complete, detail = _remaster_contract_status(
        report,
        pair_count=15,
        generated=30,
        jobs=30,
    )

    assert complete is False
    assert "unique queue job IDs" in detail


def test_pipeline_uses_newest_report_for_repeated_article_campaign(tmp_path) -> None:
    report_dir = tmp_path / "data" / "reports" / "campaigns"
    report_dir.mkdir(parents=True)
    older = _production_remaster_report(success=False, pairs=1, assets=2, jobs=2)
    newer = _production_remaster_report()
    for report in (older, newer):
        report.pop("_updated_at")
        report.pop("_path")
        report.pop("_root")
    older["completed_at"] = "2026-08-01T16:05:18+00:00"
    newer["completed_at"] = "2026-08-01T17:05:12+00:00"
    (report_dir / "tarta-completa_remaster_20260801_160518.json").write_text(
        json.dumps(older),
        encoding="utf-8",
    )
    (report_dir / "tarta-completa_remaster_20260801_170512.json").write_text(
        json.dumps(newer),
        encoding="utf-8",
    )

    payload = build_pipeline_payload(tmp_path)
    campaign = next(item for item in payload["campaigns"] if item["slug"] == "tarta-completa")

    assert campaign["remaster"]["generated"] == 30
    assert campaign["remaster"]["pair_count"] == 15
    assert campaign["remaster"]["report_path"].endswith("tarta-completa_remaster_20260801_170512.json")
    assert campaign["verification_contract"]["campaign_report_complete"] is True


def test_stale_running_provider_stage_becomes_interrupted_history(tmp_path) -> None:
    path = tmp_path / "data" / "runtime" / "pipeline_events.db"
    path.parent.mkdir(parents=True)
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        CREATE TABLE pipeline_runs (
            id TEXT, domain_handle TEXT, keyword TEXT, slug TEXT, cluster TEXT,
            source TEXT, status TEXT, created_at REAL, updated_at REAL
        );
        CREATE TABLE pipeline_events (
            id INTEGER, run_id TEXT, stage TEXT, state TEXT, message TEXT,
            details_json TEXT, created_at REAL
        );
        """
    )
    stale_at = time.time() - STALE_RUNNING_SECONDS - 60
    connection.execute(
        "INSERT INTO pipeline_runs VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            "stale-run",
            "recetadolce",
            "Recetas de galletas caseras",
            "recetas-de-galletas-caseras",
            "Galletas",
            "Google News",
            "running",
            stale_at,
            stale_at,
        ),
    )
    connection.execute(
        "INSERT INTO pipeline_events VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            1,
            "stale-run",
            "article_write",
            "running",
            "OpenCode fallback is writing the article",
            '{"provider":"opencode"}',
            stale_at,
        ),
    )
    connection.commit()
    connection.close()

    campaign = build_pipeline_payload(tmp_path)["campaigns"][0]
    writing = next(stage for stage in campaign["stages"] if stage["key"] == "article_write")

    assert campaign["overall_state"] == "attention"
    assert campaign["run_status"] == "interrupted"
    assert campaign["current_stage"] == "article_write"
    assert campaign["current_detail"].startswith("Interrupted historical checkpoint")
    assert "OpenCode" not in campaign["current_detail"]
    assert writing["state"] == "warning"
    assert writing["metrics"]["interrupted"] is True


def test_current_batch_run_is_included_prioritized_and_reconciles_exact_proof(
    tmp_path,
) -> None:
    path = tmp_path / "data" / "runtime" / "pipeline_events.db"
    path.parent.mkdir(parents=True)
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        CREATE TABLE pipeline_runs (
            id TEXT, domain_handle TEXT, keyword TEXT, slug TEXT, cluster TEXT,
            source TEXT, status TEXT, created_at REAL, updated_at REAL
        );
        CREATE TABLE pipeline_events (
            id INTEGER, run_id TEXT, stage TEXT, state TEXT, message TEXT,
            details_json TEXT, created_at REAL
        );
        """
    )
    now = time.time()
    current_run_id = "recetagenial-current-batch"
    current_keyword = "Recetas de postres para fin de año"
    current_slug = "tarta-cremosa-de-turron-para-fin-de-ano"
    old = now - STALE_RUNNING_SECONDS - 60
    connection.execute(
        "INSERT INTO pipeline_runs VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            current_run_id,
            "recetagenial",
            current_keyword,
            current_slug,
            "Postres",
            "Google News",
            "distributing",
            old,
            old,
        ),
    )
    connection.executemany(
        "INSERT INTO pipeline_events VALUES (?, ?, ?, ?, ?, ?, ?)",
        [
            (
                1,
                current_run_id,
                "primary_pin",
                "complete",
                "Primary Pinterest artwork created",
                "{}",
                old,
            ),
            (
                2,
                current_run_id,
                "primary_pin_publish",
                "complete",
                "Primary pin published with verified proof",
                json.dumps(
                    {
                        "pin_id": "1148488342513478894",
                        "pin_url": "https://www.pinterest.com/pin/1148488342513478894/",
                    }
                ),
                old,
            ),
            (
                3,
                current_run_id,
                "verification",
                "complete",
                "Article, storage, and primary Pinterest proof verified",
                json.dumps({"pin_id": "1148488342513478894"}),
                old,
            ),
        ],
    )
    for index in range(41):
        run_id = f"newer-run-{index:02d}"
        connection.execute(
            "INSERT INTO pipeline_runs VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                run_id,
                "recetadolce",
                f"Newer keyword {index}",
                f"newer-keyword-{index}",
                "Postres",
                "Google News",
                "running",
                now,
                now,
            ),
        )
        connection.execute(
            "INSERT INTO pipeline_events VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                100 + index,
                run_id,
                "article_write",
                "running",
                "OpenAI Codex CLI is writing the article",
                '{"provider":"openai-codex-cli"}',
                now,
            ),
        )
    connection.commit()
    connection.close()

    batch_dir = tmp_path / "data" / "reports" / "production_batches"
    batch_dir.mkdir(parents=True)
    (batch_dir / "production-current.json").write_text(
        json.dumps(
            {
                "batch_id": "production-current",
                "state": "running",
                "domains": {
                    "recetagenial": {
                        "articles": [
                            {
                                "keyword": current_keyword,
                                "state": "verified",
                                "pipeline_run_id": current_run_id,
                                "roadmap_status": "Live",
                            }
                        ]
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    report_dir = tmp_path / "data" / "reports" / "campaigns"
    report_dir.mkdir(parents=True)
    report = _production_remaster_report()
    for internal_key in ("_updated_at", "_path", "_root"):
        report.pop(internal_key)
    report.update(
        {
            "pipeline_run_id": "",
            "keyword": "Tarta cremosa de turrón para fin de año",
            "title": "Tarta cremosa de turrón para fin de año",
            "slug": current_slug,
            "domain_handle": "recetagenial",
            "domain_url": "recetagenial.com",
            "completed_at": datetime.fromtimestamp(now, UTC).isoformat(),
        }
    )
    (report_dir / f"{current_slug}_remaster_current.json").write_text(
        json.dumps(report),
        encoding="utf-8",
    )

    payload = build_pipeline_payload(tmp_path)
    campaign = next(item for item in payload["campaigns"] if item["id"] == current_run_id)
    verification = next(stage for stage in campaign["stages"] if stage["key"] == "verification")

    assert payload["campaigns"][0]["id"] == current_run_id
    assert payload["total_campaigns"] == 41
    assert campaign["in_current_batch"] is True
    assert campaign["batch_state"] == "verified"
    assert campaign["verification_contract"]["primary_pin_proven"] is True
    assert campaign["verification_contract"]["campaign_report_complete"] is True
    assert campaign["remaster"]["pair_count"] == 15
    assert campaign["remaster"]["generated"] == 30
    assert verification["state"] == "complete"
    assert verification["detail"] == (
        "Primary pin plus 15 unique scraped sources and 30 queued pins verified"
    )
    assert not any(item["id"].startswith("report:") for item in payload["campaigns"])
