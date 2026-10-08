from __future__ import annotations

import copy
import json
import sqlite3
import time
from dataclasses import replace
from pathlib import Path

import pytest

from rankstein.production_batch import (
    ProductionBatchTracker,
    PublicationImportProof,
    collect_publication_import_proofs,
)

pytestmark = pytest.mark.unit
HANDLES = ["recetadolce", "recetagenial"]


def _tracker(tmp_path: Path, batch_id: str, target: int = 2) -> ProductionBatchTracker:
    return ProductionBatchTracker(
        project_root=tmp_path, batch_id=batch_id, domain_handles=HANDLES, target_per_domain=target
    )


def _result(tracker, handle, keyword, run_id, status="Needs Verification"):
    tracker.start_keyword(handle, keyword, "Postres", "Pinterest")
    tracker.attach_run(handle, keyword, run_id)
    tracker.complete_keyword(handle, keyword, status)


def _proof(source, handle, keyword, run_id, *, verified=False):
    return PublicationImportProof(
        source_batch_id=source.batch_id,
        domain_handle=handle,
        keyword=keyword,
        pipeline_run_id=run_id,
        article_url=f"https://{handle}.com/tarta",
        hero_url=f"https://storage.example/{handle}/tarta.jpg",
        publication_reference="pipeline-events:publication+storage;Supabase-read-back",
        checked_at=time.time(),
        verification_reference="verified-campaign.json" if verified else "",
    )


def test_import_original_baseline_extends_selected_run_and_preserves_source(tmp_path):
    source = _tracker(tmp_path, "original", 10)
    destination = _tracker(tmp_path, "selected", 2)
    proofs = {}
    for handle, count in (("recetadolce", 4), ("recetagenial", 8)):
        for number in range(count):
            keyword, run_id = f"receta {number}", f"{handle}-{number}"
            _result(source, handle, keyword, run_id)
            proofs[run_id] = _proof(source, handle, keyword, run_id)
    _result(destination, "recetadolce", "intento fallido", "failed-new", "Failed")
    source_before = source.path.read_bytes()
    destination_before = copy.deepcopy(destination.data)
    imported = destination.import_published_results(
        source.data, source_batch_id="original", publication_proofs=proofs, extend_target_per_domain=10
    )
    assert imported["changed"] is True
    assert len(imported["imported"]) == 12
    assert imported["published_per_domain"] == {"recetadolce": 4, "recetagenial": 8}
    assert destination.data["batch_id"] == "selected"
    assert destination.target_per_domain == destination.data["target_per_domain"] == 10
    assert destination.data["total_target"] == 20
    assert destination.data["verified_total"] == 0
    assert destination.data["failed_total"] == destination_before["failed_total"] == 1
    assert (
        destination.data["domains"]["recetadolce"]["articles"][0]
        == (destination_before["domains"]["recetadolce"]["articles"][0])
    )
    assert source.path.read_bytes() == source_before
    assert source.data == json.loads(source_before)
    imported_article = destination.data["domains"]["recetadolce"]["articles"][1]
    assert imported_article["pipeline_run_id"] == "recetadolce-0"
    assert imported_article["state"] == "needs verification"
    assert imported_article["import_provenance"]["source_batch_id"] == "original"
    assert imported_article["failed_counted"] is False
    destination_report = destination.path.read_bytes()
    replay = destination.import_published_results(
        source.data, source_batch_id="original", publication_proofs=proofs, extend_target_per_domain=10
    )
    assert replay["changed"] is False
    assert replay["imported"] == []
    assert destination.path.read_bytes() == destination_report
    resumed = _tracker(tmp_path, "selected", 10)
    assert resumed.published_count("recetagenial") == 8


@pytest.mark.parametrize("status", ["Failed", "Staged", "Rejected"])
def test_nonpublished_and_running_source_rows_never_import(tmp_path, status):
    source, destination = _tracker(tmp_path, "source"), _tracker(tmp_path, "destination")
    _result(source, "recetadolce", "receta fallida", "failed", status)
    source.start_keyword("recetagenial", "receta activa", "Postres", "Pinterest")
    source.attach_run("recetagenial", "receta activa", "running")
    before = destination.path.read_bytes()
    result = destination.import_published_results(
        source.data, source_batch_id="source", publication_proofs={}
    )
    assert result["changed"] is False
    assert destination.path.read_bytes() == before


