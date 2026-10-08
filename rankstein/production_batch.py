"""Durable progress state for bounded multidomain production batches."""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path


class ProductionBatchTracker:
    """Write an atomic dashboard-readable report while article workers run."""

    def __init__(
        self,
        *,
        project_root: Path,
        batch_id: str,
        domain_handles: list[str],
        target_per_domain: int,
    ) -> None:
        self.batch_id = batch_id
        self.target_per_domain = max(1, int(target_per_domain))
        self.path = project_root / "data" / "reports" / "production_batches" / f"{batch_id}.json"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        if self._load_existing(domain_handles):
            self._write()
            return
        now = time.time()
        self.data = {
            "batch_id": batch_id,
            "state": "running",
            "started_at": now,
            "updated_at": now,
            "completed_at": None,
            "target_per_domain": self.target_per_domain,
            "total_target": self.target_per_domain * len(domain_handles),
            "verified_total": 0,
            "failed_total": 0,
            "rejected_total": 0,
            "domains": {
                handle: {
                    "target": self.target_per_domain,
                    "verified": 0,
                    "failed": 0,
                    "rejected": 0,
                    "state": "running",
                    "running_keywords": [],
                    "articles": [],
                }
                for handle in domain_handles
            },
        }
        self._write()

    def _load_existing(self, domain_handles: list[str]) -> bool:
        """Resume a compatible incomplete report without losing verified work."""
        candidates: list[tuple[float, dict]] = []
        for candidate in (self.path, self.path.with_suffix(".tmp")):
            if not candidate.is_file():
                continue
            try:
                payload = json.loads(candidate.read_text(encoding="utf-8"))
                updated_at = float(payload.get("updated_at", candidate.stat().st_mtime))
            except (OSError, TypeError, ValueError, json.JSONDecodeError):
                continue
            candidates.append((updated_at, payload))
        if not candidates:
            return False
        existing = max(candidates, key=lambda item: item[0])[1]
        if existing.get("batch_id") != self.batch_id:
            raise ValueError(f"Batch report identity mismatch for {self.batch_id}")
        if existing.get("state") == "complete":
            raise ValueError(f"Completed batch {self.batch_id} cannot be reused")
        if int(existing.get("target_per_domain", 0)) != self.target_per_domain:
            raise ValueError(f"Batch target mismatch for {self.batch_id}")
        if set(existing.get("domains", {})) != set(domain_handles):
            raise ValueError(f"Batch domain set mismatch for {self.batch_id}")

        self.data = existing
        self.data["state"] = "running"
        self.data["completed_at"] = None
        self.data.pop("error", None)
        now = time.time()
        for domain in self.data["domains"].values():
            running_keywords = list(domain.get("running_keywords", []))
            interrupted = set(running_keywords)
            for article in reversed(domain.get("articles", [])):
                keyword = article.get("keyword")
                if keyword in interrupted and article.get("state") == "running":
                    article["state"] = "interrupted"
                    article["roadmap_status"] = "Failed"
                    article["reason"] = "Production worker restarted before verification"
                    article["completed_at"] = now
                    interrupted.discard(keyword)
            domain["failed"] = int(domain.get("failed", 0)) + len(running_keywords)
            domain["running_keywords"] = []
            if int(domain.get("verified", 0)) < int(domain.get("target", 0)):
                domain["state"] = "running"
                domain.pop("detail", None)
        self._recount()
        return True

    def verified(self, domain_handle: str) -> int:
        with self._lock:
            return int(self.data["domains"][domain_handle]["verified"])

    def published_count(self, domain_handle: str) -> int:
        """Count published articles, including those waiting for Pinterest proof."""
        with self._lock:
            latest = {
                str(article.get("keyword") or "").strip().casefold(): article
                for article in self.data["domains"][domain_handle].get("articles", [])
            }
            return sum(
                str(article.get("state") or "").replace("_", " ").casefold()
                in {"verified", "needs verification"}
                for article in latest.values()
            )

    def start_keyword(
        self,
        domain_handle: str,
        keyword: str,
        cluster: str,
        source: str,
    ) -> None:
        with self._lock:
            domain = self.data["domains"][domain_handle]
            if keyword not in domain["running_keywords"]:
                domain["running_keywords"].append(keyword)
            domain["articles"].append(
                {
                    "keyword": keyword,
                    "cluster": cluster,
                    "source": source,
                    "state": "running",
                    "pipeline_run_id": "",
                    "started_at": time.time(),
                    "completed_at": None,
                }
            )
            self._write()

    def attach_run(self, domain_handle: str, keyword: str, pipeline_run_id: str) -> None:
        if not pipeline_run_id:
            return
        with self._lock:
            article = self._latest_article(domain_handle, keyword)
            if article:
                article["pipeline_run_id"] = pipeline_run_id
            self._write()

    def reject_keyword(self, domain_handle: str, keyword: str, reason: str) -> None:
        with self._lock:
            domain = self.data["domains"][domain_handle]
            domain["rejected"] += 1
            domain["articles"].append(
                {
                    "keyword": keyword,
                    "state": "rejected",
                    "reason": reason,
                    "pipeline_run_id": "",
                    "started_at": time.time(),
                    "completed_at": time.time(),
                }
            )
            self._recount()
            self._write()

    def complete_keyword(self, domain_handle: str, keyword: str, status: str) -> None:
        with self._lock:
            domain = self.data["domains"][domain_handle]
            domain["running_keywords"] = [item for item in domain["running_keywords"] if item != keyword]
            article = self._latest_article(domain_handle, keyword)
            if not article or article.get("state") != "running":
                self._write()
                return
            article["state"] = "verified" if status == "Live" else status.casefold()
            article["roadmap_status"] = status
            article["completed_at"] = time.time()
            if status == "Live":
                domain["verified"] += 1
            else:
                domain["failed"] += 1
            if domain["verified"] >= domain["target"]:
                domain["state"] = "complete"
            self._recount()
            self._write()

    def invalidate_verified_keyword(
        self,
        domain_handle: str,
        keyword: str,
        reason: str,
        *,
        pipeline_run_id: str = "",
    ) -> bool:
        """Remove stale production credit when its verification proof is invalid.

        The operation is idempotent and deliberately targets a previously verified
        article.  It lets operators tighten a production proof contract without
        hand-editing the durable batch report or accidentally double-decrementing a
        domain on repeated audits.
        """

        with self._lock:
            domain = self.data["domains"][domain_handle]
            article = None
            for candidate in reversed(domain["articles"]):
                if candidate.get("keyword") != keyword:
                    continue
                if candidate.get("state") != "verified":
                    continue
                if pipeline_run_id and candidate.get("pipeline_run_id") != pipeline_run_id:
                    continue
                article = candidate
                break
            if article is None:
                self._write()
                return False

            article["state"] = "needs verification"
            article["roadmap_status"] = "Needs Verification"
            article["reason"] = str(reason)[:500]
            article["invalidated_at"] = time.time()
            domain["verified"] = max(0, int(domain.get("verified", 0)) - 1)
            if domain["verified"] < domain["target"]:
                domain["state"] = "running"
                domain.pop("detail", None)
            self.data["state"] = "running"
            self.data["completed_at"] = None
            self._recount()
            self._write()
            return True

    def restore_invalidated_keyword(
        self,
        domain_handle: str,
        keyword: str,
        proof_reference: str,
        *,
        pipeline_run_id: str = "",
    ) -> bool:
        """Restore batch credit only after replacement proof was validated."""

        with self._lock:
            domain = self.data["domains"][domain_handle]
            article = None
            for candidate in reversed(domain["articles"]):
                if candidate.get("keyword") != keyword:
                    continue
                if candidate.get("state") != "needs verification":
                    continue
                if "invalidated_at" not in candidate:
                    continue
                if pipeline_run_id and candidate.get("pipeline_run_id") != pipeline_run_id:
                    continue
                article = candidate
                break
            if article is None:
                self._write()
                return False

            article["state"] = "verified"
            article["roadmap_status"] = "Live"
            article["replacement_proof"] = str(proof_reference)[:500]
            article["reverified_at"] = time.time()
            article.pop("reason", None)
            self.data.pop("error", None)
            domain["verified"] = int(domain.get("verified", 0)) + 1
            if domain["verified"] >= domain["target"]:
                domain["state"] = "complete"
            else:
                domain["state"] = "running"
            self._recount()
            self._write()
            return True

    def reconcile_needs_verification(
        self,
        domain_handle: str,
        keyword: str,
        *,
        pipeline_run_id: str,
        primary_job_id: str,
        pin_id: str,
        pin_url: str,
        campaign_report: str,
    ) -> bool:
        """Credit one exact late-verified article without regenerating it.

        A normal ``Needs Verification`` completion is counted once in the
        domain's failed total.  Late Pinterest/remaster proof moves that same
        exact run to verified, removes the one failed count, and persists the
        proof used by the reconciler.  Replays and mismatched runs are no-ops.
        """

        if not pipeline_run_id:
            return False
        with self._lock:
            domain = self.data.get("domains", {}).get(domain_handle)
            if not isinstance(domain, dict):
                return False

            article = None
            for candidate in reversed(domain.get("articles", [])):
                if str(candidate.get("keyword") or "").casefold() != keyword.casefold():
                    continue
                if candidate.get("pipeline_run_id") != pipeline_run_id:
                    continue
                state = str(candidate.get("state") or "").replace("_", " ").casefold()
                if state != "needs verification":
                    return False
                article = candidate
                break
            if article is None:
                return False

            article["state"] = "verified"
            article["roadmap_status"] = "Live"
            article["reconciled_at"] = time.time()
            article["reconciliation_proof"] = {
                "primary_job_id": str(primary_job_id),
                "pin_id": str(pin_id),
                "pin_url": str(pin_url),
                "campaign_report": str(campaign_report),
            }
            article.pop("reason", None)
            domain["failed"] = max(0, int(domain.get("failed", 0)) - 1)
            domain["verified"] = int(domain.get("verified", 0)) + 1
            domain["running_keywords"] = [
                item for item in domain.get("running_keywords", []) if item != keyword
            ]
            if domain["verified"] >= int(domain.get("target", 0)):
                domain["state"] = "complete"
                domain.pop("detail", None)
            else:
                domain["state"] = "running"
            self.data.pop("error", None)
            self._recount()
            self._write()
            return True

    def mark_domain_waiting(self, domain_handle: str, reason: str) -> None:
        with self._lock:
            domain = self.data["domains"][domain_handle]
            domain["state"] = "waiting"
            domain["detail"] = reason
            self._write()

    def mark_domain_running(self, domain_handle: str) -> None:
        with self._lock:
            domain = self.data["domains"][domain_handle]
            if domain["verified"] < domain["target"]:
                domain["state"] = "running"
                domain.pop("detail", None)
            self._write()

    def finish_if_complete(self) -> bool:
        with self._lock:
            complete = all(domain["verified"] >= domain["target"] for domain in self.data["domains"].values())
            if complete:
                self.data["state"] = "complete"
                self.data["completed_at"] = time.time()
                self._write()
            return complete

    def fail(self, error: str) -> None:
        with self._lock:
            self.data["state"] = "failed"
            self.data["error"] = str(error)[:500]
            self.data["completed_at"] = time.time()
            self._write()

    def _latest_article(self, domain_handle: str, keyword: str) -> dict | None:
        articles = self.data["domains"][domain_handle]["articles"]
        for article in reversed(articles):
            if article.get("keyword") == keyword:
                return article
        return None

    def _recount(self) -> None:
        domains = self.data["domains"].values()
        self.data["verified_total"] = sum(int(item["verified"]) for item in domains)
        self.data["failed_total"] = sum(int(item["failed"]) for item in domains)
        self.data["rejected_total"] = sum(int(item["rejected"]) for item in domains)

    def _write(self) -> None:
        self.data["updated_at"] = time.time()
        temp_path = self.path.with_suffix(".tmp")
        temp_path.write_text(
            json.dumps(self.data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        last_error: PermissionError | None = None
        for attempt in range(20):
            try:
                os.replace(temp_path, self.path)
                return
            except PermissionError as exc:
                last_error = exc
                time.sleep(min(0.05 * (attempt + 1), 0.25))
        if last_error is not None:
            raise last_error
