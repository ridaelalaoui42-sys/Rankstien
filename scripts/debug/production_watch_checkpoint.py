"""One bounded, proof-backed checkpoint for the selected continuation.

Only destination batch metadata changes with --apply. Source reports, remote
articles, roadmaps, queues, and quarantined jobs are never rewritten.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

DESTINATION = "production-20261008-174143"
SOURCE = "production-17190"
SELECTED_RUNS = {
    "recetadolce-050ce1ea2d5a",
    "recetadolce-449ce57b961e",
    "recetadolce-64038f68f307",
    "recetadolce-60613fe7163f",
    "recetagenial-cb5c7f5488c7",
    "recetagenial-03b477ac6ee3",
}


def require_idle() -> None:
    import psutil

    for process in psutil.process_iter(["cmdline"]):
        arguments = process.info.get("cmdline") or []
        if any(Path(value).name.casefold() == "turbo_articles.py" for value in arguments):
            raise RuntimeError("Article owner is active; checkpoint refused")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    require_idle()

    from rankstein.domain import get_registry
    from rankstein.pipeline_events import PIPELINE_DB
    from rankstein.production_batch import ProductionBatchTracker, collect_publication_import_proofs
    from rankstein_mcp_server import get_article_data_from_supabase_by_slug

    directory = ROOT / "data/reports/production_batches"
    source_path = directory / f"{SOURCE}.json"
    archive_path = directory / "archive" / f"{DESTINATION}.json"
    destination_path = directory / f"{DESTINATION}.json"
    source_bytes = source_path.read_bytes()
    archive_bytes = archive_path.read_bytes()
    destination_bytes = destination_path.read_bytes()
    source = json.loads(source_bytes)
    selected = copy.deepcopy(source)
    for domain in selected["domains"].values():
        domain["articles"] = [
            article for article in domain["articles"] if article.get("pipeline_run_id") in SELECTED_RUNS
        ]
    selected_ids = {
        article["pipeline_run_id"]
        for domain in selected["domains"].values()
        for article in domain["articles"]
    }
    if selected_ids != SELECTED_RUNS:
        raise RuntimeError("Selected publication identities changed")

    with sqlite3.connect(PIPELINE_DB.resolve().as_uri() + "?mode=ro", uri=True, timeout=5) as connection:
        for domain in selected["domains"].values():
            for article in domain["articles"]:
                if "Pinterest" not in article.get("source", "") or "Google" not in article.get("source", ""):
                    raise RuntimeError("Selected publication has no recorded Pinterest/Google provenance")
                rows = connection.execute(
                    "SELECT stage,state,details_json FROM pipeline_events "
                    "WHERE run_id=? AND stage IN ('article_write','hero_image','source_extract') ORDER BY id",
                    (article["pipeline_run_id"],),
                ).fetchall()
                latest = {stage: (state, json.loads(details)) for stage, state, details in rows}
                if latest.get("article_write", ("", {})) != ("complete", {"provider": "openai-codex"}):
                    state, detail = latest.get("article_write", ("", {}))
                    if state != "complete" or detail.get("provider") != "openai-codex":
                        raise RuntimeError("Selected publication is not attested Codex output")
                state, detail = latest.get("hero_image", ("", {}))
                if state != "complete" or detail.get("source") != "codex":
                    raise RuntimeError("Selected publication has no approved Codex hero")
                state, detail = latest.get("source_extract", ("", {}))
                if state != "complete" or detail.get("sources_extracted", 0) < 2:
                    raise RuntimeError("Selected publication lacks independent recipe source extraction")

    registry = get_registry()
    lookup = getattr(get_article_data_from_supabase_by_slug, "fn", get_article_data_from_supabase_by_slug)
    collection = collect_publication_import_proofs(
        selected,
        source_batch_id=SOURCE,
        pipeline_db_path=PIPELINE_DB,
        domain_hosts={handle: registry.get(handle).domain for handle in selected["domains"]},
        article_lookup=lookup,
    )
    report = {
        "checked_utc": datetime.now(UTC).isoformat(),
        "selected_batch": DESTINATION,
        "source_batch": SOURCE,
        "publication_proofs": len(collection.proofs),
        "rejected": collection.rejected,
        "original_selected_archive_sha256": hashlib.sha256(archive_bytes).hexdigest(),
        "new_publication_credit": "Needs Verification only",
    }
    print(json.dumps(report), flush=True)
    if collection.rejected or len(collection.proofs) != len(SELECTED_RUNS):
        return 2
    if args.apply:
        require_idle()
        if source_path.read_bytes() != source_bytes or archive_path.read_bytes() != archive_bytes:
            raise RuntimeError("Original source/archive changed during audit")
        if destination_path.read_bytes() != destination_bytes:
            raise RuntimeError("Destination changed during audit")
        tracker = ProductionBatchTracker(
            project_root=ROOT,
            batch_id=DESTINATION,
            domain_handles=list(selected["domains"]),
            target_per_domain=10,
        )
        report["import"] = tracker.import_published_results(
            selected,
            source_batch_id=SOURCE,
            publication_proofs=collection.proofs,
        )
        report["invalidated_historical_credits"] = []
        for handle, domain in tracker.data["domains"].items():
            for article in list(domain["articles"]):
                if article.get("state") == "verified":
                    reason = (
                        "2026-10-13 proof audit: exact primary/remaster queue history or "
                        "current campaign assets missing; publication preserved pending fresh proof"
                    )
                    if tracker.invalidate_verified_keyword(
                        handle,
                        article["keyword"],
                        reason,
                        pipeline_run_id=article.get("pipeline_run_id", ""),
                    ):
                        report["invalidated_historical_credits"].append(article["pipeline_run_id"])
            tracker.mark_domain_waiting(
                handle,
                "Ten publications preserved; awaiting exact primary and clean 15-source/30-job proof",
            )
        report["published_per_domain"] = {
            handle: tracker.published_count(handle) for handle in tracker.data["domains"]
        }
        if any(count != 10 for count in report["published_per_domain"].values()):
            raise RuntimeError("Destination publication cap was not reached exactly")
        if source_path.read_bytes() != source_bytes or archive_path.read_bytes() != archive_bytes:
            raise RuntimeError("Original reports changed unexpectedly")
        output = ROOT / "data/reports/automation_watch/20261013_checkpoint.json"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(report), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