def test_import_requires_proof_and_finite_terminal_timestamp(tmp_path):
    source, destination = _tracker(tmp_path, "source"), _tracker(tmp_path, "destination")
    _result(source, "recetadolce", "receta uno", "missing-proof")
    _result(source, "recetagenial", "receta dos", "not-terminal")
    source.data["domains"]["recetagenial"]["articles"][0]["completed_at"] = None
    result = destination.import_published_results(
        source.data,
        source_batch_id="source",
        publication_proofs={"not-terminal": _proof(source, "recetagenial", "receta dos", "not-terminal")},
    )
    assert result["imported"] == []
    assert len(result["skipped"]) == 2
    assert destination.published_count("recetadolce") == 0


def test_verified_source_downgrades_without_current_full_chain_proof(tmp_path):
    source, destination = _tracker(tmp_path, "source"), _tracker(tmp_path, "destination")
    _result(source, "recetadolce", "receta uno", "run", "Live")
    proof = _proof(source, "recetadolce", "receta uno", "run")
    destination.import_published_results(
        source.data, source_batch_id="source", publication_proofs={"run": proof}
    )
    article = destination.data["domains"]["recetadolce"]["articles"][0]
    assert article["state"] == "needs verification"
    assert article["roadmap_status"] == "Needs Verification"
    assert destination.verified("recetadolce") == 0
    assert article["import_provenance"]["source_state"] == "verified"


def test_current_full_chain_proof_imports_verified_once(tmp_path):
    source, destination = _tracker(tmp_path, "source"), _tracker(tmp_path, "destination")
    _result(source, "recetagenial", "receta uno", "run", "Live")
    proof = _proof(source, "recetagenial", "receta uno", "run", verified=True)
    for _ in range(2):
        destination.import_published_results(
            source.data, source_batch_id="source", publication_proofs={"run": proof}
        )
    assert destination.verified("recetagenial") == 1
    assert destination.data["verified_total"] == 1
    assert len(destination.data["domains"]["recetagenial"]["articles"]) == 1


def test_quality_held_publication_cannot_gain_live_from_a_proof_reference(tmp_path):
    source, destination = _tracker(tmp_path, "source"), _tracker(tmp_path, "destination")
    _result(source, "recetadolce", "sin horno", "held-run")
    source_article = source.data["domains"]["recetadolce"]["articles"][0]
    source_article.update(invalidated_at=time.time(), reason="Quality hold")
    proof = _proof(source, "recetadolce", "sin horno", "held-run", verified=True)
    destination.import_published_results(
        source.data, source_batch_id="source", publication_proofs={"held-run": proof}
    )
    imported = destination.data["domains"]["recetadolce"]["articles"][0]
    assert imported["state"] == "needs verification"
    assert imported["reason"] == "Quality hold"
    assert imported["invalidated_at"] == source_article["invalidated_at"]
    assert destination.verified("recetadolce") == 0


def test_duplicate_baseline_preserves_existing_publication_and_latest_failure(tmp_path):
    source, destination = _tracker(tmp_path, "source"), _tracker(tmp_path, "destination")
    _result(destination, "recetadolce", "Tarta  de coco", "original-run", "Live")
    _result(destination, "recetadolce", " tarta de coco ", "later-failure", "Failed")
    _result(source, "recetadolce", "TARTA DE COCO", "source-run")
    before = destination.path.read_bytes()
    result = destination.import_published_results(
        source.data,
        source_batch_id="source",
        publication_proofs={"source-run": _proof(source, "recetadolce", "TARTA DE COCO", "source-run")},
    )
    assert result["changed"] is False
    assert destination.path.read_bytes() == before
    assert destination.published_count("recetadolce") == 1
    assert destination.verified("recetadolce") == 1
    assert destination.data["domains"]["recetadolce"]["articles"][-1]["state"] == "failed"


def test_import_caps_unique_publications_at_destination_target(tmp_path):
    source, destination = _tracker(tmp_path, "source", 10), _tracker(tmp_path, "destination", 1)
    proofs = {}
    for number in range(3):
        keyword, run_id = f"receta {number}", f"run-{number}"
        _result(source, "recetadolce", keyword, run_id)
        proofs[run_id] = _proof(source, "recetadolce", keyword, run_id)
    result = destination.import_published_results(
        source.data, source_batch_id="source", publication_proofs=proofs
    )
    assert len(result["imported"]) == 1
    assert len(result["skipped"]) == 2
    assert destination.published_count("recetadolce") == 1


