from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from pinterest_automation import campaign
from pinterest_automation import job_queue as job_queue_module
from pinterest_automation.job_queue import JobQueue


@pytest.fixture
def queue(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> JobQueue:
    monkeypatch.setattr(job_queue_module, "QUEUE_FILE", tmp_path / "pending_jobs.json")
    monkeypatch.setattr(job_queue_module, "DLQ_FILE", tmp_path / "dead_letter.json")
    monkeypatch.setattr(job_queue_module, "COMPLETED_FILE", tmp_path / "completed_jobs.json")
    instance = JobQueue(db_file=tmp_path / "queue.db")
    monkeypatch.setattr(
        campaign,
        "get_config",
        lambda: SimpleNamespace(boards={}, default_board="Chocolate"),
    )
    monkeypatch.setattr(campaign, "get_job_queue", lambda: instance)
    monkeypatch.setattr(campaign, "account_cohort", lambda *_args, **_kwargs: ["r1"])
    monkeypatch.setattr(campaign, "select_upload_account", lambda *_args, **_kwargs: "r1")
    return instance


def _production_assets(tmp_path: Path, *, suffix: str = "") -> tuple[list[str], list[dict]]:
    image_paths: list[str] = []
    assets: list[dict] = []
    for source_index in range(1, 16):
        pair_id = f"source-{source_index:02d}"
        pin_id = f"100000000000000{source_index:02d}"
        for variant in ("viral_visual", "recipe_card"):
            image = tmp_path / f"{pair_id}-{variant}{suffix}.jpg"
            image.write_bytes(f"{pair_id}:{variant}".encode())
            image_paths.append(str(image))
            assets.append(
                {
                    "remastered_path": str(image),
                    "pair_id": pair_id,
                    "source_index": source_index,
                    "source": "pinterest",
                    "original_pin_id": pin_id,
                    "original_url": f"https://www.pinterest.com/pin/{pin_id}/",
                    "variant": variant,
                    "variant_label": variant.replace("_", " ").title(),
                    "source_batch": "scrape",
                    "domain_handle": "recetadolce",
                }
            )
    return image_paths, assets


def _enqueue(
    tmp_path: Path,
    *,
    image_paths: list[str] | None = None,
    assets: list[dict] | None = None,
) -> dict:
    if image_paths is None or assets is None:
        image_paths, assets = _production_assets(tmp_path)
    return campaign.enqueue_article_remasters(
        slug="tarta-de-chocolate",
        title="Tarta de chocolate",
        domain_url="recetadolce.com",
        domain_handle="recetadolce",
        folder=tmp_path,
        image_paths=image_paths,
        asset_metadata=assets,
        pipeline_run_id="run-123",
        limit=30,
    )


@pytest.mark.unit
def test_article_remaster_queue_requires_exact_validated_pinterest_pairs(
    queue: JobQueue, tmp_path: Path
) -> None:
    image_paths, assets = _production_assets(tmp_path)
    assets[-2]["original_pin_id"] = assets[0]["original_pin_id"]
    assets[-1]["original_pin_id"] = assets[0]["original_pin_id"]

    result = _enqueue(tmp_path, image_paths=image_paths, assets=assets)

    assert result["success"] is False
    assert "15 unique Pinterest" in result["error"]
    assert result["jobs_enqueued"] == 0
    assert queue.get_stats()["total"] == 0


@pytest.mark.unit
def test_article_remaster_queue_rejects_partial_batch_before_mutation(
    queue: JobQueue, tmp_path: Path
) -> None:
    image_paths, assets = _production_assets(tmp_path)

    result = _enqueue(tmp_path, image_paths=image_paths[:-1], assets=assets[:-1])

    assert result["success"] is False
    assert "exactly 30" in result["error"]
    assert result["jobs_enqueued"] == 0
    assert queue.get_stats()["total"] == 0


@pytest.mark.unit
def test_article_remaster_queue_rejects_native_source_before_mutation(
    queue: JobQueue, tmp_path: Path
) -> None:
    image_paths, assets = _production_assets(tmp_path)
    assets[-2]["source"] = "native_fallback"
    assets[-1]["source"] = "native_fallback"

    result = _enqueue(tmp_path, image_paths=image_paths, assets=assets)

    assert result["success"] is False
    assert "not backed exclusively by a Pinterest source" in result["error"]
    assert result["jobs_enqueued"] == 0
    assert queue.get_stats()["total"] == 0


@pytest.mark.unit
def test_article_remaster_queue_preserves_pair_variant_and_source_metadata(
    queue: JobQueue, tmp_path: Path
) -> None:
    result = _enqueue(tmp_path)

    pending = queue.list_pending()
    assert result["success"] is True
    assert result["images_enqueued"] == 30
    assert result["jobs_enqueued"] == 30
    assert result["jobs_created"] == 30
    assert len(pending) == 30
    assert {job.payload["extra"]["pair_id"] for job in pending} == {
        f"source-{index:02d}" for index in range(1, 16)
    }
    assert {job.payload["extra"]["variant"] for job in pending} == {
        "viral_visual",
        "recipe_card",
    }
    assert all(job.payload["extra"]["source"] == "pinterest" for job in pending)
    assert all(job.payload["extra"]["source_pin_id"] for job in pending)
    assert all(job.payload["extra"]["pipeline_run_id"] == "run-123" for job in pending)
    assert all(job.payload["extra"]["idempotency_key"] for job in pending)


@pytest.mark.unit
def test_article_remaster_retry_deduplicates_by_source_identity_not_image_path(
    queue: JobQueue, tmp_path: Path
) -> None:
    first = _enqueue(tmp_path)
    retry_paths, retry_assets = _production_assets(tmp_path, suffix="-retry")

    retry = _enqueue(tmp_path, image_paths=retry_paths, assets=retry_assets)

    assert first["jobs_created"] == 30
    assert retry["success"] is True
    assert retry["jobs_enqueued"] == 30
    assert retry["jobs_created"] == 0
    assert retry["duplicates_skipped"] == 30
    assert queue.get_stats()["total"] == 30
    assert {item["job_id"] for item in retry["details"]} == {item["job_id"] for item in first["details"]}


@pytest.mark.unit
def test_article_remaster_retry_deduplicates_completed_jobs(queue: JobQueue, tmp_path: Path) -> None:
    first = _enqueue(tmp_path)
    for detail in first["details"]:
        queue.complete(detail["job_id"], {"pin_id": f"published-{detail['job_id']}"})

    retry_paths, retry_assets = _production_assets(tmp_path, suffix="-retry")
    retry = _enqueue(tmp_path, image_paths=retry_paths, assets=retry_assets)

    assert retry["success"] is True
    assert retry["jobs_enqueued"] == 30
    assert retry["jobs_created"] == 0
    assert retry["duplicates_skipped"] == 30
    assert {item["state"] for item in retry["details"]} == {"completed"}
    assert queue.get_stats()["total"] == 0


@pytest.mark.unit
def test_article_remaster_retry_deduplicates_completed_and_surfaces_dlq(
    queue: JobQueue, tmp_path: Path
) -> None:
    first = _enqueue(tmp_path)
    completed_id = first["details"][0]["job_id"]
    dlq_id = first["details"][1]["job_id"]
    queue.complete(completed_id, {"pin_id": "published-pin"})
    with queue._conn() as conn:
        row = conn.execute("SELECT * FROM jobs WHERE id = ?", (dlq_id,)).fetchone()
        assert row is not None
        job_json = json.dumps(
            {
                "id": row["id"],
                "type": row["type"],
                "payload": json.loads(row["payload_json"]),
                "status": "dead",
                "created_at": row["created_at"],
                "attempt": row["attempt"],
                "max_attempts": row["max_attempts"],
                "error_log": ["forced DLQ state"],
                "priority": row["priority"],
            }
        )
        conn.execute(
            "INSERT INTO dlq (id, job_json, moved_at) VALUES (?, ?, 1)",
            (dlq_id, job_json),
        )
        conn.execute("DELETE FROM jobs WHERE id = ?", (dlq_id,))

    retry_paths, retry_assets = _production_assets(tmp_path, suffix="-retry")
    retry = _enqueue(tmp_path, image_paths=retry_paths, assets=retry_assets)

    assert retry["success"] is False
    assert "DLQ" in retry["error"]
    assert retry["jobs_created"] == 0
    assert retry["duplicates_skipped"] == 30
    assert {item["location"] for item in retry["details"]} == {"active", "completed", "dlq"}
    assert queue.get_stats() == {
        "total": 28,
        "by_status": {"pending": 28},
        "dlq_size": 1,
    }
    assert queue.get_job_outcome(completed_id)["state"] == "completed"


@pytest.mark.unit
def test_article_remaster_batch_rolls_back_when_any_insert_fails(queue: JobQueue, tmp_path: Path) -> None:
    with queue._conn() as conn:
        conn.execute(
            """
            CREATE TRIGGER reject_source_eight
            BEFORE INSERT ON jobs
            WHEN json_extract(NEW.payload_json, '$.extra.pair_id') = 'source-08'
            BEGIN
                SELECT RAISE(ABORT, 'forced batch failure');
            END;
            """
        )

    result = _enqueue(tmp_path)

    assert result["success"] is False
    assert "forced batch failure" in result["error"]
    assert result["jobs_enqueued"] == 0
    assert queue.get_stats()["total"] == 0
