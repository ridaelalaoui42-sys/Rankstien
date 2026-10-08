from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest
from pydantic import SecretStr

import rankstein.production_reconcile as reconcile
from rankstein.domain import Domain
from rankstein.keyword_roadmap import KeywordRow, read_keyword_rows, write_keyword_rows
from rankstein.pipeline_events import (
    record_pipeline_stage,
    set_pipeline_run_status,
    start_pipeline_run,
)
from rankstein.production_batch import ProductionBatchTracker


def _domain(tmp_path: Path) -> Domain:
    domain_root = tmp_path / "data" / "domains" / "recetagenial"
    return Domain(
        handle="recetagenial",
        domain="recetagenial.com",
        display_name="RecetaGenial",
        language="es",
        niche="recetas",
        root=domain_root,
        keywords_file=domain_root / "keywords.md",
        sessions_dir=domain_root / "sessions",
        output_dir=domain_root / "output",
        branding_dir=domain_root / "branding",
        pinterest_email="user@example.com",
        pinterest_password=SecretStr("secret"),
        supabase_url="https://supabase.example",
        supabase_service_role_key=SecretStr("service-role"),
        categories=("Ensaladas",),
        boards_default={"Ensaladas": "ENSALADES", "_default": "ENSALADES"},
    )


def _complete_report(*, run_id: str, slug: str) -> dict:
    assets = []
    jobs = []
    for index in range(1, 16):
        pair_id = f"pair-{index:02d}"
        for variant in ("viral_visual", "recipe_card"):
            assets.append(
                {
                    "pair_id": pair_id,
                    "variant": variant,
                    "source": "pinterest",
                    "original_pin_id": f"source-{index:02d}",
                }
            )
            jobs.append({"job_id": f"job-{index:02d}-{variant}"})
    return {
        "success": True,
        "domain_handle": "recetagenial",
        "slug": slug,
        "pipeline_run_id": run_id,
        "target_count": 30,
        "source_target": 15,
        "accepted_source_count": 15,
        "pair_count": 15,
        "generated_count": 30,
        "missing_count": 0,
        "source_counts": {"pinterest": 15, "native": 0},
        "variant_contract": {
            "variants_per_source": 2,
            "variants": ["viral_visual", "recipe_card"],
        },
        "assets": assets,
        "enqueue": {
            "success": True,
            "images_enqueued": 30,
            "jobs_enqueued": 30,
            "details": jobs,
        },
    }


def _setup_needs_verification(tmp_path: Path) -> tuple[Domain, str, Path]:
    domain = _domain(tmp_path)
    keyword = "ensalada saludable"
    slug = "ensalada-saludable-de-quinoa"
    write_keyword_rows(
        domain.keywords_file,
        "RecetaGenial Keyword Roadmap",
        [
            KeywordRow(
                keyword=keyword,
                cluster="Ensaladas",
                source="Pinterest",
                target_blog=domain.domain,
                status="Needs Verification",
            )
        ],
    )
    pipeline_db = tmp_path / "data" / "runtime" / "pipeline_events.db"
    run_id = start_pipeline_run(
        domain_handle=domain.handle,
        keyword=keyword,
        cluster="Ensaladas",
        source="Pinterest",
        db_path=pipeline_db,
    )
    record_pipeline_stage(
        run_id,
        "article_publish",
        "complete",
        "Article published",
        details={
            "slug": slug,
            "article_url": f"https://{domain.domain}/{slug}",
        },
        slug=slug,
        db_path=pipeline_db,
    )
    set_pipeline_run_status(run_id, "needs_verification", db_path=pipeline_db)
    tracker = ProductionBatchTracker(
        project_root=tmp_path,
        batch_id="production-test",
        domain_handles=[domain.handle],
        target_per_domain=1,
    )
    tracker.start_keyword(domain.handle, keyword, "Ensaladas", "Pinterest")
    tracker.attach_run(domain.handle, keyword, run_id)
    tracker.complete_keyword(domain.handle, keyword, "Needs Verification")
    return domain, run_id, pipeline_db


