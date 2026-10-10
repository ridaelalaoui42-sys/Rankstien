"""Build evidence-backed per-keyword workflow snapshots for the dashboard."""

from __future__ import annotations

import json
import re
import sqlite3
import time
import unicodedata
from collections import defaultdict
from collections.abc import Iterable
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

STAGE_DEFINITIONS = (
    ("keyword_search", "Keyword search", "Research", "rankstein.trend_intelligence"),
    (
        "keyword_selected",
        "Keyword selected",
        "Research",
        "keyword_roadmap.reserve_pending_keywords",
    ),
    ("source_scrape", "Article search", "Research", "scrape_news_sources"),
    ("source_extract", "Source extraction", "Research", "extract_article_content"),
    ("article_write", "Article writing", "Article", "backend.scripts.turbo_articles"),
    ("quality_check", "Quality validation", "Article", "validate_article_quality"),
    ("hero_image", "Hero generation", "Visuals", "hero_image_pipeline"),
    ("hero_upload", "Image storage", "Visuals", "upload_image_to_supabase"),
    ("article_publish", "Article publish", "Delivery", "publish_article_to_supabase"),
    ("primary_pin", "Primary pin design", "Pinterest", "create_article_pin"),
    (
        "primary_pin_publish",
        "Primary pin upload",
        "Pinterest",
        "automation_upload_pin_direct",
    ),
    (
        "pinterest_siphon",
        "Pinterest siphon",
        "Pinterest",
        "backend.services.remasterer",
    ),
    ("remaster", "Paired pin studio", "Pinterest", "backend.services.remasterer"),
    ("queue", "Queue creation", "Distribution", "enqueue_article_remasters"),
    (
        "distribution",
        "Pin distribution",
        "Distribution",
        "pinterest_automation.supervisor",
    ),
    (
        "verification",
        "Final verification",
        "Delivery",
        "primary pin proof + 15 pairs / 30 queued jobs",
    ),
)
STAGE_INDEX = {key: index for index, (key, *_rest) in enumerate(STAGE_DEFINITIONS)}
TERMINAL_STATES = {"complete", "failed", "warning"}
ACTIVE_QUEUE_STATES = {"pending", "processing", "retry"}
ONGOING_STAGE_STATES = {
    "running",
    "queued",
    "waiting",
    "retry",
    "retrying",
    "processing",
    "researching",
    "pending_retry",
}
ONGOING_WORKFLOW_STATES = {
    "running",
    "queued",
    "waiting",
    "retry",
    "retrying",
    "processing",
    "researching",
    "distributing",
    "publishing",
    "in_progress",
}
TERMINAL_WORKFLOW_STATES = {
    "complete",
    "completed",
    "live",
    "verified",
    "succeeded",
    "failed",
    "stopped",
    "interrupted",
    "cancelled",
    "canceled",
    "rejected",
}
REQUIRED_SOURCE_PAIRS = 15
REQUIRED_PIN_ASSETS = 30
REQUIRED_QUEUE_JOBS = 30
STALE_RUNNING_SECONDS = 2 * 60 * 60