@pytest.mark.parametrize("bad_field", ["source_batch_id", "domain_handle", "pipeline_run_id", "keyword"])
def test_bad_proof_identity_rolls_back_all_imports_and_target_extension(tmp_path, bad_field):
    source, destination = _tracker(tmp_path, "source"), _tracker(tmp_path, "destination")
    _result(source, "recetadolce", "receta uno", "first")
    _result(source, "recetagenial", "receta dos", "bad")
    proofs = {
        "first": _proof(source, "recetadolce", "receta uno", "first"),
        "bad": replace(_proof(source, "recetagenial", "receta dos", "bad"), **{bad_field: "wrong"}),
    }
    before = destination.path.read_bytes()
    with pytest.raises(ValueError, match="identity mismatch"):
        destination.import_published_results(
            source.data, source_batch_id="source", publication_proofs=proofs, extend_target_per_domain=10
        )
    assert destination.path.read_bytes() == before
    assert destination.data == json.loads(before)
    assert destination.target_per_domain == 2


def test_source_domain_set_mismatch_and_target_shrink_fail_closed(tmp_path):
    source, destination = _tracker(tmp_path, "source"), _tracker(tmp_path, "destination")
    before = destination.path.read_bytes()
    malformed = copy.deepcopy(source.data)
    malformed["domains"].pop("recetagenial")
    with pytest.raises(ValueError, match="domain set mismatch"):
        destination.import_published_results(malformed, source_batch_id="source", publication_proofs={})
    with pytest.raises(ValueError, match="cannot shrink"):
        destination.import_published_results(
            source.data, source_batch_id="source", publication_proofs={}, extend_target_per_domain=1
        )
    assert destination.path.read_bytes() == before


def test_active_or_stale_destination_report_cannot_be_imported_over(tmp_path):
    source, destination = _tracker(tmp_path, "source"), _tracker(tmp_path, "destination")
    destination.start_keyword("recetadolce", "activa", "Postres", "Pinterest")
    with pytest.raises(ValueError, match="idle checkpoint"):
        destination.import_published_results(source.data, source_batch_id="source", publication_proofs={})
    _result(destination, "recetadolce", "otra", "another", "Failed")
    altered = copy.deepcopy(destination.data)
    altered["updated_at"] += 1
    destination.path.write_text(json.dumps(altered), encoding="utf-8")
    with pytest.raises(ValueError, match="changed outside"):
        destination.import_published_results(source.data, source_batch_id="source", publication_proofs={})


def test_late_verification_of_import_does_not_remove_unrelated_failure_credit(tmp_path):
    source, destination = _tracker(tmp_path, "source"), _tracker(tmp_path, "destination")
    _result(source, "recetadolce", "publicada", "published-run")
    _result(destination, "recetadolce", "fallida", "failed-run", "Failed")
    destination.import_published_results(
        source.data,
        source_batch_id="source",
        publication_proofs={"published-run": _proof(source, "recetadolce", "publicada", "published-run")},
    )
    assert destination.reconcile_needs_verification(
        "recetadolce",
        "publicada",
        pipeline_run_id="published-run",
        primary_job_id="pin-job",
        pin_id="1082904672939731127",
        pin_url="https://www.pinterest.com/pin/1082904672939731127/",
        campaign_report="reviewed-campaign.json",
    )
    assert destination.data["failed_total"] == 1
    assert destination.data["verified_total"] == 1


def _publication_database(tmp_path, source, handle="recetadolce", keyword="receta", run_id="run"):
    _result(source, handle, keyword, run_id)
    path = tmp_path / "events.db"
    article_url = f"https://{handle}.com/receta"
    hero_url = f"https://storage.example/storage/v1/object/public/recipe-images/{handle}/receta-hero.png"
    with sqlite3.connect(path) as connection:
        connection.executescript(
            "CREATE TABLE pipeline_runs (id TEXT, domain_handle TEXT, keyword TEXT, slug TEXT);"
            "CREATE TABLE pipeline_events (id INTEGER PRIMARY KEY, run_id TEXT, stage TEXT, state TEXT, details_json TEXT);"
        )
        connection.execute(
            "INSERT INTO pipeline_runs VALUES (?, ?, ?, ?)", (run_id, handle, keyword, "receta")
        )
        for stage, details in (
            ("hero_upload", {"public_url": hero_url}),
            ("article_publish", {"article_url": article_url, "slug": "receta"}),
        ):
            connection.execute(
                "INSERT INTO pipeline_events (run_id, stage, state, details_json) VALUES (?, ?, 'complete', ?)",
                (run_id, stage, json.dumps(details)),
            )
    remote = {
        "success": True,
        "domain": handle,
        "title": "Receta",
        "featured_image_url": hero_url,
        "recipe_schema": {
            "recipeIngredient": ["2 zanahorias"],
            "recipeInstructions": [{"@type": "HowToStep", "text": "Ralla las zanahorias"}],
        },
    }
    return path, remote