def _primary_outcome(domain: Domain, slug: str) -> dict:
    pin_id = "1148488342515527632"
    return {
        "found": True,
        "state": "completed",
        "type": "pin_upload",
        "priority": 1,
        "payload": {
            "domain_handle": domain.handle,
            "account_handle": "r1",
            "link": f"https://{domain.domain}/{slug}",
            "extra": {
                "domain_handle": domain.handle,
                "account_handle": "r1",
                "source": "direct_upload_via_supervisor",
            },
        },
        "result": {
            "success": True,
            "pin_id": pin_id,
            "pin_url": f"https://www.pinterest.com/pin/{pin_id}/",
        },
        "errors": [],
    }


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.parametrize("use_live_tracker", [False, True])
async def test_reconcile_promotes_only_after_supabase_and_exact_campaign_proof(
    tmp_path: Path, monkeypatch, use_live_tracker
) -> None:
    domain, run_id, pipeline_db = _setup_needs_verification(tmp_path)
    slug = "ensalada-saludable-de-quinoa"
    pin_id = "1148488342515527632"
    report_path = tmp_path / "data" / "reports" / "campaigns" / "report.json"
    report_path.parent.mkdir(parents=True)
    report_path.write_text(
        json.dumps(_complete_report(run_id=run_id, slug=slug)),
        encoding="utf-8",
    )
    live_tracker = None
    if use_live_tracker:
        live_tracker = ProductionBatchTracker(
            project_root=tmp_path,
            batch_id="production-test",
            domain_handles=[domain.handle],
            target_per_domain=1,
        )
        live_tracker.data["domains"]["recetadolce"] = {
            "target": 1,
            "verified": 0,
            "failed": 0,
            "rejected": 0,
            "state": "running",
            "running_keywords": [],
            "articles": [],
        }
        live_tracker.data["total_target"] = 2
        live_tracker.start_keyword("recetadolce", "tarta de coco", "Postres", "Pinterest Trends")

    class Registry:
        def get(self, handle: str) -> Domain:
            assert handle == domain.handle
            return domain

    supabase_pin = {"value": ""}
    article_reads = 0
    remaster_kwargs = {}

    def get_article(article_slug: str, domain_handle: str) -> dict:
        nonlocal article_reads
        article_reads += 1
        assert article_slug == slug
        assert domain_handle == domain.handle
        return {
            "success": True,
            "title": "Ensalada saludable de quinoa",
            "pinterest_pin_id": supabase_pin["value"],
            "recipe_schema": {
                "recipeIngredient": ["200 g de quinoa"],
                "recipeInstructions": [{"text": "Mezcla los ingredientes."}],
            },
            "chef_tip": "Sirve fría.",
            "excerpt": "Ensalada fresca.",
            "category": "Ensaladas",
        }

    def update_pin(article_slug: str, proof_pin_id: str, domain_handle: str) -> dict:
        assert (article_slug, proof_pin_id, domain_handle) == (slug, pin_id, domain.handle)
        supabase_pin["value"] = proof_pin_id
        return {"success": True, "slug": slug, "pin_id": proof_pin_id}

    async def launch_remaster(**kwargs) -> dict:
        remaster_kwargs.update(kwargs)
        return {
            "success": True,
            "report_path": str(report_path),
            "generated_count": 30,
            "pair_count": 15,
            "jobs_enqueued": 30,
            "reused_existing_report": True,
        }

    monkeypatch.setattr(reconcile, "get_registry", lambda: Registry())
    monkeypatch.setattr(reconcile, "_get_primary_job_outcome", lambda job_id: _primary_outcome(domain, slug))
    monkeypatch.setattr(reconcile, "_expected_upload_account", lambda *args: "r1")
    monkeypatch.setattr(reconcile, "_get_supabase_article", get_article)
    monkeypatch.setattr(reconcile, "_update_supabase_pin", update_pin)
    monkeypatch.setattr(reconcile, "_launch_remaster_campaign", launch_remaster)

    result = await reconcile.reconcile_production_article(
        project_root=tmp_path,
        batch_id="production-test",
        domain_handle=domain.handle,
        pipeline_run_id=run_id,
        primary_job_id="primary-1",
        pipeline_db_path=pipeline_db,
        batch_tracker=live_tracker,
    )

    assert result["success"] is True
    assert result["reconciled"] is True
    assert result["pin_id"] == pin_id
    assert result["campaign_report"] == str(report_path)
    assert article_reads == 2
    assert remaster_kwargs["keyword"] == "ensalada saludable"
    assert remaster_kwargs["title"] == "Ensalada saludable de quinoa"
    assert remaster_kwargs["slug"] == slug
    assert remaster_kwargs["pipeline_run_id"] == run_id
    assert remaster_kwargs["recipe_ingredients"] == ["200 g de quinoa"]
    assert remaster_kwargs["recipe_steps"] == ["Mezcla los ingredientes."]

    batch = json.loads(
        (tmp_path / "data" / "reports" / "production_batches" / "production-test.json").read_text(
            encoding="utf-8"
        )
    )
    article = batch["domains"][domain.handle]["articles"][-1]
    assert batch["verified_total"] == 1
    assert batch["failed_total"] == 0
    if use_live_tracker:
        assert batch["domains"]["recetadolce"]["running_keywords"] == ["tarta de coco"]
        assert batch["domains"]["recetadolce"]["articles"][-1]["state"] == "running"
    assert article["reconciliation_proof"]["primary_job_id"] == "primary-1"
    assert read_keyword_rows(domain.keywords_file)[0].status == "Live"
    with sqlite3.connect(pipeline_db) as connection:
        status = connection.execute("SELECT status FROM pipeline_runs WHERE id = ?", (run_id,)).fetchone()[0]
        events = connection.execute(
            "SELECT stage, state FROM pipeline_events WHERE run_id = ? ORDER BY id", (run_id,)
        ).fetchall()
    assert status == "complete"
    assert ("primary_pin_publish", "complete") in events
    assert events[-1] == ("verification", "complete")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_reconcile_rejects_primary_job_for_wrong_article_host_before_mutation(
    tmp_path: Path, monkeypatch
) -> None:
    domain, run_id, pipeline_db = _setup_needs_verification(tmp_path)
    outcome = _primary_outcome(domain, "ensalada-saludable-de-quinoa")
    outcome["payload"]["link"] = "https://attacker.example/ensalada-saludable-de-quinoa"

    class Registry:
        def get(self, handle: str) -> Domain:
            return domain

    monkeypatch.setattr(reconcile, "get_registry", lambda: Registry())
    monkeypatch.setattr(reconcile, "_get_primary_job_outcome", lambda job_id: outcome)
    monkeypatch.setattr(reconcile, "_expected_upload_account", lambda *args: "r1")
    monkeypatch.setattr(
        reconcile,
        "_update_supabase_pin",
        lambda *args: pytest.fail("Supabase must not be mutated for mismatched proof"),
    )
    monkeypatch.setattr(
        reconcile,
        "_launch_remaster_campaign",
        lambda **kwargs: pytest.fail("remaster must not run for mismatched proof"),
    )

    with pytest.raises(reconcile.ReconciliationError, match="article host"):
        await reconcile.reconcile_production_article(
            project_root=tmp_path,
            batch_id="production-test",
            domain_handle=domain.handle,
            pipeline_run_id=run_id,
            primary_job_id="primary-1",
            pipeline_db_path=pipeline_db,
        )

    report = json.loads(
        (tmp_path / "data" / "reports" / "production_batches" / "production-test.json").read_text(
            encoding="utf-8"
        )
    )
    assert report["verified_total"] == 0
    assert report["failed_total"] == 1


