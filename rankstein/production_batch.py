"""Durable progress state for bounded multidomain production batches."""

from __future__ import annotations

import copy
import json
import math
import os
import sqlite3
import threading
import time
import unicodedata
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import unquote, urlparse


def _keyword_key(value: object) -> str:
    return " ".join(unicodedata.normalize("NFKC", str(value or "")).split()).casefold()


def _result_state(value: object) -> str:
    return str(value or "").strip().replace("_", " ").casefold()


@dataclass(frozen=True)
class PublicationImportProof:
    """Exact-run publication evidence; full production credit is opt-in.

    Construct these through ``collect_publication_import_proofs``. A separate
    current full-chain verifier may provide ``verification_reference``; a
    historical pipeline status or source batch label is never sufficient.
    """

    source_batch_id: str
    domain_handle: str
    keyword: str
    pipeline_run_id: str
    article_url: str
    hero_url: str
    publication_reference: str
    checked_at: float
    verification_reference: str = ""


@dataclass(frozen=True)
class PublicationProofCollection:
    proofs: dict[str, PublicationImportProof] = field(default_factory=dict)
    rejected: dict[str, str] = field(default_factory=dict)


def collect_publication_import_proofs(
    source_batch: dict,
    *,
    source_batch_id: str,
    pipeline_db_path: Path,
    domain_hosts: Mapping[str, str],
    article_lookup: Callable[[str, str], dict],
    verification_validator: Callable[[str, dict], str] | None = None,
) -> PublicationProofCollection:
    """Read exact publication/storage events and current Supabase recipe proof.

    ``article_lookup`` is the maintained read-only
    ``get_article_data_from_supabase_by_slug(slug, domain_handle)`` function.
    No queue, roadmap, event, source batch, or remote article is mutated. The
    optional verification validator must independently recheck the current
    primary pin and complete source-quality-approved campaign before returning
    a nonempty reference. Publication-only proof deliberately downgrades a
    historical verified row to Needs Verification on import.
    """
    if not source_batch_id or source_batch.get("batch_id") != source_batch_id:
        raise ValueError("Source batch identity mismatch")
    domains = source_batch.get("domains")
    if not isinstance(domains, dict) or set(domains) != set(domain_hosts):
        raise ValueError("Publication proof domain set mismatch")
    database_path = Path(pipeline_db_path).resolve()
    result = PublicationProofCollection()
    seen_run_ids: set[str] = set()
    with sqlite3.connect(database_path.as_uri() + "?mode=ro", uri=True, timeout=5) as connection:
        connection.row_factory = sqlite3.Row
        for handle, domain in domains.items():
            if not isinstance(domain, dict):
                raise ValueError("Malformed source batch domain")
            host = str(domain_hosts[handle]).strip().casefold()
            if not host or urlparse("https://" + host).hostname != host:
                raise ValueError("Invalid configured public domain")
            for article in domain.get("articles", []):
                if not isinstance(article, dict) or _result_state(article.get("state")) not in {
                    "verified",
                    "needs verification",
                }:
                    continue
                run_id = str(article.get("pipeline_run_id") or "").strip()
                if not run_id:
                    result.rejected[f"{handle}:{_keyword_key(article.get('keyword'))}"] = (
                        "missing run identity"
                    )
                    continue
                if run_id in seen_run_ids:
                    result.proofs.pop(run_id, None)
                    result.rejected[run_id] = "ambiguous source pipeline run"
                    continue
                seen_run_ids.add(run_id)
                try:
                    row = connection.execute(
                        "SELECT domain_handle, keyword, slug FROM pipeline_runs WHERE id = ?", (run_id,)
                    ).fetchone()
                    if row is None or row["domain_handle"] != handle:
                        raise ValueError("pipeline run domain mismatch or missing run")
                    if _keyword_key(row["keyword"]) != _keyword_key(article.get("keyword")):
                        raise ValueError("pipeline run keyword mismatch")
                    slug = str(row["slug"] or "").strip()
                    if not slug or "/" in slug or slug in {".", ".."}:
                        raise ValueError("missing or unsafe published slug")
                    latest = {}
                    for event in connection.execute(
                        "SELECT id, stage, state, details_json FROM pipeline_events "
                        "WHERE run_id = ? AND stage IN ('article_publish', 'hero_upload') ORDER BY id",
                        (run_id,),
                    ):
                        latest[event["stage"]] = event
                    publish = latest.get("article_publish")
                    upload = latest.get("hero_upload")
                    if (
                        publish is None
                        or upload is None
                        or any(event["state"] != "complete" for event in (publish, upload))
                    ):
                        raise ValueError("latest publication/storage event is not complete")
                    publication = json.loads(publish["details_json"] or "{}")
                    storage = json.loads(upload["details_json"] or "{}")
                    article_url = str(publication.get("article_url") or "").strip()
                    article_address = urlparse(article_url)
                    if (
                        article_address.scheme != "https"
                        or article_address.netloc.casefold() != host
                        or unquote(article_address.path).strip("/") != slug
                        or article_address.query
                        or article_address.fragment
                        or publication.get("slug", slug) != slug
                    ):
                        raise ValueError("published URL does not match configured domain/slug")
                    hero_url = str(storage.get("public_url") or "").strip()
                    hero_address = urlparse(hero_url)
                    hero_path = unquote(hero_address.path)
                    if (
                        hero_address.scheme != "https"
                        or not hero_address.netloc
                        or "/storage/v1/object/public/" not in hero_path
                        or f"/{handle}/{slug}-hero." not in hero_path
                    ):
                        raise ValueError("storage URL does not match exact domain/slug")
                    try:
                        remote = article_lookup(slug, handle)
                    except Exception as exc:
                        raise ValueError("current published article lookup raised an error") from exc
                    if not isinstance(remote, dict) or remote.get("success") is not True:
                        raise ValueError("current published article read-back failed")
                    if remote.get("domain") != handle or not str(remote.get("title") or "").strip():
                        raise ValueError("current published article identity is missing or wrong")
                    if remote.get("featured_image_url") != hero_url:
                        raise ValueError("current article hero does not match exact storage event")
                    schema = remote.get("recipe_schema")
                    if not isinstance(schema, dict):
                        raise ValueError("current article recipe schema is missing")
                    ingredients = schema.get("recipeIngredient")
                    steps = schema.get("recipeInstructions")
                    if (
                        not isinstance(ingredients, list)
                        or not any(str(item or "").strip() for item in ingredients)
                        or not isinstance(steps, list)
                        or not any(
                            str(item.get("text") or "").strip()
                            if isinstance(item, dict)
                            else str(item or "").strip()
                            for item in steps
                        )
                    ):
                        raise ValueError("current article ingredients or steps are empty")
                    verification = ""
                    if _result_state(article.get("state")) == "verified" and verification_validator:
                        verification = str(
                            verification_validator(handle, copy.deepcopy(article)) or ""
                        ).strip()
                    proof = PublicationImportProof(
                        source_batch_id=source_batch_id,
                        domain_handle=handle,
                        keyword=str(article["keyword"]),
                        pipeline_run_id=run_id,
                        article_url=article_url,
                        hero_url=hero_url,
                        publication_reference=f"{database_path}#article_publish:{publish['id']};hero_upload:{upload['id']}",
                        checked_at=time.time(),
                        verification_reference=verification,
                    )
                    result.proofs[run_id] = proof
                except (ValueError, TypeError, KeyError, OSError) as exc:
                    result.rejected[run_id] = str(exc)[:240]
    return result


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
            published = {
                _keyword_key(article.get("keyword"))
                for article in self.data["domains"][domain_handle].get("articles", [])
                if _result_state(article.get("state")) in {"verified", "needs verification"}
            }
            return len(published - {""})

    def import_published_results(
        self,
        source_batch: dict,
        *,
        source_batch_id: str,
        publication_proofs: Mapping[str, PublicationImportProof],
        extend_target_per_domain: int | None = None,
    ) -> dict:
        """Import a proven baseline into an idle continuation, never its failures.

        Stop the destination worker or use its actual in-memory tracker at an
        idle checkpoint. Never construct a second tracker over an active worker
        report. This operation only writes the destination report; source data,
        article URLs, exact pipeline identities, and all existing attempts remain
        intact. Monotonic target extension is explicit. Existing published
        keywords win even when shadowed by later failure rows.
        """
        if not source_batch_id or source_batch_id == self.batch_id:
            raise ValueError("Source batch must have a distinct exact identity")
        source = copy.deepcopy(source_batch)
        if source.get("batch_id") != source_batch_id:
            raise ValueError("Source batch identity mismatch")
        with self._lock:
            expected_report = self.path.read_bytes()
            if json.loads(expected_report.decode("utf-8")) != self.data:
                raise ValueError("Destination report changed outside this tracker")
            domains = self.data.get("domains", {})
            source_domains = source.get("domains")
            if not isinstance(source_domains, dict) or set(source_domains) != set(domains):
                raise ValueError("Batch domain set mismatch")
            if self.data.get("state") == "complete":
                raise ValueError("Completed destination batch cannot be changed")
            if any(
                domain.get("running_keywords")
                or any(
                    _result_state(article.get("state")) == "running" for article in domain.get("articles", [])
                )
                for domain in domains.values()
            ):
                raise ValueError("Destination batch is not at an idle checkpoint")
            target = (
                self.target_per_domain if extend_target_per_domain is None else int(extend_target_per_domain)
            )
            if target < self.target_per_domain:
                raise ValueError("Batch target cannot shrink")
            if int(self.data.get("target_per_domain", 0)) != self.target_per_domain or any(
                int(domain.get("target", 0)) != self.target_per_domain for domain in domains.values()
            ):
                raise ValueError("Destination target identity mismatch")

            working = copy.deepcopy(self.data)
            report = {
                "source_batch_id": source_batch_id,
                "destination_batch_id": self.batch_id,
                "imported": [],
                "skipped": [],
                "target_per_domain": target,
            }
            seen_runs = {}
            for handle, source_domain in source_domains.items():
                if not isinstance(source_domain, dict) or not isinstance(
                    source_domain.get("articles", []), list
                ):
                    raise ValueError("Malformed source batch domain")
                destination = working["domains"][handle]
                published_keys = {
                    _keyword_key(article.get("keyword"))
                    for article in destination.get("articles", [])
                    if _result_state(article.get("state")) in {"verified", "needs verification"}
                } - {""}
                if len(published_keys) > target:
                    raise ValueError("Destination already exceeds the publication target")
                for article in source_domain.get("articles", []):
                    if not isinstance(article, dict):
                        raise ValueError("Malformed source article row")
                    state = _result_state(article.get("state"))
                    if state not in {"verified", "needs verification"}:
                        continue
                    run_id = str(article.get("pipeline_run_id") or "").strip()
                    key = _keyword_key(article.get("keyword"))
                    completed_at = article.get("completed_at")
                    if (
                        not run_id
                        or not key
                        or not isinstance(completed_at, (int, float))
                        or not math.isfinite(completed_at)
                        or completed_at <= 0
                    ):
                        report["skipped"].append(
                            {
                                "domain_handle": handle,
                                "pipeline_run_id": run_id,
                                "reason": "missing terminal exact-run identity",
                            }
                        )
                        continue
                    identity = (handle, key)
                    if run_id in seen_runs and seen_runs[run_id] != identity:
                        raise ValueError("Source pipeline run belongs to multiple domain/keyword identities")
                    seen_runs[run_id] = identity
                    if article.get("domain_handle", handle) != handle:
                        raise ValueError("Source article domain identity mismatch")
                    proof = publication_proofs.get(run_id)
                    if proof is None:
                        report["skipped"].append(
                            {
                                "domain_handle": handle,
                                "pipeline_run_id": run_id,
                                "reason": "current publication proof missing",
                            }
                        )
                        continue
                    if not isinstance(proof, PublicationImportProof) or (
                        proof.source_batch_id != source_batch_id
                        or proof.domain_handle != handle
                        or proof.pipeline_run_id != run_id
                        or _keyword_key(proof.keyword) != key
                        or not proof.publication_reference.strip()
                        or not proof.hero_url.strip()
                        or urlparse(proof.article_url).scheme != "https"
                        or not urlparse(proof.article_url).hostname
                        or not math.isfinite(proof.checked_at)
                        or proof.checked_at <= 0
                    ):
                        raise ValueError("Publication proof exact-run identity mismatch")
                    if key in published_keys:
                        report["skipped"].append(
                            {
                                "domain_handle": handle,
                                "pipeline_run_id": run_id,
                                "reason": "published keyword already preserved",
                            }
                        )
                        continue
                    if len(published_keys) >= target:
                        report["skipped"].append(
                            {
                                "domain_handle": handle,
                                "pipeline_run_id": run_id,
                                "reason": "publication target reached",
                            }
                        )
                        continue
                    # Reusing a run for a different destination keyword/domain is
                    # never safe, even if that destination attempt failed.
                    for destination_handle, destination_domain in working["domains"].items():
                        if any(
                            existing.get("pipeline_run_id") == run_id
                            and (destination_handle != handle or _keyword_key(existing.get("keyword")) != key)
                            for existing in destination_domain.get("articles", [])
                        ):
                            raise ValueError("Destination pipeline run identity collision")
                    imported = copy.deepcopy(article)
                    fully_verified = state == "verified" and bool(proof.verification_reference.strip())
                    imported["state"] = "verified" if fully_verified else "needs verification"
                    imported["roadmap_status"] = "Live" if fully_verified else "Needs Verification"
                    imported["failed_counted"] = False
                    imported.pop("retry_authorized", None)
                    imported["import_provenance"] = {
                        "source_batch_id": source_batch_id,
                        "domain_handle": handle,
                        "pipeline_run_id": run_id,
                        "imported_at": time.time(),
                        "article_url": proof.article_url,
                        "hero_url": proof.hero_url,
                        "publication_reference": proof.publication_reference,
                        "proof_checked_at": proof.checked_at,
                        "verification_reference": proof.verification_reference if fully_verified else "",
                        "source_state": state,
                    }
                    destination["articles"].append(imported)
                    if fully_verified:
                        destination["verified"] = int(destination.get("verified", 0)) + 1
                    published_keys.add(key)
                    report["imported"].append(
                        {
                            "domain_handle": handle,
                            "pipeline_run_id": run_id,
                            "keyword": imported["keyword"],
                            "state": imported["state"],
                        }
                    )
                destination["target"] = target
                if destination.get("state") == "complete" and int(destination.get("verified", 0)) < target:
                    destination["state"] = "waiting"
                    destination["detail"] = "Target extended; awaiting continuation"

            changed = bool(report["imported"]) or target != self.target_per_domain
            if changed:
                old_data, old_target = self.data, self.target_per_domain
                self.data, self.target_per_domain = working, target
                self.data["target_per_domain"] = target
                self.data["total_target"] = target * len(domains)
                self._recount()
                try:
                    if self.path.read_bytes() != expected_report:
                        raise ValueError("Destination report changed during reconciliation")
                    self._write()
                except Exception:
                    self.data, self.target_per_domain = old_data, old_target
                    raise
            report["changed"] = changed
            report["published_per_domain"] = {handle: self.published_count(handle) for handle in domains}
            return report

    def attempted_keyword_keys(self, domain_handle: str) -> set[str]:
        """Exclude attempted keywords unless their latest failure permits one retry.

        Retry permission stays on the failed attempt for audit history. A new
        attempt supersedes it, so restarting a worker cannot reuse old permission.
        Published work is excluded even if a later malformed report row shadows it.
        """
        with self._lock:
            articles = self.data["domains"][domain_handle].get("articles", [])
            latest = {str(article.get("keyword") or "").strip().casefold(): article for article in articles}
            published = {
                str(article.get("keyword") or "").strip().casefold()
                for article in articles
                if self._article_was_published(article)
            }
            return {
                keyword
                for keyword, article in latest.items()
                if keyword
                and (
                    keyword in published
                    or (
                        article.get("state") != "interrupted"
                        and not (article.get("state") == "failed" and article.get("retry_authorized") is True)
                    )
                )
            }

    def authorize_failed_retry(
        self,
        domain_handle: str,
        keyword: str,
        reason: str,
        *,
        pipeline_run_id: str,
    ) -> bool:
        """Authorize one exact latest failed attempt without erasing its history.

        Operators must establish a recoverable failure and fresh keyword evidence
        separately. This only changes batch retry permission; roadmap reservation,
        source research, publication limits, and provider gates still apply.
        """
        keyword_key = keyword.strip().casefold()
        if not keyword_key or not pipeline_run_id.strip() or not reason.strip():
            return False
        with self._lock:
            domain = self.data.get("domains", {}).get(domain_handle)
            if not isinstance(domain, dict) or self.data.get("state") == "complete":
                return False
            matches = [
                article
                for article in domain.get("articles", [])
                if str(article.get("keyword") or "").strip().casefold() == keyword_key
            ]
            if not matches or any(self._article_was_published(article) for article in matches):
                return False
            article = matches[-1]
            if (
                article.get("state") != "failed"
                or article.get("pipeline_run_id") != pipeline_run_id
                or article.get("retry_authorized") is True
            ):
                return False
            article["retry_authorized"] = True
            article["retry_authorized_at"] = time.time()
            article["retry_reason"] = reason.strip()[:500]
            self._write()
            return True

    @staticmethod
    def _article_was_published(article: dict) -> bool:
        return any(
            str(article.get(field) or "").replace("_", " ").strip().casefold()
            in {"verified", "live", "published", "needs verification"}
            for field in ("state", "roadmap_status")
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
            domain["state"] = "running"
            domain.pop("detail", None)
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
            if article.get("failed_counted") is not False:
                domain["failed"] = max(0, int(domain.get("failed", 0)) - 1)
            article["failed_counted"] = False
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