def _collect(source, path, remote, **kwargs):
    calls = []

    def lookup(slug, handle):
        calls.append((slug, handle))
        return remote

    result = collect_publication_import_proofs(
        source.data,
        source_batch_id=source.batch_id,
        pipeline_db_path=path,
        domain_hosts={handle: f"{handle}.com" for handle in HANDLES},
        article_lookup=lookup,
        **kwargs,
    )
    return result, calls


def test_proof_collector_reads_exact_events_and_current_domain_recipe_without_mutation(tmp_path):
    source = _tracker(tmp_path, "source")
    path, remote = _publication_database(tmp_path, source)
    before_db, before_source = path.read_bytes(), source.path.read_bytes()
    result, calls = _collect(source, path, remote)
    assert calls == [("receta", "recetadolce")]
    assert set(result.proofs) == {"run"}
    assert result.rejected == {}
    proof = result.proofs["run"]
    assert proof.domain_handle == "recetadolce"
    assert proof.verification_reference == ""
    assert "article_publish:2;hero_upload:1" in proof.publication_reference
    assert path.read_bytes() == before_db
    assert source.path.read_bytes() == before_source
    assert "recipe_schema" not in vars(proof)


@pytest.mark.parametrize(
    "failure", ["wrong_domain", "changed_hero", "empty_ingredients", "empty_steps", "missing_article"]
)
def test_proof_collector_rejects_current_unproven_or_incomplete_article(tmp_path, failure):
    source = _tracker(tmp_path, "source")
    path, remote = _publication_database(tmp_path, source)
    if failure == "wrong_domain":
        remote["domain"] = "recetagenial"
    elif failure == "changed_hero":
        remote["featured_image_url"] = "https://storage.example/another.jpg"
    elif failure == "empty_ingredients":
        remote["recipe_schema"]["recipeIngredient"] = []
    elif failure == "empty_steps":
        remote["recipe_schema"]["recipeInstructions"] = [{"text": ""}]
    elif failure == "missing_article":
        remote["success"] = False
    result, _ = _collect(source, path, remote)
    assert result.proofs == {}
    assert "run" in result.rejected


@pytest.mark.parametrize(
    "failure", ["run_domain", "run_keyword", "public_domain", "later_publish_failure", "later_upload_failure"]
)
def test_proof_collector_rejects_wrong_or_stale_pipeline_identity(tmp_path, failure):
    source = _tracker(tmp_path, "source")
    path, remote = _publication_database(tmp_path, source)
    with sqlite3.connect(path) as connection:
        if failure == "run_domain":
            connection.execute("UPDATE pipeline_runs SET domain_handle='recetagenial'")
        elif failure == "run_keyword":
            connection.execute("UPDATE pipeline_runs SET keyword='otra receta'")
        elif failure == "public_domain":
            connection.execute(
                "UPDATE pipeline_events SET details_json=? WHERE stage='article_publish'",
                (json.dumps({"article_url": "https://unconfigured.example/receta", "slug": "receta"}),),
            )
        else:
            stage = "article_publish" if failure == "later_publish_failure" else "hero_upload"
            connection.execute(
                "INSERT INTO pipeline_events (run_id, stage, state, details_json) VALUES ('run', ?, 'failed', '{}')",
                (stage,),
            )
    result, calls = _collect(source, path, remote)
    assert result.proofs == {}
    assert "run" in result.rejected
    assert calls == []


def test_collector_never_treats_historical_verified_label_as_current_full_verification(tmp_path):
    source = _tracker(tmp_path, "source")
    path, remote = _publication_database(tmp_path, source)
    article = source.data["domains"]["recetadolce"]["articles"][0]
    article.update(state="verified", roadmap_status="Live")
    basic, _ = _collect(source, path, remote)
    assert basic.proofs["run"].verification_reference == ""
    complete, _ = _collect(
        source, path, remote, verification_validator=lambda handle, row: "reviewed-30pin.json"
    )
    assert complete.proofs["run"].verification_reference == "reviewed-30pin.json"