@pytest.mark.unit
def test_production_reconcile_cli_shape() -> None:
    from rankstein.cli import build_parser

    args = build_parser().parse_args(
        [
            "production",
            "reconcile",
            "--batch-id",
            "production-test",
            "--domain",
            "recetagenial",
            "--pipeline-run-id",
            "recetagenial-run-1",
            "--primary-job-id",
            "primary-1",
        ]
    )

    assert args.batch_id == "production-test"
    assert args.domain == "recetagenial"
    assert args.pipeline_run_id == "recetagenial-run-1"
    assert args.primary_job_id == "primary-1"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_reconcile_replay_uses_stored_proof_without_repeating_side_effects(
    tmp_path: Path, monkeypatch
) -> None:
    domain, run_id, pipeline_db = _setup_needs_verification(tmp_path)
    slug = "ensalada-saludable-de-quinoa"
    pin_id = "1148488342515527632"
    report_path = tmp_path / "data" / "reports" / "campaigns" / "report.json"
    report_path.parent.mkdir(parents=True)
    report_path.write_text(
        json.dumps(_complete_report(run_id=run_id, slug=slug)),
        encoding="utf-8",
    )

    class Registry:
        def get(self, handle: str) -> Domain:
            return domain

    supabase_pin = {"value": ""}
    update_count = 0
    remaster_count = 0

    def get_article(article_slug: str, domain_handle: str) -> dict:
        return {
            "success": True,
            "title": "Ensalada saludable de quinoa",
            "pinterest_pin_id": supabase_pin["value"],
            "recipe_schema": {
                "recipeIngredient": ["200 g de quinoa"],
                "recipeInstructions": [{"text": "Mezcla los ingredientes."}],
            },
            "category": "Ensaladas",
        }

    def update_pin(*args) -> dict:
        nonlocal update_count
        update_count += 1
        supabase_pin["value"] = pin_id
        return {"success": True, "pin_id": pin_id}

    async def launch_remaster(**kwargs) -> dict:
        nonlocal remaster_count
        remaster_count += 1
        return {"success": True, "report_path": str(report_path)}

    monkeypatch.setattr(reconcile, "get_registry", lambda: Registry())
    monkeypatch.setattr(reconcile, "_get_primary_job_outcome", lambda job_id: _primary_outcome(domain, slug))
    monkeypatch.setattr(reconcile, "_expected_upload_account", lambda *args: "r1")
    monkeypatch.setattr(reconcile, "_get_supabase_article", get_article)
    monkeypatch.setattr(reconcile, "_update_supabase_pin", update_pin)
    monkeypatch.setattr(reconcile, "_launch_remaster_campaign", launch_remaster)

    first = await reconcile.reconcile_production_article(
        project_root=tmp_path,
        batch_id="production-test",
        domain_handle=domain.handle,
        pipeline_run_id=run_id,
        primary_job_id="primary-1",
        pipeline_db_path=pipeline_db,
    )
    second = await reconcile.reconcile_production_article(
        project_root=tmp_path,
        batch_id="production-test",
        domain_handle=domain.handle,
        pipeline_run_id=run_id,
        primary_job_id="primary-1",
        pipeline_db_path=pipeline_db,
    )

    assert first["reconciled"] is True
    assert second["reconciled"] is False
    assert second["already_reconciled"] is True
    assert update_count == 1
    assert remaster_count == 1


