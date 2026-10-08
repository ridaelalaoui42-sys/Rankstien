from __future__ import annotations

import json
from pathlib import Path

import pytest

from rankstein.production_batch import ProductionBatchTracker


@pytest.mark.unit
def test_production_batch_tracks_verified_targets_and_run_ids(tmp_path: Path) -> None:
    tracker = ProductionBatchTracker(
        project_root=tmp_path,
        batch_id="production-test",
        domain_handles=["recetadolce", "recetagenial"],
        target_per_domain=1,
    )

    tracker.start_keyword("recetadolce", "tarta de chocolate", "Postres", "Pinterest")
    tracker.attach_run("recetadolce", "tarta de chocolate", "recetadolce-run-1")
    tracker.complete_keyword("recetadolce", "tarta de chocolate", "Live")
    tracker.reject_keyword("recetagenial", "cargando resultados", "not a recipe")
    tracker.start_keyword("recetagenial", "gazpacho de sandía", "Aperitivos", "Google News")
    tracker.attach_run("recetagenial", "gazpacho de sandía", "recetagenial-run-1")
    tracker.complete_keyword("recetagenial", "gazpacho de sandía", "Live")

    assert tracker.finish_if_complete() is True
    report = json.loads(tracker.path.read_text(encoding="utf-8"))
    assert report["state"] == "complete"
    assert report["verified_total"] == 2
    assert report["rejected_total"] == 1
    assert report["domains"]["recetadolce"]["articles"][0]["pipeline_run_id"] == ("recetadolce-run-1")
    assert report["domains"]["recetagenial"]["verified"] == 1


@pytest.mark.unit
def test_production_batch_does_not_count_needs_verification_as_live(tmp_path: Path) -> None:
    tracker = ProductionBatchTracker(
        project_root=tmp_path,
        batch_id="production-incomplete",
        domain_handles=["recetadolce"],
        target_per_domain=1,
    )
    tracker.start_keyword("recetadolce", "flan casero", "Postres", "roadmap")
    tracker.complete_keyword("recetadolce", "flan casero", "Needs Verification")

    assert tracker.verified("recetadolce") == 0
    assert tracker.finish_if_complete() is False
    assert tracker.data["domains"]["recetadolce"]["failed"] == 1


@pytest.mark.unit
def test_incomplete_batch_resumes_verified_work_and_marks_interrupted_attempt(
    tmp_path: Path,
) -> None:
    tracker = ProductionBatchTracker(
        project_root=tmp_path,
        batch_id="production-resume",
        domain_handles=["recetadolce"],
        target_per_domain=2,
    )
    tracker.start_keyword("recetadolce", "tarta uno", "Postres", "test")
    tracker.complete_keyword("recetadolce", "tarta uno", "Live")
    tracker.start_keyword("recetadolce", "tarta dos", "Postres", "test")

    resumed = ProductionBatchTracker(
        project_root=tmp_path,
        batch_id="production-resume",
        domain_handles=["recetadolce"],
        target_per_domain=2,
    )

    report = json.loads(resumed.path.read_text(encoding="utf-8"))
    assert report["state"] == "running"
    assert report["domains"]["recetadolce"]["verified"] == 1
    assert report["domains"]["recetadolce"]["failed"] == 1
    assert report["domains"]["recetadolce"]["running_keywords"] == []
    assert report["domains"]["recetadolce"]["articles"][-1]["state"] == "interrupted"


@pytest.mark.unit
def test_batch_writer_retries_windows_replace_lock(tmp_path: Path, monkeypatch) -> None:
    import rankstein.production_batch as production_batch

    real_replace = production_batch.os.replace
    calls = 0

    def flaky_replace(source, destination):
        nonlocal calls
        calls += 1
        if calls < 3:
            raise PermissionError(5, "Access is denied")
        return real_replace(source, destination)

    monkeypatch.setattr(production_batch.os, "replace", flaky_replace)
    monkeypatch.setattr(production_batch.time, "sleep", lambda _: None)

    tracker = ProductionBatchTracker(
        project_root=tmp_path,
        batch_id="production-retry",
        domain_handles=["recetadolce"],
        target_per_domain=1,
    )

    assert tracker.path.is_file()
    assert calls == 3