def build_pipeline_payload(
    root: Path, *, limit: int = 12, live_only: bool = False, history_limit: int | None = None
) -> dict[str, Any]:
    """Return recent and active keyword pipelines from maintained runtime state."""

    root = Path(root)
    now = time.time()
    batch = _read_current_production_batch(root)
    batch_articles = batch.get("articles", {})
    event_runs = _read_event_runs(root, include_run_ids=batch_articles)
    reports = _read_remaster_reports(root)
    queue_groups = _read_queue_groups(root)
    roadmap = _read_roadmap_statuses(root)
    recovery = _read_recovery_proof(root)

    campaigns: dict[tuple[str, str], dict[str, Any]] = {}
    run_keys: dict[str, tuple[str, str]] = {}
    campaign_aliases: dict[tuple[str, str], tuple[str, str]] = {}
    applied_report_times: dict[tuple[str, str], float] = {}
    deferred_queues: dict[tuple[str, str], dict[str, Any]] = {}

    for run in event_runs:
        domain = _domain_handle(run.get("domain_handle", ""))
        keyword_slug = _slugify(run.get("keyword"))
        slug = _slugify(run.get("slug") or keyword_slug)
        key = (domain, keyword_slug or slug)
        if key in campaigns:
            continue
        campaign = _new_campaign(
            domain=domain,
            keyword=run.get("keyword", ""),
            title=run.get("keyword", ""),
            slug=slug,
            updated_at=float(run.get("updated_at") or now),
            run_id=run.get("id", ""),
        )
        campaign["run_status"] = run.get("status", "running")
        batch_article = batch_articles.get(str(run.get("id") or ""))
        if batch_article:
            campaign.update(
                {
                    "in_current_batch": True,
                    "batch_id": batch.get("batch_id", ""),
                    "batch_state": batch_article.get("state", ""),
                }
            )
        for event in run.get("events", []):
            _apply_event(campaign, event, root=root)
        campaigns[key] = campaign
        if slug:
            campaign_aliases[(domain, slug)] = key
        if run.get("id"):
            run_keys[run["id"]] = key

    for report in reports:
        domain = _domain_handle(report.get("domain_handle", ""))
        slug = _slugify(report.get("slug") or report.get("title") or report.get("keyword"))
        run_id = str(report.get("pipeline_run_id") or "")
        report_key = (domain, slug)
        key = run_keys.get(run_id) or campaign_aliases.get(report_key) or report_key
        report_updated_at = float(report.get("_updated_at") or 0)
        if report_updated_at <= applied_report_times.get(key, float("-inf")):
            continue
        campaign = campaigns.get(key)
        if campaign is None:
            campaign = _new_campaign(
                domain=domain,
                keyword=report.get("keyword", ""),
                title=report.get("title", ""),
                slug=slug,
                updated_at=report["_updated_at"],
                run_id=run_id or f"report:{slug}",
            )
            campaigns[key] = campaign
        _apply_remaster_report(campaign, report)
        applied_report_times[key] = report_updated_at
        if run_id:
            run_keys[run_id] = key

    for queue_key, queue in queue_groups.items():
        run_id = queue.get("pipeline_run_id", "")
        key = run_keys.get(run_id) or campaign_aliases.get(queue_key) or queue_key
        campaign = campaigns.get(key)
        if campaign is None:
            if live_only and not queue.get("processing") and key not in recovery:
                # Aggregate old queue-only lanes without allocating their stage trees.
                # The selected recent history is expanded below for normal inspection.
                campaigns[key] = _queue_history_summary(key, queue, roadmap)
                deferred_queues[key] = queue
                continue
            campaign = _new_campaign(
                domain=key[0],
                keyword=queue.get("title", "") or key[1].replace("-", " ").title(),
                title=queue.get("title", ""),
                slug=key[1],
                updated_at=queue.get("updated_at", now),
                run_id=run_id or f"queue:{key[0]}:{key[1]}",
            )
            campaigns[key] = campaign
        _apply_queue_evidence(campaign, queue)

    for proof_key, proof in recovery.items():
        key = campaign_aliases.get(proof_key) or proof_key
        campaign = campaigns.get(key)
        if campaign is None:
            campaign = _new_campaign(
                domain=proof_key[0],
                keyword=proof.get("title", "") or proof_key[1].replace("-", " ").title(),
                title=proof.get("title", ""),
                slug=proof_key[1],
                updated_at=proof.get("updated_at", now),
                run_id=f"proof:{proof_key[0]}:{proof_key[1]}",
            )
            campaigns[key] = campaign
        _apply_primary_proof(campaign, proof)

    for key, campaign in campaigns.items():
        if key in deferred_queues:
            continue
        keyword_key = (
            campaign["domain_handle"],
            _slugify(campaign.get("keyword", "")),
        )
        campaign["roadmap_status"] = roadmap.get(keyword_key) or roadmap.get(key, "")
        _finalize_campaign(campaign, now=now)

    for campaign in campaigns.values():
        campaign["is_ongoing"] = _campaign_is_ongoing(campaign)

    ordered = sorted(
        campaigns.values(),
        key=lambda item: (
            0 if item.get("in_current_batch") else 1,
            {"active": 0, "waiting": 1, "attention": 2, "complete": 3, "recent": 4}.get(
                item["overall_state"],
                4,
            ),
            -float(item.get("updated_at") or 0),
        ),
    )
    visible = ordered[: max(1, limit)]
    ongoing = [item for item in ordered if item["is_ongoing"]]
    history = [item for item in ordered if not item["is_ongoing"]]
    if live_only:
        history.sort(key=lambda item: -float(item.get("updated_at") or 0))
    recent_history = history[: max(0, history_limit if history_limit is not None else limit)]
    if deferred_queues:
        for index, item in enumerate(recent_history):
            key = (item["domain_handle"], item["slug"])
            queue = deferred_queues.get(key)
            if queue is None:
                continue
            campaign = _new_campaign(
                domain=key[0],
                keyword=item["keyword"],
                title=item["title"],
                slug=key[1],
                updated_at=item["updated_at"],
                run_id=item["id"],
            )
            _apply_queue_evidence(campaign, queue)
            campaign["roadmap_status"] = item["roadmap_status"]
            _finalize_campaign(campaign, now=now)
            campaign["is_ongoing"] = False
            recent_history[index] = campaign
    return {
        "stages": [
            {"key": key, "label": label, "phase": phase, "service": service}
            for key, label, phase, service in STAGE_DEFINITIONS
        ],
        "campaigns": ongoing if live_only else visible,
        # The live dashboard consumes this collection. ``campaigns`` remains the
        # recent evidence/history feed so completed artifacts are not discarded.
        "ongoing_campaigns": ongoing if live_only else ongoing[: max(1, limit)],
        "history_campaigns": recent_history,
        "history_truncated": len(recent_history) < len(history),
        "total_campaigns": len(ordered),
        "ongoing_total": len(ongoing),
        "history_total": len(history),
        "summary": {
            "ongoing": len(ongoing),
            "active": sum(item["overall_state"] == "active" for item in ongoing),
            "waiting": sum(item["overall_state"] == "waiting" for item in ongoing),
            "attention": sum(item["overall_state"] == "attention" for item in ordered),
            "complete": sum(item["overall_state"] == "complete" for item in ordered),
            "pins_pending": sum(item["queue"].get("active", 0) for item in ordered),
            "pins_published": sum(item["queue"].get("completed", 0) for item in ordered),
            "pins_dead": sum(item["queue"].get("dead", 0) for item in ordered),
            "pins_held": sum(item["queue"].get("held", 0) for item in ordered),
        },
        "updated_at": int(now),
    }


def _queue_history_summary(
    key: tuple[str, str], queue: dict[str, Any], roadmap: dict[tuple[str, str], str]
) -> dict[str, Any]:
    """Keep full backlog counts/classification without expanding invisible stages."""

    active = sum(int(queue.get(state, 0)) for state in ACTIVE_QUEUE_STATES)
    counts = {state: int(queue.get(state, 0)) for state in ("completed", "dead", "failed", "held")}
    title = queue.get("title", "")
    keyword = title or key[1].replace("-", " ").title()
    roadmap_status = roadmap.get((key[0], _slugify(keyword))) or roadmap.get(key, "")
    if counts["held"] or roadmap_status == "Failed" or (not active and (counts["dead"] or counts["failed"])):
        state = "attention"
    elif active or roadmap_status == "Needs Verification":
        state = "waiting"
    else:
        state = "recent"
    return {
        "id": queue.get("pipeline_run_id") or f"queue:{key[0]}:{key[1]}",
        "domain_handle": key[0],
        "slug": key[1],
        "keyword": keyword,
        "title": title,
        "updated_at": float(queue.get("updated_at") or 0),
        "roadmap_status": roadmap_status,
        "queue": {"active": active, **counts},
        "overall_state": state,
        "is_ongoing": False,
        "in_current_batch": False,
    }


def _new_campaign(
    *,
    domain: str,
    keyword: str,
    title: str,
    slug: str,
    updated_at: float,
    run_id: str,
) -> dict[str, Any]:
    stages = []
    for key, label, phase, service in STAGE_DEFINITIONS:
        stages.append(
            {
                "key": key,
                "label": label,
                "phase": phase,
                "service": service,
                "state": "pending",
                "detail": "Waiting",
                "updated_at": None,
                "metrics": {},
            }
        )
    return {
        "id": run_id,
        "domain_handle": domain,
        "keyword": keyword or title or slug.replace("-", " ").title(),
        "title": title or keyword,
        "slug": slug,
        "article_url": "",
        "pin_url": "",
        "latest_campaign_pin_url": "",
        "campaign_pins": [],
        "campaign_job_ids": [],
        "historical_queue": {},
        "other_jobs": {},
        "roadmap_status": "",
        "run_status": "",
        "updated_at": updated_at,
        "stages": stages,
        "queue": {
            "total": 0,
            "active": 0,
            "completed": 0,
            "dead": 0,
            "failed": 0,
            "held": 0,
        },
        "remaster": {},
        "verification_contract": {
            "primary_pin_proven": False,
            "campaign_report_seen": False,
            "campaign_report_complete": False,
            "required_source_pairs": REQUIRED_SOURCE_PAIRS,
            "required_pin_assets": REQUIRED_PIN_ASSETS,
            "required_queue_jobs": REQUIRED_QUEUE_JOBS,
            "detail": "Waiting for primary pin and exact paired campaign proof",
        },
        "previews": {},
        "in_current_batch": False,
        "batch_id": "",
        "batch_state": "",
    }


