"""Discover exact folder-upload destination repairs without changing the queue.

Feed the resulting report to plan_pinterest_destination_repair.py for fresh
canonical Recipe proof and a read-only repair_upload_destinations dry run.
This audit never constructs a writable JobQueue or selects held/DLQ jobs.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import re
import sqlite3
import sys
from collections import Counter
from datetime import UTC, date, datetime
from pathlib import Path
from urllib.parse import urlsplit

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))
SOURCE_SUFFIX = re.compile(r"(?:-|_)source[-_]\d+", re.I)
SOURCE_LABEL = re.compile(r"\bsource[\s_-]*\d+\b", re.I)


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def _target(image: str, domains, remaster_root: Path):
    path = Path(image).resolve(strict=True)
    parts = path.relative_to(remaster_root.resolve()).parts
    if not path.is_file() or len(parts) != 4:
        raise ValueError("Image lacks exact domain/date/article/file provenance")
    handle, day, slug, _filename = parts
    if date.fromisoformat(day).isoformat() != day or not re.fullmatch(r"[a-z0-9][a-z0-9-]*", slug):
        raise ValueError("Image has an invalid date or article slug")
    domain = domains.get(handle)
    if domain is None:
        raise ValueError("Image domain folder is not configured")
    configured = domain.domain if "://" in domain.domain else "https://" + domain.domain
    parsed = urlsplit(configured)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.port not in {None, 443}
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("Configured public domain is not an HTTPS origin")
    return handle, slug, f"https://{parsed.netloc}/{slug}"


def discover(queue_db: Path, domains, account_handles, remaster_root: Path):
    connection = sqlite3.connect(queue_db.resolve(strict=True).as_uri() + "?mode=ro", uri=True, timeout=3)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only=ON")
    try:
        connection.execute("BEGIN")
        rows = [dict(row) for row in connection.execute("SELECT * FROM jobs ORDER BY id")]
        dead = [dict(row) for row in connection.execute("SELECT * FROM dlq ORDER BY id")]
        connection.rollback()
    finally:
        connection.close()
    candidates, excluded = [], []
    folder_states = Counter()
    bad_source_count = 0
    for row in rows:
        if row["type"] != "pin_upload":
            continue
        payload = json.loads(row["payload_json"])
        extra = payload.get("extra") or {}
        if not isinstance(extra, dict) or extra.get("campaign_type") != "folder_batch":
            continue
        folder_states[row["status"]] += 1
        if row["status"] not in {"pending", "retry"}:
            continue
        bad_source = bool(SOURCE_SUFFIX.search(str(payload.get("link") or "")))
        bad_source_count += bad_source
        try:
            if row.get("result_json") is not None:
                raise ValueError("An existing upload result needs publication reconciliation")
            handle, slug, canonical = _target(payload.get("image_path") or "", domains, remaster_root)
            identities = {
                str(value).strip()
                for value in (payload.get("account_handle"), extra.get("account_handle"))
                if value is not None and str(value).strip()
            }
            if len(identities) != 1 or not identities.issubset(account_handles):
                raise ValueError("Unknown or conflicting account metadata")
            mismatches = []
            if payload.get("link") != canonical:
                mismatches.append("destination")
            for field, actual, expected in (
                ("domain_handle", payload.get("domain_handle"), handle),
                ("extra.domain_handle", extra.get("domain_handle"), handle),
                ("extra.slug", extra.get("slug"), slug),
            ):
                if actual != expected:
                    mismatches.append(field)
            if any(
                SOURCE_LABEL.search(str(payload.get(field) or ""))
                for field in ("title", "description", "alt_text")
            ):
                mismatches.append("filename_title_metadata")
            if not mismatches:
                continue
            candidates.append(
                {
                    "id": row["id"],
                    "status": row["status"],
                    "account_handle": next(iter(identities)),
                    "current_domain_handle": payload.get("domain_handle"),
                    "derived_domain_handle": handle,
                    "derived_slug": slug,
                    "current_destination": payload.get("link"),
                    "proposed_destination": canonical,
                    "image_path": payload.get("image_path"),
                    "bad_source_filename_destination": bad_source,
                    "metadata_mismatches": mismatches,
                    "expected_payload_sha256": _digest(payload),
                    "attempt": row.get("attempt"),
                    "max_attempts": row.get("max_attempts"),
                    "next_retry_at": row.get("next_retry_at"),
                }
            )
        except (OSError, TypeError, ValueError) as error:
            excluded.append({"id": row["id"], "status": row["status"], "reason": str(error)})
    held = [{"id": row["id"], "row_sha256": _digest(row)} for row in rows if row["status"] == "held"]
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "queue_db": str(queue_db.resolve()),
        "read_only": True,
        "apply_performed": False,
        "canonical_proof_pending": True,
        "queue_statuses": dict(Counter(row["status"] for row in rows)),
        "folder_job_statuses": dict(folder_states),
        "active_bad_source_destination_count": bad_source_count,
        "repair_candidate_count": len(candidates),
        "candidate_articles": dict(Counter(job["proposed_destination"] for job in candidates)),
        "metadata_mismatch_counts": dict(
            Counter(field for job in candidates for field in job["metadata_mismatches"])
        ),
        "held_rows_preserved": held,
        "dlq_rows_preserved": {"count": len(dead), "sha256": _digest(dead), "selected": 0},
        "excluded_preserved": excluded,
        "jobs": candidates,
    }


def verify_articles(report, proof_fetcher=None):
    """Exclude unproven canonical targets before producing repair API input."""
    if proof_fetcher is None:
        from scripts.dev.plan_pinterest_destination_repair import _article_proof

        proof_fetcher = _article_proof
    articles = {}
    rejected = {}
    domains = {job["proposed_destination"]: job["derived_domain_handle"] for job in report["jobs"]}

    def fetch(url):
        try:
            actual_url, proof = proof_fetcher(url)
            if actual_url != url or proof.get("canonical_url") != url or proof.get("status") != 200:
                raise ValueError("Canonical Recipe proof does not match its exact target")
            schema = proof.get("recipe_schema")
            kind = schema.get("@type") if isinstance(schema, dict) else None
            name = schema.get("name") if isinstance(schema, dict) else None
            if (
                not (kind == "Recipe" or (isinstance(kind, list) and "Recipe" in kind))
                or not isinstance(name, str)
                or not name.strip()
                or len(name.strip()) > 500
            ):
                raise ValueError("Canonical target lacks a named Recipe schema")
            # Domain identity comes from the configured registry/path mapping,
            # rather than inferring a handle by stripping a hostname suffix.
            proof = {**proof, "domain_handle": domains[url]}
            return url, proof, None
        except Exception as error:
            return (
                url,
                None,
                {
                    "type": type(error).__name__,
                    "http_status": getattr(error, "code", None),
                    "message": str(error)[:300],
                },
            )

    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        for url, proof, error in pool.map(fetch, sorted(domains)):
            if error is None:
                articles[url] = proof
            else:
                rejected[url] = error
    unproven = [job for job in report["jobs"] if job["proposed_destination"] not in articles]
    proven = [job for job in report["jobs"] if job["proposed_destination"] in articles]
    return {
        **report,
        "canonical_proof_pending": False,
        "article_proofs": articles,
        "rejected_articles": rejected,
        "discovered_candidate_count": len(report["jobs"]),
        "repair_candidate_count": len(proven),
        "unproven_jobs_preserved": unproven,
        "jobs": proven,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--queue-db", type=Path, default=PROJECT_ROOT / "data/queue/jobs.db")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--verify-articles", action="store_true")
    args = parser.parse_args()
    from pinterest_automation.config import get_config
    from rankstein.domain import get_registry

    domains = {domain.handle: domain for domain in get_registry().all()}
    report = discover(
        args.queue_db, domains, set(get_config().accounts), PROJECT_ROOT / "data/media/remaster_final"
    )
    if args.verify_articles:
        report = verify_articles(report)
    output = args.output or PROJECT_ROOT / "data/reports/pinterest_draft_recovery" / (
        "active_folder_destination_audit_" + datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + ".json"
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "report": str(output),
                "candidates": len(report["jobs"]),
                "canonical_articles": len(report["candidate_articles"]),
                "excluded": len(report["excluded_preserved"]),
                "apply_performed": False,
            }
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