@pytest.mark.unit
def test_resume_prefers_newer_recoverable_tmp_report(tmp_path: Path) -> None:
    tracker = ProductionBatchTracker(
        project_root=tmp_path,
        batch_id="production-tmp",
        domain_handles=["recetadolce"],
        target_per_domain=2,
    )
    tracker.start_keyword("recetadolce", "tarta uno", "Postres", "test")
    tracker.complete_keyword("recetadolce", "tarta uno", "Live")
    newer = json.loads(tracker.path.read_text(encoding="utf-8"))
    newer["updated_at"] += 10
    newer["domains"]["recetadolce"]["failed"] = 2
    tracker.path.with_suffix(".tmp").write_text(
        json.dumps(newer),
        encoding="utf-8",
    )

    resumed = ProductionBatchTracker(
        project_root=tmp_path,
        batch_id="production-tmp",
        domain_handles=["recetadolce"],
        target_per_domain=2,
    )

    assert resumed.data["domains"]["recetadolce"]["verified"] == 1
    assert resumed.data["domains"]["recetadolce"]["failed"] == 2


@pytest.mark.unit
def test_completion_is_idempotent(tmp_path: Path) -> None:
    tracker = ProductionBatchTracker(
        project_root=tmp_path,
        batch_id="production-idempotent",
        domain_handles=["recetadolce"],
        target_per_domain=2,
    )
    tracker.start_keyword("recetadolce", "tarta uno", "Postres", "test")

    tracker.complete_keyword("recetadolce", "tarta uno", "Live")
    tracker.complete_keyword("recetadolce", "tarta uno", "Live")

    assert tracker.data["domains"]["recetadolce"]["verified"] == 1


@pytest.mark.unit
def test_invalid_verified_proof_removes_batch_credit_idempotently(tmp_path: Path) -> None:
    tracker = ProductionBatchTracker(
        project_root=tmp_path,
        batch_id="production-invalidate",
        domain_handles=["recetagenial"],
        target_per_domain=1,
    )
    tracker.start_keyword("recetagenial", "tarta de turron", "Postres", "Pinterest")
    tracker.attach_run("recetagenial", "tarta de turron", "run-1")
    tracker.complete_keyword("recetagenial", "tarta de turron", "Live")

    assert tracker.invalidate_verified_keyword(
        "recetagenial",
        "tarta de turron",
        "Campaign used generated source substitutions",
        pipeline_run_id="run-1",
    )
    assert not tracker.invalidate_verified_keyword(
        "recetagenial",
        "tarta de turron",
        "Repeated audit",
        pipeline_run_id="run-1",
    )

    domain = tracker.data["domains"]["recetagenial"]
    article = domain["articles"][-1]
    assert domain["verified"] == 0
    assert domain["state"] == "running"
    assert tracker.data["verified_total"] == 0
    assert tracker.data["state"] == "running"
    assert article["state"] == "needs verification"
    assert article["roadmap_status"] == "Needs Verification"
    assert "generated source" in article["reason"]

    tracker.data["error"] = "stale write failure"
    assert tracker.restore_invalidated_keyword(
        "recetagenial",
        "tarta de turron",
        "campaign-report.json",
        pipeline_run_id="run-1",
    )
    assert not tracker.restore_invalidated_keyword(
        "recetagenial",
        "tarta de turron",
        "duplicate restore",
        pipeline_run_id="run-1",
    )
    assert domain["verified"] == 1
    assert domain["state"] == "complete"
    assert tracker.data["verified_total"] == 1
    assert article["state"] == "verified"
    assert article["roadmap_status"] == "Live"
    assert article["replacement_proof"] == "campaign-report.json"
    assert "error" not in tracker.data