@pytest.mark.unit
@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda value: value.update({"type": "pin_save"}), "priority-1 pin_upload"),
        (lambda value: value.update({"priority": 5}), "priority-1 pin_upload"),
        (
            lambda value: value["payload"]["extra"].update({"source": "enqueue_pin_mcp"}),
            "direct_upload_via_supervisor",
        ),
        (
            lambda value: value["payload"].update({"domain_handle": "recetadolce"}),
            "conflicting domain_handle",
        ),
        (
            lambda value: value["payload"].update({"account_handle": "other"}),
            "conflicting account_handle",
        ),
        (
            lambda value: value["result"].update(
                {"pin_url": "https://www.pinterest.com/pin/1148488342515527639/"}
            ),
            "same pin_id",
        ),
    ],
)
def test_primary_job_proof_rejects_every_identity_mismatch(
    tmp_path: Path, monkeypatch, mutation, message: str
) -> None:
    domain = _domain(tmp_path)
    outcome = _primary_outcome(domain, "ensalada-saludable-de-quinoa")
    mutation(outcome)
    monkeypatch.setattr(reconcile, "_expected_upload_account", lambda *args: "r1")

    with pytest.raises(reconcile.ReconciliationError, match=message):
        reconcile._validate_primary_job(
            outcome,
            domain=domain,
            slug="ensalada-saludable-de-quinoa",
        )
