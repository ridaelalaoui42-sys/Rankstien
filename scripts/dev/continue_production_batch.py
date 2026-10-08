"""Proof-backed publication carry-forward at an idle production checkpoint.

Dry-run is the default. --apply changes only the destination batch report.
Original reports, Supabase articles, roadmaps and Pinterest queues are preserved.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def _require_idle() -> None:
    import psutil

    for process in psutil.process_iter(["cmdline"]):
        arguments = process.info.get("cmdline") or []
        if any(Path(value).name.casefold() == "turbo_articles.py" for value in arguments):
            raise RuntimeError("Article worker is active; wait for an idle continuation checkpoint")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-batch", required=True)
    parser.add_argument("--destination-batch", required=True)
    parser.add_argument("--target-per-domain", type=int, default=10)
    parser.add_argument("--apply", action="store_true")
    arguments = parser.parse_args()
    for batch_id in (arguments.source_batch, arguments.destination_batch):
        if not re.fullmatch(r"production-\d{8}-\d{6}", batch_id):
            parser.error("Expected an exact production batch ID")
    if not 1 <= arguments.target_per_domain <= 20:
        parser.error("Target must be between 1 and 20 articles per domain")
    _require_idle()

    from rankstein.domain import get_registry
    from rankstein.pipeline_events import PIPELINE_DB
    from rankstein.production_batch import (
        ProductionBatchTracker,
        collect_publication_import_proofs,
    )
    from rankstein_mcp_server import get_article_data_from_supabase_by_slug

    report_directory = ROOT / "data" / "reports" / "production_batches"
    source_path = report_directory / f"{arguments.source_batch}.json"
    original_bytes = source_path.read_bytes()
    source = json.loads(original_bytes)
    destination = json.loads(
        (report_directory / f"{arguments.destination_batch}.json").read_text(encoding="utf-8")
    )
    registry = get_registry()
    lookup = getattr(get_article_data_from_supabase_by_slug, "fn", get_article_data_from_supabase_by_slug)
    collection = collect_publication_import_proofs(
        source,
        source_batch_id=arguments.source_batch,
        pipeline_db_path=PIPELINE_DB,
        domain_hosts={handle: registry.get(handle).domain for handle in source["domains"]},
        article_lookup=lookup,
    )
    print(
        json.dumps({"publication_proofs": len(collection.proofs), "rejected": collection.rejected}),
        flush=True,
    )
    if collection.rejected:
        return 2
    if not arguments.apply:
        return 0
    _require_idle()
    if source_path.read_bytes() != original_bytes:
        raise RuntimeError("Original report changed during proof collection; repeat the audit")
    tracker = ProductionBatchTracker(
        project_root=ROOT,
        batch_id=arguments.destination_batch,
        domain_handles=list(source["domains"]),
        target_per_domain=int(destination["target_per_domain"]),
    )
    result = tracker.import_published_results(
        source,
        source_batch_id=arguments.source_batch,
        publication_proofs=collection.proofs,
        extend_target_per_domain=arguments.target_per_domain,
    )
    for handle in source["domains"]:
        tracker.mark_domain_waiting(handle, "Proven publications carried forward; awaiting dashboard resume")
    print(json.dumps(result, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