@pytest.mark.unit
def test_completed_batch_id_cannot_be_reused(tmp_path: Path) -> None:
    tracker = ProductionBatchTracker(
        project_root=tmp_path,
        batch_id="production-complete",
        domain_handles=["recetadolce"],
        target_per_domain=1,
    )
    tracker.start_keyword("recetadolce", "tarta uno", "Postres", "test")
    tracker.complete_keyword("recetadolce", "tarta uno", "Live")
    assert tracker.finish_if_complete() is True

    with pytest.raises(ValueError, match="cannot be reused"):
        ProductionBatchTracker(
            project_root=tmp_path,
            batch_id="production-complete",
            domain_handles=["recetadolce"],
            target_per_domain=1,
        )


@pytest.mark.unit
def test_reconcile_needs_verification_credits_exact_run_once(tmp_path: Path) -> None:
    tracker = ProductionBatchTracker(
        project_root=tmp_path,
        batch_id="production-reconcile",
        domain_handles=["recetagenial"],
        target_per_domain=2,
    )
    tracker.start_keyword("recetagenial", "ensalada saludable", "Ensaladas", "Pinterest")
    tracker.attach_run("recetagenial", "ensalada saludable", "recetagenial-run-1")
    tracker.complete_keyword("recetagenial", "ensalada saludable", "Needs Verification")

    assert tracker.reconcile_needs_verification(
        "recetagenial",
        "ensalada saludable",
        pipeline_run_id="recetagenial-run-1",
        primary_job_id="primary-1",
        pin_id="1148488342515527632",
        pin_url="https://www.pinterest.com/pin/1148488342515527632/",
        campaign_report="campaign-report.json",
    )
    assert not tracker.reconcile_needs_verification(
        "recetagenial",
        "ensalada saludable",
        pipeline_run_id="recetagenial-run-1",
        primary_job_id="primary-1",
        pin_id="1148488342515527632",
        pin_url="https://www.pinterest.com/pin/1148488342515527632/",
        campaign_report="campaign-report.json",
    )

    domain = tracker.data["domains"]["recetagenial"]
    article = domain["articles"][-1]
    assert domain["failed"] == 0
    assert domain["verified"] == 1
    assert tracker.data["failed_total"] == 0
    assert tracker.data["verified_total"] == 1
    assert article["state"] == "verified"
    assert article["roadmap_status"] == "Live"
    assert article["reconciliation_proof"] == {
        "primary_job_id": "primary-1",
        "pin_id": "1148488342515527632",
        "pin_url": "https://www.pinterest.com/pin/1148488342515527632/",
        "campaign_report": "campaign-report.json",
    }


@pytest.mark.unit
def test_reconcile_needs_verification_rejects_wrong_run_without_counter_changes(
    tmp_path: Path,
) -> None:
    tracker = ProductionBatchTracker(
        project_root=tmp_path,
        batch_id="production-wrong-run",
        domain_handles=["recetagenial"],
        target_per_domain=1,
    )
    tracker.start_keyword("recetagenial", "pescado frito", "Pescados", "Pinterest")
    tracker.attach_run("recetagenial", "pescado frito", "recetagenial-run-1")
    tracker.complete_keyword("recetagenial", "pescado frito", "Needs Verification")
    before = json.loads(json.dumps(tracker.data))

    assert not tracker.reconcile_needs_verification(
        "recetagenial",
        "pescado frito",
        pipeline_run_id="recetagenial-run-2",
        primary_job_id="primary-2",
        pin_id="1148488342515527688",
        pin_url="https://www.pinterest.com/pin/1148488342515527688/",
        campaign_report="campaign-report.json",
    )
    assert tracker.data["domains"] == before["domains"]
    assert tracker.data["verified_total"] == before["verified_total"]
    assert tracker.data["failed_total"] == before["failed_total"]


def test_published_count_includes_articles_waiting_for_pin_proof(tmp_path: Path) -> None:
    tracker = ProductionBatchTracker(
        project_root=tmp_path,
        batch_id="production-bounded",
        domain_handles=["recetagenial"],
        target_per_domain=10,
    )
    for number in range(10):
        keyword = f"recipe {number}"
        tracker.start_keyword("recetagenial", keyword, "Carnes", "Pinterest Trends")
        tracker.complete_keyword("recetagenial", keyword, "Needs Verification")
    assert tracker.verified("recetagenial") == 0
    assert tracker.published_count("recetagenial") == 10


