"""Plan exact legacy Pinterest destination repairs without changing queue state.

Only IDs in a prior read-only link audit are considered. Canonical article proof
is fetched fresh; exact current payloads/states are captured after any supervisor
drain. The maintained queue API is called with dry_run=True through connections
which enforce SQLite mode=ro and query_only. There is deliberately no apply flag.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import contextlib
import hashlib
import html
import json
import re
import sqlite3
import sys
import threading
from datetime import UTC, datetime
from pathlib import Path
from urllib.request import Request, urlopen

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))
REASON = "Repair verified canonical recipe destinations and domain metadata for existing legacy remaster folder jobs after graceful drain"


def _recipe(value):
    if isinstance(value, dict):
        kind = value.get("@type")
        if (kind == "Recipe" or (isinstance(kind, list) and "Recipe" in kind)) and isinstance(
            value.get("name"), str
        ):
            return value
        values = value.values()
    elif isinstance(value, list):
        values = value
    else:
        return None
    for nested in values:
        found = _recipe(nested)
        if found:
            return found
    return None


def _article_proof(url):
    request = Request(url, headers={"User-Agent": "RankSteinCanonicalRepairDryRun/1.0"})
    with urlopen(request, timeout=20) as response:
        body = response.read(2_000_001)
        status, final_url = response.status, response.url
    if len(body) > 2_000_000:
        raise ValueError("Canonical article exceeds the proof byte limit")
    text = body.decode("utf-8", "replace")
    canonical = re.findall(r"<link[^>]+rel=[\"']canonical[\"'][^>]+href=[\"']([^\"']+)", text, re.I)
    recipe = None
    for attributes, content in re.findall(r"<script\b([^>]*)>(.*?)</script>", text, re.I | re.S):
        if "application/ld+json" not in attributes.lower():
            continue
        try:
            recipe = _recipe(json.loads(html.unescape(content)))
        except (TypeError, ValueError):
            continue
        if recipe:
            break
    if status != 200 or final_url != url or url not in canonical or recipe is None:
        raise ValueError(f"Canonical Recipe proof failed for {url}")
    host = url.split("/")[2]
    return url, {
        "status": status,
        "domain_handle": host.removeprefix("www.").removesuffix(".com"),
        "canonical_url": url,
        "recipe_schema": {"@type": "Recipe", "name": recipe["name"]},
        "checked_at": datetime.now(UTC).isoformat(),
        "schema_sha256": hashlib.sha256(
            json.dumps(recipe, ensure_ascii=False, sort_keys=True).encode()
        ).hexdigest(),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audit-report", type=Path, required=True)
    parser.add_argument("--queue-db", type=Path, default=PROJECT_ROOT / "data/queue/jobs.db")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    audit = json.loads(args.audit_report.read_text(encoding="utf-8"))
    mappings = {job["id"]: job for job in audit["jobs"] if job.get("proposed_destination")}
    if not mappings or len(mappings) > 1000:
        raise ValueError("Audit must contain one to 1000 explicit mapped job IDs")
    urls = sorted({job["proposed_destination"] for job in mappings.values()})
    if len(urls) > 20:
        raise ValueError("This bounded planner accepts at most 20 canonical articles")
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        proofs = dict(pool.map(_article_proof, urls))
    queue_path = args.queue_db.resolve(strict=True)

    def readonly():
        connection = sqlite3.connect(queue_path.as_uri() + "?mode=ro", uri=True, timeout=0.5)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only=ON")
        return connection

    with readonly() as connection:
        connection.execute("BEGIN")
        rows = {row["id"]: row for row in connection.execute("SELECT * FROM jobs")}
        dead = {row[0] for row in connection.execute("SELECT id FROM dlq")}
        connection.rollback()
    entries, excluded = [], []
    for job_id, mapping in mappings.items():
        row = rows.get(job_id)
        if row is None:
            excluded.append(
                {"id": job_id, "reason": "dead_preserved" if job_id in dead else "not_in_active_queue"}
            )
            continue
        payload = json.loads(row["payload_json"])
        article = proofs[mapping["proposed_destination"]]
        if row["status"] not in {"pending", "retry"}:
            excluded.append(
                {
                    "id": job_id,
                    "reason": "currently_" + row["status"],
                    "expected_payload": payload,
                    "article": article,
                }
            )
            continue
        entries.append(
            {"id": job_id, "expected_status": row["status"], "expected_payload": payload, "article": article}
        )
    now = datetime.now(UTC)
    output = args.output or PROJECT_ROOT / "data/reports/pinterest_draft_recovery" / (
        "canonical_destination_repair_dryrun_" + now.strftime("%Y%m%dT%H%M%SZ") + ".json"
    )
    report = {
        "generated_at": now.isoformat(),
        "dry_run": True,
        "apply_performed": False,
        "reason": REASON,
        "source_mapping_report": str(args.audit_report.resolve()),
        "article_proofs": proofs,
        "original_held_ids_preserved": [row["id"] for row in rows.values() if row["status"] == "held"],
        "excluded_current_rows": excluded,
        "entries": entries,
        "api_validation_pending": True,
        "api_result": None,
    }

    def save():
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    # Preserve fresh proof and exact entries before importing the browser-heavy
    # package. The report says pending until the queue API actually validates it.
    save()
    print(
        json.dumps(
            {
                "report": str(output),
                "entries": len(entries),
                "excluded": len(excluded),
                "api_validation_pending": True,
            }
        ),
        flush=True,
    )
    from pinterest_automation.job_queue import JobQueue

    class ReadOnlyQueue(JobQueue):
        @contextlib.contextmanager
        def _conn(self):
            connection = readonly()
            try:
                yield connection
            finally:
                connection.close()

    queue = object.__new__(ReadOnlyQueue)
    queue._db_file = queue_path
    queue._lock = threading.Lock()
    try:
        report["api_result"] = (
            queue.repair_upload_destinations(entries, reason=REASON, dry_run=True) if entries else None
        )
    except Exception as error:
        report["api_validation_error"] = {"type": type(error).__name__, "message": str(error)[:300]}
        raise
    finally:
        report["api_validation_pending"] = False
        save()
    result = report["api_result"] or {}
    print(
        json.dumps(
            {
                "report": str(output),
                "entries": len(entries),
                "repair_count": result.get("repair_count", 0),
                "hold_count": result.get("hold_count", 0),
                "apply_performed": False,
            }
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
