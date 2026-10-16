"""Recover only reviewed selected-batch primary completions; never restore jobs."""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import unquote, urlparse

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
BATCH_ID = "production-20261008-174143"
EXACT_JOB_IDS = (
    "679db0e3",
    "60cbc872",
    "c2a804d0",
    "b2d9fe6e",
    "95fa4971",
    "ebe50991",
    "93493e08",
    "15613d3f",
    "7daaff7f",
    "eca5a95c",
    "ab3086e6",
    "8441d0a5",
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    from pinterest_automation.job_queue import get_job_queue
    from rankstein.domain import get_registry
    from rankstein.pipeline_events import PIPELINE_DB

    report_dir = ROOT / "data/reports/production_batches"
    protected = [
        report_dir / f"{BATCH_ID}.json",
        report_dir / "archive" / f"{BATCH_ID}.json",
        report_dir / "production-20261008-022241.json",
        report_dir / "archive/production-20261008-022241.json",
    ]
    hashes = {
        str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in protected if path.is_file()
    }
    batch = json.loads(protected[0].read_text(encoding="utf-8"))
    if batch["batch_id"] != BATCH_ID:
        raise RuntimeError("Selected batch identity changed")
    registry = get_registry()
    selected_jobs = {}
    with sqlite3.connect(PIPELINE_DB.resolve().as_uri() + "?mode=ro", uri=True, timeout=3) as connection:
        for handle, domain in batch["domains"].items():
            articles = [
                item
                for item in domain["articles"]
                if str(item.get("state") or "").strip().replace("_", " ").casefold()
                in {"verified", "needs verification"}
            ]
            if len(articles) != 10:
                raise RuntimeError("Selected publication cap is not exactly ten per domain")
            for article in articles:
                run_id = article["pipeline_run_id"]
                run = connection.execute(
                    "SELECT slug FROM pipeline_runs WHERE id=? AND domain_handle=?", (run_id, handle)
                ).fetchone()
                if run is None:
                    raise RuntimeError("Selected publication pipeline identity missing")
                rows = connection.execute(
                    "SELECT details_json FROM pipeline_events WHERE run_id=? AND stage='primary_pin_publish' ORDER BY id DESC LIMIT 50",
                    (run_id,),
                ).fetchall()
                for row in rows:
                    details = json.loads(row[0])
                    job_id = details.get("primary_job_id") or details.get("job_id")
                    if job_id:
                        selected_jobs[job_id] = {"domain": handle, "run_id": run_id, "slug": run[0]}
                        break
    if not set(EXACT_JOB_IDS).issubset(selected_jobs):
        raise RuntimeError("Reviewed exact job IDs no longer match selected pipeline events")
    snapshot = ROOT / "data/backups/20261008T231554630397Z/data/queue/jobs.db"
    with sqlite3.connect(snapshot.resolve().as_uri() + "?mode=ro", uri=True, timeout=3) as connection:
        for job_id in EXACT_JOB_IDS:
            row = connection.execute("SELECT job_json FROM completed_log WHERE id=?", (job_id,)).fetchone()
            if row is None:
                raise RuntimeError("Reviewed primary completion missing from snapshot")
            job = json.loads(row[0])
            payload = job["payload"]
            extra = payload.get("extra") or {}
            identity = selected_jobs[job_id]
            parsed = urlparse(payload.get("link") or "")
            if (
                job.get("priority") != 1
                or (payload.get("source") or extra.get("source")) != "direct_upload_via_supervisor"
                or (payload.get("domain_handle") or extra.get("domain_handle")) != identity["domain"]
                or parsed.hostname != registry.get(identity["domain"]).domain
                or unquote(parsed.path.rstrip("/").rsplit("/", 1)[-1]) != identity["slug"]
            ):
                raise RuntimeError("Reviewed completion does not prove the exact selected article")
    queue = get_job_queue()
    recovery = queue.recover_completion_evidence(snapshot, list(EXACT_JOB_IDS), dry_run=not args.apply)
    after_hashes = {path: hashlib.sha256(Path(path).read_bytes()).hexdigest() for path in hashes}
    if hashes != after_hashes:
        raise RuntimeError("Protected production report changed during evidence recovery")
    result = {
        "checked_utc": datetime.now(UTC).isoformat(),
        "batch_id": BATCH_ID,
        "applied": args.apply,
        "recovery": recovery,
        "selected_primary_identities": selected_jobs,
        "protected_report_hashes": hashes,
        "queue_stats": queue.get_stats(),
        "publication_credit_changed": False,
    }
    output = (
        ROOT
        / "data/reports/automation_watch"
        / (
            datetime.now(UTC).strftime("%Y%m%d")
            + ("_primary_recovery_applied.json" if args.apply else "_primary_recovery_preview.json")
        )
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"report": str(output), "recovery": recovery, "queue_stats": result["queue_stats"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