@pytest.mark.unit
def test_start_keyword_clears_waiting_state_without_changing_completed_counts(tmp_path: Path) -> None:
    tracker = ProductionBatchTracker(
        project_root=tmp_path,
        batch_id="production-resume-waiting",
        domain_handles=["recetadolce"],
        target_per_domain=10,
    )
    tracker.start_keyword("recetadolce", "tarta de coco", "Postres", "Pinterest Trends")
    tracker.complete_keyword("recetadolce", "tarta de coco", "Live")
    tracker.start_keyword("recetadolce", "tarta de pera", "Postres", "Pinterest Trends")
    tracker.complete_keyword("recetadolce", "tarta de pera", "Failed")
    tracker.mark_domain_waiting("recetadolce", "No unattempted Pinterest keyword; researching new candidates")
    before = json.loads(json.dumps(tracker.data))

    tracker.start_keyword("recetadolce", "galletas de avena", "Postres", "Pinterest Trends")

    report = json.loads(tracker.path.read_text(encoding="utf-8"))
    domain = report["domains"]["recetadolce"]
    assert domain["state"] == "running"
    assert "detail" not in domain
    assert domain["running_keywords"] == ["galletas de avena"]
    assert domain["verified"] == before["domains"]["recetadolce"]["verified"] == 1
    assert domain["failed"] == before["domains"]["recetadolce"]["failed"] == 1
    assert domain["articles"][:2] == before["domains"]["recetadolce"]["articles"]
    assert report["verified_total"] == before["verified_total"]
    assert report["failed_total"] == before["failed_total"]


@pytest.mark.unit
def test_failed_retry_authorization_preserves_history_and_survives_restart(tmp_path: Path) -> None:
    tracker = ProductionBatchTracker(
        project_root=tmp_path,
        batch_id="production-authorized-retry",
        domain_handles=["recetadolce"],
        target_per_domain=10,
    )
    tracker.start_keyword("recetadolce", "tarta de coco", "Postres", "Pinterest Trends")
    tracker.attach_run("recetadolce", "tarta de coco", "failed-run-1")
    tracker.complete_keyword("recetadolce", "tarta de coco", "Failed")
    before = json.loads(json.dumps(tracker.data))

    assert tracker.authorize_failed_retry(
        "recetadolce",
        " TARTA DE COCO ",
        "Codex quota reset; original run failed with HTTP 429",
        pipeline_run_id="failed-run-1",
    )
    authorized_report = json.loads(tracker.path.read_text(encoding="utf-8"))
    assert not tracker.authorize_failed_retry(
        "recetadolce", "tarta de coco", "Repeated authorization", pipeline_run_id="failed-run-1"
    )
    assert json.loads(tracker.path.read_text(encoding="utf-8")) == authorized_report
    article = tracker.data["domains"]["recetadolce"]["articles"][-1]
    assert article["state"] == "failed"
    assert article["roadmap_status"] == "Failed"
    assert article["completed_at"] == before["domains"]["recetadolce"]["articles"][-1]["completed_at"]
    assert article["retry_authorized"] is True
    assert "HTTP 429" in article["retry_reason"]
    assert tracker.data["failed_total"] == before["failed_total"] == 1
    assert tracker.published_count("recetadolce") == 0

    resumed = ProductionBatchTracker(
        project_root=tmp_path,
        batch_id="production-authorized-retry",
        domain_handles=["recetadolce"],
        target_per_domain=10,
    )
    assert "tarta de coco" not in resumed.attempted_keyword_keys("recetadolce")
    resumed.start_keyword("recetadolce", "tarta de coco", "Postres", "Pinterest Trends")
    resumed.attach_run("recetadolce", "tarta de coco", "failed-run-2")
    resumed.complete_keyword("recetadolce", "tarta de coco", "Failed")
    assert "tarta de coco" in resumed.attempted_keyword_keys("recetadolce")
    assert not resumed.authorize_failed_retry(
        "recetadolce", "tarta de coco", "Replay of old permission", pipeline_run_id="failed-run-1"
    )
    assert "tarta de coco" in resumed.attempted_keyword_keys("recetadolce")
    assert len(resumed.data["domains"]["recetadolce"]["articles"]) == 2
    assert resumed.data["failed_total"] == 2