def _apply_event(
    campaign: dict[str, Any],
    event: dict[str, Any],
    *,
    root: Path | None = None,
) -> None:
    stage = _stage(campaign, event.get("stage", ""))
    if stage is None:
        return
    details = _json_object(event.get("details_json"))
    stage.update(
        {
            "state": event.get("state", "pending"),
            "detail": event.get("message") or stage["detail"],
            "updated_at": event.get("created_at"),
            "metrics": details,
        }
    )
    campaign["updated_at"] = max(
        float(campaign.get("updated_at") or 0),
        float(event.get("created_at") or 0),
    )
    if details.get("slug"):
        campaign["slug"] = _slugify(details["slug"])
    if details.get("article_url"):
        campaign["article_url"] = str(details["article_url"])
    if stage["key"] in {"primary_pin_publish", "verification"} and (
        details.get("pin_id") or details.get("pin_url")
    ):
        campaign["verification_contract"]["primary_pin_proven"] = True
        if details.get("pin_id"):
            campaign["pin_url"] = f"https://www.pinterest.com/pin/{details['pin_id']}/"
        elif details.get("pin_url"):
            campaign["pin_url"] = str(details["pin_url"])
    if root is not None and details.get("output_path"):
        preview_path = _relative_asset_path(root, details["output_path"])
        if preview_path:
            campaign["previews"][stage["key"]] = {
                "stage": stage["key"],
                "label": stage["label"],
                "preview_path": preview_path,
            }


