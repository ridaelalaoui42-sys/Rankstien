"""Observe existing Pinterest queue throughput without changing runtime state.

Examples:
    python scripts/dev/observe_pinterest_workers.py
    python scripts/dev/observe_pinterest_workers.py --duration 180 --interval 5

Only the JSON observation report is written. Queue reads use SQLite mode=ro
and one transaction spanning active jobs and the completion archive. Processing
concurrency measures queue leases, not simultaneous browser actions.
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
import time
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

PROJECT_ROOT = Path(__file__).resolve().parents[2]
PIN_ID_PATTERN = re.compile(r"\d{15,22}")
UNKNOWN_ACCOUNT = "_unconfigured"


def _object(value: object) -> dict:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (ValueError, TypeError):
            return {}
    return value if isinstance(value, dict) else {}


def verified_pin(result: object) -> dict | None:
    """Require successful upload/save proof, with a real-looking Pinterest ID."""
    result = _object(result)
    if result.get("success") is not True:
        return None
    pin_id = str(result.get("pin_id") or "").strip()
    pin_url = str(result.get("pin_url") or "").strip()
    try:
        parsed = urlparse(pin_url)
        url_id = parsed.path.strip("/").split("/")
        valid_url = (
            parsed.scheme == "https"
            and parsed.hostname in {"pinterest.com", "www.pinterest.com"}
            and len(url_id) == 2
            and url_id[0] == "pin"
            and PIN_ID_PATTERN.fullmatch(url_id[1]) is not None
        )
    except ValueError:
        valid_url = False
    if not PIN_ID_PATTERN.fullmatch(pin_id) and not valid_url:
        return None
    return {
        "pin_id": pin_id if PIN_ID_PATTERN.fullmatch(pin_id) else url_id[1],
        "pin_url": pin_url if valid_url else "",
    }


def _identity(payload: dict, accounts: set[str]) -> tuple[str, bool]:
    extra = _object(payload.get("extra"))
    handle = str(payload.get("account_handle") or extra.get("account_handle") or "").strip()
    campaign = str(payload.get("campaign_type") or extra.get("campaign_type") or "").lower()
    image = str(payload.get("image_path") or "").replace("\\", "/").lower()
    remaster = "remaster" in campaign or campaign == "folder_batch" or "/remaster" in image
    return handle if handle in accounts else UNKNOWN_ACCOUNT, remaster


def read_queue_snapshot(
    db_file: Path,
    accounts: list[str],
    *,
    observed_at: float | None = None,
    completed_since: float = 0,
    stale_after: float = 600,
    active_processing_since: float | None = None,
) -> tuple[dict, dict[str, dict]]:
    """Return sanitized queue metrics and verified completions in one snapshot."""
    now = time.time() if observed_at is None else observed_at
    account_set = set(accounts)
    account_rows = {
        account: {
            "processing": 0,
            "processing_remasters": 0,
            "stale_processing": 0,
            "previous_supervisor_processing": 0,
            "active_processing": 0,
            "active_processing_remasters": 0,
            "ready": 0,
            "ready_remasters": 0,
            "deferred": 0,
            "held": 0,
        }
        for account in [*sorted(account_set), UNKNOWN_ACCOUNT]
    }
    statuses: Counter = Counter()
    processing_types: Counter = Counter()
    active_processing_types: Counter = Counter()
    verified: dict[str, dict] = {}
    invalid_completions: set[str] = set()
    processing: list[dict] = []
    connection = sqlite3.connect(db_file.resolve().as_uri() + "?mode=ro", uri=True, timeout=3)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("PRAGMA query_only=ON")
        deadline = time.monotonic() + 10
        connection.set_progress_handler(lambda: int(time.monotonic() > deadline), 1000)
        connection.execute("BEGIN")
        rows = connection.execute(
            "SELECT id, type, payload_json, status, started_at, completed_at, "
            "next_retry_at, result_json FROM jobs"
        )
        for row in rows:
            payload = _object(row["payload_json"])
            account, remaster = _identity(payload, account_set)
            status = str(row["status"])
            job_type = row["type"] if row["type"] in {"pin_upload", "pin_save"} else "_other"
            statuses[
                status
                if status in {"pending", "retry", "processing", "held", "completed", "failed"}
                else "_other"
            ] += 1
            counts = account_rows[account]
            if status == "processing":
                counts["processing"] += 1
                counts["processing_remasters"] += int(remaster)
                age = max(0, now - float(row["started_at"])) if row["started_at"] else None
                stale = age is None or age > stale_after
                previous_supervisor = (
                    active_processing_since is not None
                    and row["started_at"] is not None
                    and row["started_at"] < active_processing_since
                )
                active = not stale and not previous_supervisor
                counts["stale_processing"] += int(stale)
                counts["previous_supervisor_processing"] += int(previous_supervisor)
                counts["active_processing"] += int(active)
                counts["active_processing_remasters"] += int(active and remaster)
                processing_types[job_type] += 1
                if active:
                    active_processing_types[job_type] += 1
                processing.append(
                    {
                        "job_id": row["id"],
                        "account": account,
                        "type": job_type,
                        "remaster": remaster,
                        "age_seconds": round(age, 3) if age is not None else None,
                        "stale": stale,
                        "previous_supervisor": previous_supervisor,
                        "active": active,
                    }
                )
            elif status in {"pending", "retry"}:
                if row["next_retry_at"] is None or row["next_retry_at"] <= now:
                    counts["ready"] += 1
                    counts["ready_remasters"] += int(remaster)
                else:
                    counts["deferred"] += 1
            elif status == "held":
                counts["held"] += 1
            if status == "completed" and (row["completed_at"] or 0) >= completed_since:
                _collect_completion(
                    {
                        "id": row["id"],
                        "type": row["type"],
                        "payload": payload,
                        "result": _object(row["result_json"]),
                        "status": status,
                        "started_at": row["started_at"],
                        "completed_at": row["completed_at"],
                    },
                    account_set,
                    verified,
                    invalid_completions,
                )
        for row in connection.execute(
            "SELECT id, job_json, completed_at FROM completed_log WHERE completed_at >= ?",
            (completed_since,),
        ):
            job = _object(row["job_json"])
            job["id"] = row["id"]
            job["completed_at"] = row["completed_at"]
            _collect_completion(job, account_set, verified, invalid_completions)
    finally:
        connection.close()
    active_accounts = [
        account for account in sorted(account_set) if account_rows[account]["active_processing"] > 0
    ]
    return {
        "timestamp": datetime.fromtimestamp(now, UTC).isoformat(),
        "observed_at": now,
        "queue_status_counts": dict(statuses),
        "accounts": account_rows,
        "processing_by_type": dict(processing_types),
        "active_processing_by_type": dict(active_processing_types),
        "processing_jobs": processing,
        "distinct_processing_accounts": len(active_accounts),
        "processing_accounts": active_accounts,
        "verified_completions_in_window": len(verified),
        "unverified_completed_jobs_in_window": len(invalid_completions - verified.keys()),
    }, verified


def _collect_completion(job: dict, accounts: set[str], verified: dict, invalid: set[str]) -> None:
    if job.get("type") not in {"pin_upload", "pin_save"}:
        return
    job_id = str(job.get("id") or "")
    proof = verified_pin(job.get("result")) if job.get("status") == "completed" else None
    if not proof:
        invalid.add(job_id)
        return
    account, remaster = _identity(_object(job.get("payload")), accounts)
    started, completed = job.get("started_at"), job.get("completed_at")
    elapsed = (
        max(0, completed - started)
        if isinstance(started, (int, float)) and isinstance(completed, (int, float))
        else None
    )
    verified[job_id] = {
        "job_id": job_id,
        "account": account,
        "type": job["type"],
        "remaster": remaster,
        "completed_at": completed,
        "processing_elapsed_seconds": round(elapsed, 3) if elapsed is not None else None,
        **proof,
    }


def summarize(samples: list[dict], completions: dict[str, dict], accounts: list[str]) -> dict:
    valid = [sample for sample in samples if "observed_at" in sample and not sample.get("error")]
    elapsed = max(0, valid[-1]["observed_at"] - valid[0]["observed_at"]) if valid else 0
    uploads = [row for row in completions.values() if row["type"] == "pin_upload"]
    remaster_uploads = [row for row in uploads if row["remaster"]]
    per_account = {}
    for account in [*sorted(set(accounts)), UNKNOWN_ACCOUNT]:
        matching = [row for row in completions.values() if row["account"] == account]
        account_uploads = [row for row in matching if row["type"] == "pin_upload"]
        account_remaster_uploads = [row for row in account_uploads if row["remaster"]]
        latencies = [
            row["processing_elapsed_seconds"]
            for row in matching
            if row["processing_elapsed_seconds"] is not None
        ]
        per_account[account] = {
            "verified_completions": len(matching),
            "verified_remaster_completions": sum(row["remaster"] for row in matching),
            "verified_upload_completions": len(account_uploads),
            "verified_remaster_upload_completions": len(account_remaster_uploads),
            "elapsed_seconds": round(elapsed, 3),
            "pins_per_minute": round(len(matching) * 60 / elapsed, 3) if elapsed > 0 else None,
            "verified_uploads_per_minute": round(len(account_uploads) * 60 / elapsed, 3)
            if elapsed > 0
            else None,
            "verified_remaster_uploads_per_minute": (
                round(len(account_remaster_uploads) * 60 / elapsed, 3) if elapsed > 0 else None
            ),
            "mean_processing_seconds": round(sum(latencies) / len(latencies), 3) if latencies else None,
            "peak_observed_processing_jobs": max(
                (sample["accounts"][account]["processing"] for sample in valid), default=0
            ),
            "peak_observed_active_processing_jobs": max(
                (sample["accounts"][account]["active_processing"] for sample in valid), default=0
            ),
        }
    worker_counts = sorted(
        {
            sample["supervisor"]["worker_count"]
            for sample in samples
            if isinstance(sample.get("supervisor", {}).get("worker_count"), int)
        }
    )
    return {
        "elapsed_seconds": round(elapsed, 3),
        "verified_completion_delta": len(completions),
        "verified_remaster_completion_delta": sum(row["remaster"] for row in completions.values()),
        "verified_upload_completion_delta": len(uploads),
        "verified_remaster_upload_completion_delta": len(remaster_uploads),
        "pins_per_minute": round(len(completions) * 60 / elapsed, 3) if elapsed > 0 else None,
        "verified_uploads_per_minute": round(len(uploads) * 60 / elapsed, 3) if elapsed > 0 else None,
        "verified_remaster_uploads_per_minute": round(len(remaster_uploads) * 60 / elapsed, 3)
        if elapsed > 0
        else None,
        "peak_observed_distinct_account_concurrency": max(
            (sample["distinct_processing_accounts"] for sample in valid), default=0
        ),
        "observed_worker_counts": worker_counts,
        "fixed_worker_count": len(worker_counts) == 1,
        "per_account": per_account,
        "measurement_note": "Concurrency counts non-stale configured-account queue leases started during the running supervisor's lifetime when its start time is known; earlier-owner rows remain visible but are excluded. It does not prove simultaneous browser actions. Throughput counts verified completed jobs once across active jobs and the completion archive. Compatibility fields verified_completion_delta, verified_remaster_completion_delta, pins_per_minute and their per-account equivalents combine uploads and saves. The upload-specific fields count only pin_upload jobs, so saving an existing pin never increases verified upload throughput.",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--duration", type=float, default=0, help="Observation seconds (default: one snapshot; maximum 3600)."
    )
    parser.add_argument("--interval", type=float, default=5, help="Seconds between snapshots (minimum 0.5).")
    parser.add_argument(
        "--stale-after",
        type=float,
        default=600,
        help="Exclude older processing leases from concurrency (seconds).",
    )
    parser.add_argument("--output", type=Path, help="Optional JSON report path.")
    args = parser.parse_args(argv)
    if not 0 <= args.duration <= 3600 or args.interval < 0.5 or args.stale_after <= 0:
        parser.error("duration must be 0..3600, interval >= 0.5, and stale-after > 0")
    sys.path.insert(0, str(PROJECT_ROOT))
    from pinterest_automation.config import get_config
    from pinterest_automation.job_queue import DB_FILE
    from pinterest_automation.runtime_state import supervisor_status

    accounts = sorted(get_config().accounts)
    started = time.time()
    monotonic_start = time.monotonic()
    samples: list[dict] = []
    completions: dict[str, dict] = {}
    baseline: set[str] = set()
    interrupted = False
    try:
        while True:
            now = time.time()
            supervisor = supervisor_status()
            supervisor_started_at = supervisor.get("started_at") if supervisor.get("running") else None
            try:
                sample, verified = read_queue_snapshot(
                    DB_FILE,
                    accounts,
                    observed_at=now,
                    completed_since=started,
                    stale_after=args.stale_after,
                    active_processing_since=(
                        supervisor_started_at if isinstance(supervisor_started_at, (int, float)) else None
                    ),
                )
                if not samples:
                    baseline = set(verified)
                completions.update({key: value for key, value in verified.items() if key not in baseline})
            except (OSError, sqlite3.Error) as exc:
                sample = {
                    "observed_at": now,
                    "error": f"Queue observation unavailable ({type(exc).__name__})",
                }
            sample["supervisor"] = supervisor
            samples.append(sample)
            remaining = args.duration - (time.monotonic() - monotonic_start)
            if remaining <= 0 or (len(samples) == 1 and sample.get("error")):
                break
            time.sleep(min(args.interval, remaining))
    except KeyboardInterrupt:
        interrupted = True
    output = args.output or (
        PROJECT_ROOT
        / "data"
        / "reports"
        / "pinterest_scaling"
        / f"workers_observation_{datetime.now(UTC).strftime('%Y%m%dT%H%M%S_%fZ')}.json"
    )
    report = {
        "schema_version": 1,
        "observer": "read_only_live_queue",
        "started_at": datetime.fromtimestamp(started, UTC).isoformat(),
        "configured_accounts": accounts,
        "requested_duration_seconds": args.duration,
        "sampling_interval_seconds": args.interval,
        "stale_processing_after_seconds": args.stale_after,
        "interrupted": interrupted,
        "samples": samples,
        "new_verified_completions": list(completions.values()),
        "summary": summarize(samples, completions, accounts),
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"report_path": str(output.resolve()), "summary": report["summary"]}, indent=2))
    return 1 if any(sample.get("error") for sample in samples) else 0


if __name__ == "__main__":
    raise SystemExit(main())