@pytest.mark.unit
@pytest.mark.parametrize("status", ["Live", "Needs Verification", "Rejected", "interrupted"])
def test_failed_retry_rejects_other_states_without_changes(tmp_path: Path, status: str) -> None:
    tracker = ProductionBatchTracker(
        project_root=tmp_path,
        batch_id="production-retry-other-state",
        domain_handles=["recetagenial"],
        target_per_domain=10,
    )
    tracker.start_keyword("recetagenial", "pollo al horno", "Carnes", "Pinterest Trends")
    tracker.attach_run("recetagenial", "pollo al horno", "run-1")
    tracker.complete_keyword("recetagenial", "pollo al horno", status)
    before = json.loads(json.dumps(tracker.data))
    assert not tracker.authorize_failed_retry(
        "recetagenial", "pollo al horno", "Provider recovered", pipeline_run_id="run-1"
    )
    assert tracker.data == before


@pytest.mark.unit
def test_failed_retry_requires_latest_exact_run_and_reason(tmp_path: Path) -> None:
    tracker = ProductionBatchTracker(
        project_root=tmp_path,
        batch_id="production-retry-exact-run",
        domain_handles=["recetagenial"],
        target_per_domain=10,
    )
    for run_id in ("failed-run-1", "failed-run-2"):
        tracker.start_keyword("recetagenial", "pollo al horno", "Carnes", "Pinterest Trends")
        tracker.attach_run("recetagenial", "pollo al horno", run_id)
        tracker.complete_keyword("recetagenial", "pollo al horno", "Failed")
    before = json.loads(json.dumps(tracker.data))
    for handle, keyword, reason, run_id in (
        ("recetagenial", "pollo al horno", "Recovered", "failed-run-1"),
        ("recetagenial", "pollo al horno", "Recovered", ""),
        ("recetagenial", "pollo al horno", " ", "failed-run-2"),
        ("recetagenial", "missing recipe", "Recovered", "failed-run-2"),
        ("missing-domain", "pollo al horno", "Recovered", "failed-run-2"),
    ):
        assert not tracker.authorize_failed_retry(handle, keyword, reason, pipeline_run_id=run_id)
        assert tracker.data == before
    assert tracker.authorize_failed_retry(
        "recetagenial", "pollo al horno", "Recovered", pipeline_run_id="failed-run-2"
    )
    articles = tracker.data["domains"]["recetagenial"]["articles"]
    assert "retry_authorized" not in articles[0]
    assert articles[1]["retry_authorized"] is True


@pytest.mark.unit
def test_published_history_cannot_be_retried_by_shadowing_it_with_a_failed_row(tmp_path: Path) -> None:
    tracker = ProductionBatchTracker(
        project_root=tmp_path,
        batch_id="production-retry-published-history",
        domain_handles=["recetagenial"],
        target_per_domain=10,
    )
    tracker.start_keyword("recetagenial", "pollo al horno", "Carnes", "Pinterest Trends")
    tracker.complete_keyword("recetagenial", "pollo al horno", "Needs Verification")
    tracker.start_keyword("recetagenial", "POLLO AL HORNO", "Carnes", "Pinterest Trends")
    tracker.attach_run("recetagenial", "POLLO AL HORNO", "shadow-run")
    tracker.complete_keyword("recetagenial", "POLLO AL HORNO", "Failed")
    assert not tracker.authorize_failed_retry(
        "recetagenial", "pollo al horno", "Recovered", pipeline_run_id="shadow-run"
    )
    tracker.data["domains"]["recetagenial"]["articles"][-1]["retry_authorized"] = True
    assert "pollo al horno" in tracker.attempted_keyword_keys("recetagenial")