def _apply_remaster_report(campaign: dict[str, Any], report: dict[str, Any]) -> None:
    campaign["keyword"] = report.get("keyword") or campaign["keyword"]
    campaign["title"] = report.get("title") or campaign["title"]
    campaign["slug"] = _slugify(report.get("slug") or campaign["slug"])
    campaign["article_url"] = campaign["article_url"] or (
        f"https://{report.get('domain_url')}/{campaign['slug']}" if report.get("domain_url") else ""
    )
    campaign["updated_at"] = max(campaign["updated_at"], report["_updated_at"])

    _complete_through(
        campaign,
        "article_publish",
        detail="Proven by article remaster campaign report",
        updated_at=report["_updated_at"],
    )
    generated = int(report.get("generated_count") or 0)
    target = int(report.get("target_count") or 30)
    variants_per_source = int(report.get("variant_contract", {}).get("variants_per_source") or 1)
    pair_count = int(
        report.get("pair_count") or report.get("accepted_source_count") or (generated // variants_per_source)
    )
    if 2 <= generated and generated % 2 == 0 and pair_count == (generated // variants_per_source):
        target = generated
        source_target = pair_count
    else:
        source_target = int(report.get("source_target") or max(1, target // variants_per_source))
    report_complete, contract_detail = _remaster_contract_status(
        report,
        pair_count=pair_count,
        generated=generated,
        jobs=int((report.get("enqueue") or {}).get("jobs_enqueued") or 0),
    )
    contract = campaign["verification_contract"]
    contract.update(
        {
            "campaign_report_seen": True,
            "campaign_report_complete": report_complete,
            "detail": contract_detail,
        }
    )
    source_counts = report.get("source_counts") or {}
    pinterest_sources = int(source_counts.get("pinterest") or 0)
    native_sources = int(source_counts.get("native") or 0)
    collection = _source_collection_presentation(report, source_target=source_target)
    source_detail = (
        f"{pinterest_sources} of {source_target} unique scraped Pinterest sources · "
        f"{native_sources} generated fills"
    )
    if collection:
        source_detail = (
            f"{collection['accepted']} of {source_target} clean photos accepted · {collection['examined']} examined · "
            f"{collection['text_rejected']} text-rejected · {collection['text_unavailable']} OCR-unavailable"
        )
        if collection.get("phase"):
            source_detail += f" · phase: {collection['phase']}"
        if collection.get("blocked_reason") and not report_complete:
            source_detail += f" · blocked: {collection['blocked_reason']}"
    campaign["campaign_job_ids"] = list(
        dict.fromkeys(
            str(item.get("job_id") or "").strip()
            for item in (report.get("enqueue") or {}).get("details", [])
            if isinstance(item, dict) and str(item.get("job_id") or "").strip()
        )
    )
    _set_stage(
        campaign,
        "pinterest_siphon",
        "complete" if report_complete else "warning",
        source_detail,
        report["_updated_at"],
        {**source_counts, "source_collection": collection} if collection else source_counts,
    )
    remaster_state = "complete" if report_complete else "warning"
    _set_stage(
        campaign,
        "remaster",
        remaster_state,
        f"{pair_count} of {source_target} source pairs · {generated} of {target} pin assets",
        report["_updated_at"],
        {
            "generated": generated,
            "target": target,
            "pair_count": pair_count,
            "source_target": source_target,
            "variants_per_source": 2,
        },
    )
    enqueue = report.get("enqueue") or {}
    jobs = int(enqueue.get("jobs_enqueued") or 0)
    expected_jobs = target
    if enqueue:
        queue_complete = enqueue.get("success") is True and jobs >= expected_jobs
        queue_state = "complete" if queue_complete else "warning"
        queue_detail = (
            f"{jobs} upload jobs queued"
            if queue_complete
            else str(enqueue.get("error") or "Queue creation failed")
        )
        if enqueue.get("success") and not queue_complete:
            queue_detail = f"Only {jobs} of {expected_jobs} required upload jobs queued"
        _set_stage(
            campaign,
            "queue",
            queue_state,
            queue_detail,
            report["_updated_at"],
            {"jobs_enqueued": jobs, "accounts": enqueue.get("accounts", [])},
        )
    campaign["remaster"] = {
        "generated": generated,
        "target": target,
        "pair_count": pair_count,
        "source_target": source_target,
        "variants_per_source": variants_per_source,
        "pinterest_sources": pinterest_sources,
        "native_sources": native_sources,
        "report_path": report.get("_path", ""),
        "pairs": _remaster_pair_previews(report),
        "source_collection": collection,
    }
    _sync_contract_verification(campaign, report["_updated_at"])


def _source_collection_presentation(report: dict[str, Any], *, source_target: int) -> dict[str, Any]:
    """Expose bounded counters and code-like reasons, never OCR/source text or paths."""

    raw = report.get("source_collection_diagnostics")
    if not isinstance(raw, dict):
        return {}
    result: dict[str, Any] = {"target": source_target}
    for field in (
        "accepted",
        "examined",
        "text_rejected",
        "text_unavailable",
        "held_sources_skipped",
        "download_failed",
        "irrelevant",
        "undersized",
        "ocr_in_progress",
        "attempt_examined",
        "checkpoint_sources_loaded",
        "checkpoint_invalidated",
        "checkpoint_processed_count",
        "checkpoint_skipped",
        "queries_planned",
        "query_attempts",
        "queries_succeeded",
        "query_failures",
        "login_wall_detected",
        "relevance_rejected",
        "undersized_rejected",
        "invalid_image_rejected",
        "ocr_checks_started",
        "ocr_checks_completed",
        "candidate_limit",
        "deadline_exceeded",
    ):
        value = raw.get(field, raw.get("pins_examined", 0) if field == "examined" else 0)
        try:
            result[field] = max(0, int(value))
        except (TypeError, ValueError, OverflowError):
            result[field] = 0
    result["remaining_sources"] = max(0, source_target - result["accepted"])
    for field in ("phase", "failure_phase", "blocked_reason", "error_type", "cleanup_error_type"):
        value = str(report.get(field) or raw.get(field) or "")
        result[field] = value if re.fullmatch(r"[a-zA-Z0-9_-]{1,80}", value) else ""
    allowed_steps = {stage[0] for stage in STAGE_DEFINITIONS}
    result["remaining_workflow_steps"] = list(
        dict.fromkeys(
            step
            for step in report.get("remaining_workflow_steps") or []
            if isinstance(step, str) and step in allowed_steps
        )
    )
    return result


def _remaster_contract_status(
    report: dict[str, Any],
    *,
    pair_count: int,
    generated: int,
    jobs: int,
) -> tuple[bool, str]:
    """Validate the final scraped-source, paired-asset, and queue proof."""

    target_count = int(report.get("target_count") or generated or REQUIRED_PIN_ASSETS)
    source_target = int(report.get("source_target") or pair_count or (target_count // 2))
    if report.get("success") is True and 2 <= generated and generated % 2 == 0 and pair_count == (generated // 2):
        target_count = generated
        source_target = pair_count
    expected_jobs = target_count

    issues = []
    if report.get("success") is not True:
        issues.append("report marked incomplete")
    if pair_count != source_target:
        issues.append(f"{pair_count}/{source_target} source pairs")
    if generated != target_count:
        issues.append(f"{generated}/{target_count} pin assets")

    accepted_source_count = int(report.get("accepted_source_count") or -1)
    if accepted_source_count != -1 and accepted_source_count != source_target:
        issues.append(f"accepted source count is {accepted_source_count}/{source_target}")
    missing_count = report.get("missing_count")
    if int(missing_count if missing_count is not None else 0) != 0 and (generated < 2 or generated % 2 != 0):
        issues.append("campaign still has missing source slots")

    source_counts = report.get("source_counts") or {}
    pinterest_sources = int(source_counts.get("pinterest") or -1)
    native_sources = int(source_counts.get("native") or 0)
    if pinterest_sources != source_target or native_sources != 0:
        issues.append(
            f"scraped source mix is Pinterest {pinterest_sources}/{source_target}, "
            f"generated {native_sources}/0"
        )

    variants_per_source = int((report.get("variant_contract") or {}).get("variants_per_source") or 0)
    if variants_per_source != 2:
        issues.append(f"{variants_per_source}/2 variants per source")
    variants = set((report.get("variant_contract") or {}).get("variants") or [])
    if variants != {"viral_visual", "recipe_card"}:
        issues.append("variant names do not prove viral_visual + recipe_card")

    assets = report.get("assets") or []
    pair_variants: dict[str, set[str]] = {}
    pair_sources: dict[str, str] = {}
    asset_proof_valid = len(assets) == target_count
    for asset in assets:
        if not isinstance(asset, dict):
            asset_proof_valid = False
            continue
        pair_id = str(asset.get("pair_id") or "").strip()
        variant = str(asset.get("variant") or "").strip()
        source = str(asset.get("source") or "").strip().casefold()
        source_identity = str(asset.get("original_pin_id") or asset.get("original_url") or "").strip()
        if (
            not pair_id
            or variant not in {"viral_visual", "recipe_card"}
            or source != "pinterest"
            or not source_identity
        ):
            asset_proof_valid = False
            continue
        pair_variants.setdefault(pair_id, set()).add(variant)
        previous = pair_sources.setdefault(pair_id, source_identity)
        if previous != source_identity:
            asset_proof_valid = False

    if (
        not asset_proof_valid
        or len(pair_variants) != source_target
        or any(pair != {"viral_visual", "recipe_card"} for pair in pair_variants.values())
        or len(set(pair_sources.values())) != source_target
    ):
        issues.append(f"asset proof is not {source_target} unique Pinterest pairs with both variants")

    enqueue = report.get("enqueue") or {}
    if enqueue.get("success") is not True:
        issues.append("queue enqueue not successful")
    if int(enqueue.get("images_enqueued") or -1) < expected_jobs:
        issues.append(f"{expected_jobs} enqueued images are not proven")
    if jobs < expected_jobs:
        issues.append(f"{jobs}/{expected_jobs} queued jobs")
    details = enqueue.get("details") or []
    job_ids = [str(item.get("job_id") or "") for item in details if isinstance(item, dict)]
    if (
        len(job_ids) < expected_jobs
        or any(not job_id for job_id in job_ids[:expected_jobs])
        or len(set(job_ids[:expected_jobs])) < expected_jobs
    ):
        issues.append(f"{expected_jobs} unique queue job IDs are not proven")

    if issues:
        return False, "Campaign incomplete: " + " · ".join(issues)
    return (
        True,
        f"Exact campaign proven: {source_target} unique scraped Pinterest sources, {target_count} pin assets, and {expected_jobs} unique queued jobs",
    )


def _sync_contract_verification(campaign: dict[str, Any], updated_at: float | None) -> None:
    contract = campaign["verification_contract"]
    primary = bool(contract.get("primary_pin_proven"))
    report_seen = bool(contract.get("campaign_report_seen"))
    campaign_complete = bool(contract.get("campaign_report_complete"))
    verification = _stage(campaign, "verification")
    if verification is None:
        return
    held = int((campaign.get("queue") or {}).get("held") or 0)
    if held:
        detail = (
            f"Quality hold: {held} quarantined campaign jobs; replacement source/creative proof is required"
        )
        contract.update(
            {"quality_hold": True, "held_jobs": held, "campaign_report_complete": False, "detail": detail}
        )
        _set_stage(
            campaign, "verification", "warning", detail, updated_at, {"held_jobs": held, "quality_hold": True}
        )
        return

    remaster_data = campaign.get("remaster") or {}
    source_pairs = int(remaster_data.get("pair_count") or REQUIRED_SOURCE_PAIRS)
    pin_assets = int(remaster_data.get("generated") or (source_pairs * 2))
    jobs_enqueued = pin_assets

    if primary and campaign_complete:
        _set_stage(
            campaign,
            "verification",
            "complete",
            f"Primary pin plus {source_pairs} unique scraped sources and {pin_assets} queued pins verified",
            updated_at,
            {
                "primary_pin_proven": True,
                "source_pairs": source_pairs,
                "pin_assets": pin_assets,
                "jobs_enqueued": jobs_enqueued,
            },
        )
        return

    if report_seen and not campaign_complete:
        _set_stage(
            campaign,
            "verification",
            "waiting",
            str(contract.get("detail") or "Paired campaign report is incomplete"),
            updated_at,
        )
        return

    if campaign_complete:
        _set_stage(
            campaign,
            "verification",
            "waiting",
            f"Campaign of {source_pairs} pairs / {pin_assets} pins is queued; primary pin proof is pending",
            updated_at,
        )
        return

    if primary:
        state = "running" if verification["state"] == "running" else "waiting"
        _set_stage(
            campaign,
            "verification",
            "waiting",
            f"Primary pin is proven; waiting for campaign proof ({source_pairs} pairs / {pin_assets} pins)",
            updated_at,
        )
        return

    if verification["state"] == "complete":
        _set_stage(
            campaign,
            "verification",
            "waiting",
            "Final verification requires primary pin plus exact 15-pair / 30-pin campaign proof",
            updated_at,
        )


def _apply_primary_proof(campaign: dict[str, Any], proof: dict[str, Any]) -> None:
    timestamp = float(proof.get("updated_at") or campaign["updated_at"])
    _complete_through(
        campaign,
        "primary_pin_publish",
        detail="Verified article and primary pin proof",
        updated_at=timestamp,
    )
    campaign["verification_contract"]["primary_pin_proven"] = bool(
        proof.get("pin_id") or proof.get("pin_url")
    )
    campaign["article_url"] = proof.get("url") or campaign["article_url"]
    if proof.get("pin_id"):
        campaign["pin_url"] = f"https://www.pinterest.com/pin/{proof['pin_id']}/"
    elif proof.get("pin_url"):
        campaign["pin_url"] = str(proof["pin_url"])
    _sync_contract_verification(campaign, timestamp)


def _apply_queue_evidence(campaign: dict[str, Any], queue: dict[str, Any]) -> None:
    tracked_ids = list(dict.fromkeys(campaign.get("campaign_job_ids") or []))
    job_evidence = queue.get("jobs") if isinstance(queue.get("jobs"), dict) else {}
    if tracked_ids:
        tracked_jobs = [
            {"job_id": job_id, **job_evidence[job_id]} for job_id in tracked_ids if job_id in job_evidence
        ]
        active = sum(item.get("status") in ACTIVE_QUEUE_STATES for item in tracked_jobs)
        completed = sum(item.get("status") == "completed" for item in tracked_jobs)
        dead = sum(item.get("status") == "dead" for item in tracked_jobs)
        failed = sum(item.get("status") == "failed" for item in tracked_jobs)
        held = sum(item.get("status") == "held" for item in tracked_jobs)
        total = len(tracked_ids)
        unknown = total - len(tracked_jobs)
        latest_job = max(
            (item for item in tracked_jobs if item.get("pin_url")),
            key=lambda item: float(item.get("updated_at") or 0),
            default={},
        )
        campaign["campaign_pins"] = [
            {
                "job_id": item["job_id"],
                "pin_url": item["pin_url"],
                "status": item["status"],
            }
            for item in tracked_jobs
            if item.get("pin_url")
        ]
        campaign["latest_campaign_pin_url"] = str(latest_job.get("pin_url") or "")
        tracked_set = set(tracked_ids)
        historical_jobs = [
            {"job_id": job_id, **item}
            for job_id, item in job_evidence.items()
            if job_id not in tracked_set
            and str(item.get("campaign_type") or "").startswith("article_remaster")
        ]
        other_jobs = [
            {"job_id": job_id, **item}
            for job_id, item in job_evidence.items()
            if job_id not in tracked_set
            and not str(item.get("campaign_type") or "").startswith("article_remaster")
        ]
        campaign["historical_queue"] = _queue_state_counts(historical_jobs)
        campaign["other_jobs"] = _queue_state_counts(other_jobs)
    else:
        active = sum(int(queue.get(state, 0)) for state in ACTIVE_QUEUE_STATES)
        completed = int(queue.get("completed", 0))
        dead = int(queue.get("dead", 0))
        failed = int(queue.get("failed", 0))
        held = int(queue.get("held", 0))
        total = active + completed + dead + failed + held
        unknown = 0
        campaign["latest_campaign_pin_url"] = str(queue.get("latest_campaign_pin_url") or "")
    metric_jobs = tracked_jobs if tracked_ids else list(job_evidence.values())
    pending, processing, retry = (
        sum(item.get("status") == status for item in metric_jobs)
        if job_evidence
        else int(queue.get(status, 0))
        for status in ("pending", "processing", "retry")
    )
    waiting_jobs = [item for item in metric_jobs if item.get("status") in {"pending", "retry"}]
    now = time.time()
    scheduled = sum(float(item.get("next_retry_at") or 0) > now for item in waiting_jobs)
    due_times = [float(item["next_retry_at"]) for item in waiting_jobs if item.get("next_retry_at")]
    campaign["updated_at"] = max(campaign["updated_at"], float(queue.get("updated_at") or 0))
    campaign["queue"] = {
        "total": total,
        "active": active,
        "completed": completed,
        "dead": dead,
        "failed": failed,
        "unknown": unknown,
        "held": held,
        # Legacy ``active`` means unfinished; only ``processing`` means executing.
        "pending": pending,
        "processing": processing,
        "retry": retry,
        "waiting": pending + retry,
        "scheduled": scheduled,
        "next_due_at": min(due_times) if due_times else None,
    }
    campaign["article_url"] = queue.get("link") or campaign["article_url"]
    campaign["quality_hold"] = held > 0

    if total:
        queue_label = "current campaign jobs" if tracked_ids else "Pinterest jobs"
        _set_stage(
            campaign,
            "queue",
            "complete",
            f"{total} {queue_label} recorded",
            queue.get("updated_at"),
            {"total": total, "unknown": unknown},
        )
    primary = _stage(campaign, "primary_pin_publish")
    primary_metrics = primary.get("metrics") or {}
    primary_job_id = str(primary_metrics.get("job_id") or primary_metrics.get("primary_job_id") or "")
    primary_job = job_evidence.get(primary_job_id) or {}
    if primary_job.get("status") in ACTIVE_QUEUE_STATES:
        _set_stage(
            campaign,
            "primary_pin_publish",
            "running" if primary_job["status"] == "processing" else "waiting",
            "Primary pin upload processing"
            if primary_job["status"] == "processing"
            else "Primary pin queued; waiting for a worker",
            primary_job.get("updated_at"),
            primary_metrics,
        )
    if held:
        state = "warning"
        detail = f"Quality hold: {held} quarantined · {completed} published · {processing} processing · {pending + retry} waiting"
    elif active:
        state = "running" if processing else "waiting"
        detail = f"{completed} published · {processing} processing · {pending + retry} waiting"
        if scheduled:
            detail += f" · {scheduled} scheduled"
        if dead:
            detail += f" · {dead} in DLQ"
    elif dead or failed or unknown:
        state = "warning" if completed else "failed"
        detail = f"{completed} published · {dead + failed + unknown} need attention"
    elif completed:
        state = "complete"
        detail = f"All {completed} tracked uploads published"
    else:
        return
    _set_stage(
        campaign,
        "distribution",
        state,
        detail,
        queue.get("updated_at"),
        campaign["queue"],
    )


def _queue_state_counts(items: list[dict[str, Any]]) -> dict[str, int]:
    return {
        "total": len(items),
        "active": sum(item.get("status") in ACTIVE_QUEUE_STATES for item in items),
        "completed": sum(item.get("status") == "completed" for item in items),
        "dead": sum(item.get("status") == "dead" for item in items),
        "failed": sum(item.get("status") == "failed" for item in items),
        "held": sum(item.get("status") == "held" for item in items),
    }


def _finalize_campaign(campaign: dict[str, Any], *, now: float) -> None:
    stages = campaign["stages"]
    roadmap_status = campaign.get("roadmap_status", "")
    _sync_contract_verification(campaign, campaign["updated_at"])
    _expire_stale_running_stages(campaign, now=now)
    if roadmap_status == "Needs Verification" and _stage(campaign, "verification")["state"] == "pending":
        _set_stage(
            campaign,
            "verification",
            "waiting",
            "Roadmap is waiting for pin_id or pin_url proof",
            campaign["updated_at"],
        )
    elif roadmap_status == "Failed" and not any(stage["state"] == "failed" for stage in stages):
        first_pending = next((stage for stage in stages if stage["state"] == "pending"), stages[-1])
        first_pending.update({"state": "failed", "detail": "Roadmap marked this keyword Failed"})

    stopped = any(
        _workflow_state(campaign.get(field)) in {"failed", "stopped", "interrupted"}
        for field in ("run_status", "batch_state", "roadmap_status")
    )
    if stopped:
        for stage in stages:
            queue_owns_stage = int((campaign.get("queue") or {}).get("active") or 0) > 0 and stage["key"] in {
                "primary_pin_publish",
                "queue",
                "distribution",
            }
            if stage["state"] == "running" and not queue_owns_stage:
                stage.update(
                    {
                        "state": "warning",
                        "detail": "Worker stopped before this step completed",
                        "metrics": {**stage.get("metrics", {}), "interrupted": True},
                    }
                )
    running = [stage for stage in stages if stage["state"] == "running"]
    attention = [stage for stage in stages if stage["state"] in {"failed", "warning", "waiting"}]
    waiting = [stage for stage in stages if stage["state"] in {"waiting", "queued", "retry", "retrying"}]
    completed = sum(stage["state"] == "complete" for stage in stages)
    if campaign["queue"].get("held"):
        overall_state = "attention"
        current = _stage(campaign, "verification")
    elif running:
        overall_state = "active"
        current = running[-1]
    elif any(stage["state"] in {"failed", "warning"} for stage in attention):
        overall_state = "attention"
        current = attention[-1]
    elif waiting:
        overall_state = "waiting"
        current = _stage(campaign, "distribution") if campaign["queue"].get("waiting") else waiting[-1]
    elif completed == len(stages):
        overall_state = "complete"
        current = stages[-1]
    else:
        overall_state = "recent"
        current = next((stage for stage in stages if stage["state"] == "pending"), stages[-1])

    campaign["overall_state"] = overall_state
    campaign["current_stage"] = current["key"]
    campaign["current_label"] = current["label"]
    campaign["current_detail"] = current["detail"]
    campaign["progress"] = round((completed / len(stages)) * 100)
    campaign["age_seconds"] = max(0, int(now - float(campaign.get("updated_at") or now)))


def _campaign_is_ongoing(campaign: dict[str, Any]) -> bool:
    """Return whether a lane has current work rather than historical evidence.

    Executing queue leases are live regardless of article age. Deferred older
    campaigns belong in history/backlog; current-batch waits remain visible.
    """

    queue = campaign.get("queue") or {}
    if int(queue.get("processing") or 0) > 0:
        return True
    if not campaign.get("in_current_batch"):
        return False
    if str(campaign.get("id") or "").startswith("queue:"):
        return False
    if int(queue.get("held") or 0) > 0:
        return True

    if int(queue.get("active") or 0) > 0:
        return True

    run_state = _workflow_state(campaign.get("run_status"))
    batch_state = _workflow_state(campaign.get("batch_state"))
    roadmap_state = _workflow_state(campaign.get("roadmap_status"))
    stages = campaign.get("stages") or []
    stage_states = {_workflow_state(stage.get("state")) for stage in stages}
    age_seconds = max(0, int(campaign.get("age_seconds") or 0))
    fresh = age_seconds <= STALE_RUNNING_SECONDS
    if run_state == "researching" or batch_state == "researching":
        return fresh
    if (
        _workflow_state(campaign.get("overall_state")) == "complete"
        or "failed" in stage_states
        or run_state in TERMINAL_WORKFLOW_STATES
        or batch_state in TERMINAL_WORKFLOW_STATES
        or roadmap_state in TERMINAL_WORKFLOW_STATES
    ):
        return False

    if fresh and stage_states & ONGOING_STAGE_STATES:
        return True

    warning_with_pending_work = any(
        _workflow_state(stage.get("state")) == "warning"
        and not bool((stage.get("metrics") or {}).get("interrupted"))
        for stage in stages
    ) and any(_workflow_state(stage.get("state")) == "pending" for stage in stages)
    if fresh and warning_with_pending_work:
        return True

    return fresh and (run_state in ONGOING_WORKFLOW_STATES or batch_state in ONGOING_WORKFLOW_STATES)


def _workflow_state(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(value or "").strip().casefold()).strip("_")


def _expire_stale_running_stages(campaign: dict[str, Any], *, now: float) -> None:
    """Turn abandoned running checkpoints into neutral interrupted history."""

    interrupted = False
    for stage in campaign["stages"]:
        if stage["state"] != "running":
            continue
        if stage["key"] in {"distribution", "primary_pin_publish"} and int(
            (campaign.get("queue") or {}).get("processing") or 0
        ):
            continue
        try:
            updated_at = float(stage.get("updated_at") or campaign["updated_at"])
        except (TypeError, ValueError):
            updated_at = float(campaign.get("updated_at") or now)
        age_seconds = max(0, int(now - updated_at))
        if age_seconds <= STALE_RUNNING_SECONDS:
            continue
        age_label = f"{age_seconds // 86400}d" if age_seconds >= 86400 else f"{max(1, age_seconds // 3600)}h"
        stage.update(
            {
                "state": "warning",
                "detail": (f"Interrupted historical checkpoint; no live update for {age_label}"),
                "metrics": {
                    **stage.get("metrics", {}),
                    "interrupted": True,
                    "stale_seconds": age_seconds,
                },
            }
        )
        interrupted = True
    if interrupted and campaign.get("run_status") in {"running", "distributing"}:
        campaign["run_status"] = "interrupted"


def _read_current_production_batch(root: Path) -> dict[str, Any]:
    report_dir = root / "data" / "reports" / "production_batches"
    if not report_dir.exists():
        return {"batch_id": "", "articles": {}}
    paths = sorted(
        [
            *report_dir.glob("production-*.json"),
            *report_dir.glob("production-*.tmp"),
        ],
        key=lambda path: (path.stem, path.suffix == ".tmp"),
        reverse=True,
    )
    if not paths:
        return {"batch_id": "", "articles": {}}
    latest_stem = paths[0].stem
    for path in paths:
        if path.stem != latest_stem:
            continue
        try:
            report = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        articles: dict[str, dict[str, Any]] = {}
        domains = report.get("domains") or {}
        if not isinstance(domains, dict):
            continue
        for domain_handle, domain in domains.items():
            if not isinstance(domain, dict):
                continue
            for article in domain.get("articles") or []:
                if not isinstance(article, dict):
                    continue
                run_id = str(article.get("pipeline_run_id") or "")
                if not run_id:
                    continue
                articles[run_id] = {
                    **article,
                    "domain_handle": _domain_handle(domain_handle),
                }
        return {
            "batch_id": str(report.get("batch_id") or path.stem),
            "state": str(report.get("state") or ""),
            "articles": articles,
        }
    return {"batch_id": "", "articles": {}}


def _read_event_runs(
    root: Path,
    *,
    limit: int = 40,
    include_run_ids: Iterable[str] = (),
) -> list[dict[str, Any]]:
    db_path = root / "data" / "runtime" / "pipeline_events.db"
    if not db_path.exists():
        return []
    connection = _read_connection(db_path)
    if connection is None:
        return []
    try:
        rows = list(
            connection.execute(
                "SELECT * FROM pipeline_runs ORDER BY updated_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        )
        seen = {str(row["id"]) for row in rows}
        wanted = [str(run_id) for run_id in include_run_ids if str(run_id) not in seen]
        if wanted:
            placeholders = ",".join("?" for _ in wanted)
            rows.extend(
                connection.execute(
                    f"SELECT * FROM pipeline_runs WHERE id IN ({placeholders}) ORDER BY updated_at DESC",
                    wanted,
                ).fetchall()
            )
        output = []
        for row in rows:
            run = dict(row)
            run["events"] = [
                dict(event)
                for event in connection.execute(
                    "SELECT * FROM pipeline_events WHERE run_id = ? ORDER BY id",
                    (row["id"],),
                ).fetchall()
            ]
            output.append(run)
        return output
    except sqlite3.Error:
        return []
    finally:
        connection.close()


def _read_remaster_reports(root: Path, *, limit: int = 40) -> list[dict[str, Any]]:
    report_dir = root / "data" / "reports" / "campaigns"
    if not report_dir.exists():
        return []
    output = []
    paths = sorted(
        report_dir.glob("*_remaster_*.json"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    for path in paths[:limit]:
        try:
            report = json.loads(path.read_text(encoding="utf-8"))
            if report.get("campaign_type") not in {
                "article_remaster_30",
                "article_remaster_pairs",
            }:
                continue
            report["_path"] = str(path)
            report["_root"] = str(root)
            report["_updated_at"] = _timestamp(report.get("completed_at"), path.stat().st_mtime)
            output.append(report)
        except (OSError, json.JSONDecodeError):
            continue
    return output


def _read_queue_groups(root: Path) -> dict[tuple[str, str], dict[str, Any]]:
    db_path = root / "data" / "queue" / "jobs.db"
    connection = _read_connection(db_path)
    if connection is None:
        return {}
    groups: dict[tuple[str, str], dict[str, Any]] = defaultdict(
        lambda: {
            "pending": 0,
            "processing": 0,
            "retry": 0,
            "completed": 0,
            "dead": 0,
            "failed": 0,
            "held": 0,
            "updated_at": 0.0,
            "title": "",
            "link": "",
            "pin_url": "",
            "latest_campaign_pin_url": "",
            "latest_pin_updated_at": 0.0,
            "pipeline_run_id": "",
            "jobs": {},
        }
    )
    try:
        columns = {row["name"] for row in connection.execute("PRAGMA table_info(jobs)")}
        retry_column = "next_retry_at" if "next_retry_at" in columns else "NULL AS next_retry_at"
        for row in connection.execute(
            "SELECT id, payload_json, status, created_at, started_at, completed_at, result_json, "
            f"{retry_column} FROM jobs"
        ):
            payload = _json_object(row["payload_json"])
            result = _json_object(row["result_json"])
            _accumulate_queue_row(
                groups,
                payload,
                str(row["status"]),
                result,
                max(
                    float(row["created_at"] or 0),
                    float(row["started_at"] or 0),
                    float(row["completed_at"] or 0),
                ),
                job_id=str(row["id"] or ""),
                next_retry_at=row["next_retry_at"],
            )
        for row in connection.execute("SELECT job_json, completed_at FROM completed_log"):
            job = _json_object(row["job_json"])
            _accumulate_queue_row(
                groups,
                job.get("payload") or {},
                "completed",
                job.get("result") or {},
                float(row["completed_at"] or job.get("completed_at") or 0),
                job_id=str(job.get("id") or ""),
            )
        for row in connection.execute("SELECT job_json, moved_at FROM dlq"):
            job = _json_object(row["job_json"])
            _accumulate_queue_row(
                groups,
                job.get("payload") or {},
                "dead",
                job.get("result") or {},
                float(row["moved_at"] or 0),
                job_id=str(job.get("id") or ""),
            )
    except sqlite3.Error:
        return {}
    finally:
        connection.close()
    return dict(groups)


def _accumulate_queue_row(
    groups: dict[tuple[str, str], dict[str, Any]],
    payload: dict[str, Any],
    status: str,
    result: dict[str, Any],
    updated_at: float,
    *,
    job_id: str = "",
    next_retry_at: float | None = None,
) -> None:
    extra = payload.get("extra") if isinstance(payload.get("extra"), dict) else {}
    domain = _domain_handle(payload.get("domain_handle") or extra.get("domain_handle") or "")
    slug = _slugify(extra.get("slug") or _slug_from_link(payload.get("link")) or payload.get("title"))
    if not domain or not slug:
        return
    group = groups[(domain, slug)]
    normalized_status = status if status in group else "failed"
    group[normalized_status] += 1
    group["updated_at"] = max(group["updated_at"], updated_at)
    group["title"] = payload.get("title") or group["title"]
    group["link"] = payload.get("link") or group["link"]
    pin_url = str(result.get("pin_url") or "")
    if pin_url and updated_at >= float(group["latest_pin_updated_at"] or 0):
        group["latest_campaign_pin_url"] = pin_url
        group["latest_pin_updated_at"] = updated_at
    normalized_job_id = str(job_id or "").strip()
    existing_job = group["jobs"].get(normalized_job_id) if normalized_job_id else None
    if normalized_job_id and (
        existing_job is None or updated_at >= float(existing_job.get("updated_at") or 0)
    ):
        group["jobs"][normalized_job_id] = {
            "status": normalized_status,
            "pin_url": pin_url,
            "updated_at": updated_at,
            "campaign_type": str(extra.get("campaign_type") or ""),
            "next_retry_at": next_retry_at,
        }
    group["pipeline_run_id"] = extra.get("pipeline_run_id") or group["pipeline_run_id"]


def _read_roadmap_statuses(root: Path) -> dict[tuple[str, str], str]:
    output = {}
    for path in (root / "data" / "domains").glob("*/keywords.md"):
        domain = path.parent.name
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for line in lines:
            if not line.startswith("|") or line.startswith("|---") or "Keyword" in line:
                continue
            cells = [cell.strip() for cell in line.strip("|").split("|")]
            if len(cells) >= 6:
                output[(domain, _slugify(cells[0]))] = cells[5]
    return output


def _read_recovery_proof(root: Path) -> dict[tuple[str, str], dict[str, Any]]:
    path = root / "data" / "reports" / "campaigns" / "production_recovery_20260728.json"
    if not path.exists():
        return {}
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
        updated_at = _timestamp(report.get("generated_at"), path.stat().st_mtime)
    except (OSError, json.JSONDecodeError):
        return {}
    output = {}
    for article in report.get("articles", []):
        domain = _domain_handle(article.get("domain_handle", ""))
        slug = _slug_from_link(article.get("url", ""))
        if domain and slug and article.get("primary_pin_id"):
            output[(domain, slug)] = {
                "url": article.get("url", ""),
                "pin_id": str(article["primary_pin_id"]),
                "updated_at": updated_at,
            }
    return output


def _read_connection(path: Path) -> sqlite3.Connection | None:
    if not path.exists():
        return None
    try:
        connection = sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True, timeout=5)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout=5000")
        return connection
    except sqlite3.Error:
        return None


def _relative_asset_path(root: Path, value: Any) -> str:
    """Return a browser-safe RankStein-relative path for an existing asset."""

    root = Path(root).resolve()
    raw = Path(str(value or ""))
    candidate = raw if raw.is_absolute() else root / raw
    try:
        resolved = candidate.resolve(strict=True)
        relative = resolved.relative_to(root)
    except (OSError, ValueError):
        return ""
    if resolved.suffix.lower() not in {".jpg", ".jpeg", ".png", ".webp"}:
        return ""
    return relative.as_posix()


def _remaster_pair_previews(report: dict[str, Any]) -> list[dict[str, Any]]:
    root = Path(str(report.get("_root") or "."))
    pairs: dict[str, dict[str, Any]] = {}
    for index, asset in enumerate(report.get("assets") or [], 1):
        if not isinstance(asset, dict):
            continue
        preview_path = _relative_asset_path(root, asset.get("remastered_path"))
        if not preview_path:
            continue
        pair_id = str(asset.get("pair_id") or f"legacy-{index:02d}")
        pair = pairs.setdefault(
            pair_id,
            {
                "pair_id": pair_id,
                "source_index": int(asset.get("source_index") or len(pairs) + 1),
                "source": asset.get("source") or "pinterest",
                "source_url": asset.get("original_url") or "",
                "variants": [],
            },
        )
        pair["variants"].append(
            {
                "variant": asset.get("variant") or "legacy_remaster",
                "label": asset.get("variant_label") or "Remastered pin",
                "preview_path": preview_path,
                "width": int(asset.get("width") or 1000),
                "height": int(asset.get("height") or 1500),
                "status": asset.get("status") or "complete",
            }
        )
    return sorted(pairs.values(), key=lambda item: item["source_index"])


def _complete_through(
    campaign: dict[str, Any],
    stage_key: str,
    *,
    detail: str,
    updated_at: float,
) -> None:
    last_index = STAGE_INDEX[stage_key]
    for stage in campaign["stages"][: last_index + 1]:
        if stage["state"] not in TERMINAL_STATES:
            stage.update(
                {
                    "state": "complete",
                    "detail": detail,
                    "updated_at": updated_at,
                }
            )


def _set_stage(
    campaign: dict[str, Any],
    stage_key: str,
    state: str,
    detail: str,
    updated_at: float | None,
    metrics: dict[str, Any] | None = None,
) -> None:
    stage = _stage(campaign, stage_key)
    if stage is None:
        return
    stage.update(
        {
            "state": state,
            "detail": detail,
            "updated_at": updated_at,
            "metrics": metrics or {},
        }
    )


def _stage(campaign: dict[str, Any], key: str) -> dict[str, Any] | None:
    index = STAGE_INDEX.get(key)
    return campaign["stages"][index] if index is not None else None


def _json_object(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if not raw:
        return {}
    try:
        value = json.loads(raw)
        return value if isinstance(value, dict) else {}
    except (TypeError, json.JSONDecodeError):
        return {}


def _timestamp(raw: Any, fallback: float) -> float:
    if not raw:
        return fallback
    try:
        return datetime.fromisoformat(str(raw).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return fallback


def _domain_handle(value: Any) -> str:
    text = str(value or "").strip().lower()
    if text.startswith("http"):
        text = urlparse(text).netloc
    return text.split(".")[0].replace("www", "").strip("-")


def _slug_from_link(value: Any) -> str:
    try:
        return _slugify(urlparse(str(value or "")).path.strip("/").split("/")[-1])
    except ValueError:
        return ""


def _slugify(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(char for char in text if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
