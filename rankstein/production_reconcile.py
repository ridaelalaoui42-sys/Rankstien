"""Proof-backed recovery for primary Pinterest jobs that finish after the article worker."""

from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from rankstein.domain import Domain, get_registry
from rankstein.keyword_roadmap import mark_keyword_status
from rankstein.pipeline_events import (
    PIPELINE_DB,
    record_pipeline_stage,
    set_pipeline_run_status,
)
from rankstein.production_batch import ProductionBatchTracker

PROJECT_ROOT = Path(__file__).resolve().parents[1]
_PIN_ID_PATTERN = re.compile(r"^\d{15,20}$")


class ReconciliationError(RuntimeError):
    """Raised when durable state does not prove one exact production article."""


@dataclass(frozen=True)
class BatchArticle:
    keyword: str
    cluster: str
    source: str
    state: str
    article: dict[str, Any]
    batch: dict[str, Any]


@dataclass(frozen=True)
class PipelineRun:
    keyword: str
    slug: str
    status: str


@dataclass(frozen=True)
class PrimaryPinProof:
    pin_id: str
    pin_url: str
    account_handle: str
    article_url: str


def _normalized_state(value: Any) -> str:
    return str(value or "").strip().replace("_", " ").casefold()


def _load_batch_article(
    *,
    project_root: Path,
    batch_id: str,
    domain_handle: str,
    pipeline_run_id: str,
) -> BatchArticle:
    report_path = project_root / "data" / "reports" / "production_batches" / f"{batch_id}.json"
    try:
        batch = json.loads(report_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ReconciliationError(f"Production batch report not found: {report_path}") from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise ReconciliationError(f"Production batch report is unreadable: {exc}") from exc
    if batch.get("batch_id") != batch_id:
        raise ReconciliationError("Production batch identity does not match --batch-id")
    domain = (batch.get("domains") or {}).get(domain_handle)
    if not isinstance(domain, dict):
        raise ReconciliationError(f"Domain {domain_handle!r} is not part of batch {batch_id!r}")

    matches = [
        item
        for item in domain.get("articles", [])
        if isinstance(item, dict) and item.get("pipeline_run_id") == pipeline_run_id
    ]
    if len(matches) != 1:
        raise ReconciliationError(
            f"Expected one batch article for pipeline run {pipeline_run_id!r}; found {len(matches)}"
        )
    article = matches[0]
    keyword = str(article.get("keyword") or "").strip()
    if not keyword:
        raise ReconciliationError("Batch article has no keyword")
    return BatchArticle(
        keyword=keyword,
        cluster=str(article.get("cluster") or "").strip(),
        source=str(article.get("source") or "").strip(),
        state=_normalized_state(article.get("state")),
        article=article,
        batch=batch,
    )


def _slug_from_details(details: dict[str, Any]) -> str:
    slug = str(details.get("slug") or "").strip().strip("/")
    if slug:
        return slug
    article_url = str(details.get("article_url") or "").strip()
    if not article_url:
        return ""
    return unquote(urlparse(article_url).path.rstrip("/").rsplit("/", 1)[-1]).strip()


def _load_pipeline_run(
    *,
    db_path: Path,
    pipeline_run_id: str,
    domain_handle: str,
    keyword: str,
) -> PipelineRun:
    if not db_path.is_file():
        raise ReconciliationError(f"Pipeline event database not found: {db_path}")
    try:
        with sqlite3.connect(db_path) as connection:
            connection.row_factory = sqlite3.Row
            row = connection.execute(
                """
                SELECT domain_handle, keyword, slug, status
                FROM pipeline_runs
                WHERE id = ?
                """,
                (pipeline_run_id,),
            ).fetchone()
            if row is None:
                raise ReconciliationError(f"Pipeline run not found: {pipeline_run_id}")
            if str(row["domain_handle"]) != domain_handle:
                raise ReconciliationError("Pipeline run belongs to a different domain")
            if str(row["keyword"]).strip().casefold() != keyword.casefold():
                raise ReconciliationError("Pipeline run keyword does not match the batch article")
            status = _normalized_state(row["status"])
            if status in {"failed", "cancelled", "canceled"}:
                raise ReconciliationError(f"Pipeline run is terminally {status}")

            slug = str(row["slug"] or "").strip().strip("/")
            if not slug:
                event_rows = connection.execute(
                    """
                    SELECT details_json
                    FROM pipeline_events
                    WHERE run_id = ? AND stage = 'article_publish' AND state = 'complete'
                    ORDER BY id DESC
                    """,
                    (pipeline_run_id,),
                ).fetchall()
                for event in event_rows:
                    try:
                        details = json.loads(event["details_json"] or "{}")
                    except json.JSONDecodeError:
                        continue
                    if isinstance(details, dict):
                        slug = _slug_from_details(details)
                    if slug:
                        break
    except sqlite3.Error as exc:
        raise ReconciliationError(f"Could not read pipeline run proof: {exc}") from exc
    if not slug or "/" in slug or "\\" in slug:
        raise ReconciliationError("Pipeline run has no safe published article slug")
    return PipelineRun(keyword=keyword, slug=slug, status=status)


def _get_primary_job_outcome(job_id: str) -> dict:
    from pinterest_automation.job_queue import get_job_queue

    return get_job_queue().get_job_outcome(job_id)


def _expected_upload_account(domain_handle: str, article_url: str) -> str:
    from pinterest_automation.config import get_config
    from pinterest_automation.routing import select_upload_account

    return str(select_upload_account(domain_handle, article_url, config=get_config()) or "").strip()


def _payload_identity(payload: dict[str, Any], key: str) -> str:
    values = {
        str(value).strip()
        for value in (
            payload.get(key),
            (payload.get("extra") or {}).get(key) if isinstance(payload.get("extra"), dict) else None,
        )
        if value is not None and str(value).strip()
    }
    if len(values) > 1:
        raise ReconciliationError(f"Primary job contains conflicting {key} values")
    return next(iter(values), "")


def _validate_primary_job(
    outcome: dict,
    *,
    domain: Domain,
    slug: str,
) -> PrimaryPinProof:
    if not outcome.get("found") or outcome.get("state") != "completed":
        raise ReconciliationError("Primary Pinterest job is not completed")
    if outcome.get("type") != "pin_upload" or outcome.get("priority") != 1:
        raise ReconciliationError("Primary proof must be a priority-1 pin_upload job")
    payload = outcome.get("payload")
    if not isinstance(payload, dict):
        raise ReconciliationError("Primary job payload is missing")
    if _payload_identity(payload, "source") != "direct_upload_via_supervisor":
        raise ReconciliationError("Primary job source is not direct_upload_via_supervisor")
    if _payload_identity(payload, "domain_handle") != domain.handle:
        raise ReconciliationError("Primary job domain does not match the batch article")

    article_url = str(payload.get("link") or "").strip()
    parsed_article = urlparse(article_url)
    actual_host = (parsed_article.hostname or "").casefold().removeprefix("www.")
    expected_host = domain.domain.casefold().removeprefix("www.")
    if parsed_article.scheme not in {"http", "https"} or actual_host != expected_host:
        raise ReconciliationError("Primary job article host does not match the configured domain")
    actual_slug = unquote(parsed_article.path.rstrip("/").rsplit("/", 1)[-1]).strip()
    if actual_slug.casefold() != slug.casefold():
        raise ReconciliationError("Primary job article slug does not match the pipeline run")

    account_handle = _payload_identity(payload, "account_handle")
    expected_account = _expected_upload_account(domain.handle, article_url)
    if not expected_account or account_handle != expected_account:
        raise ReconciliationError("Primary job account does not match deterministic domain routing")

    result = outcome.get("result")
    if not isinstance(result, dict) or result.get("success") is not True:
        raise ReconciliationError("Primary job result does not prove success")
    pin_id = str(result.get("pin_id") or "").strip()
    pin_url = str(result.get("pin_url") or "").strip()
    if not _PIN_ID_PATTERN.fullmatch(pin_id):
        raise ReconciliationError("Primary job pin_id is not a 15-20 digit Pinterest ID")
    parsed_pin = urlparse(pin_url)
    pin_host = (parsed_pin.hostname or "").casefold()
    pin_match = re.fullmatch(r"/pin/(\d{15,20})/?", parsed_pin.path)
    if (
        parsed_pin.scheme != "https"
        or pin_host not in {"pinterest.com", "www.pinterest.com"}
        or pin_match is None
        or pin_match.group(1) != pin_id
    ):
        raise ReconciliationError("Primary job pin_url does not prove the same pin_id")
    return PrimaryPinProof(
        pin_id=pin_id,
        pin_url=pin_url,
        account_handle=account_handle,
        article_url=article_url,
    )


def _get_supabase_article(slug: str, domain_handle: str) -> dict:
    from rankstein_mcp_server import get_article_data_from_supabase_by_slug

    return get_article_data_from_supabase_by_slug(slug, domain_handle)


def _update_supabase_pin(slug: str, pin_id: str, domain_handle: str) -> dict:
    from rankstein_mcp_server import update_pinterest_pin_id

    return update_pinterest_pin_id(slug, pin_id, domain_handle)


def _canonical_recipe_context(article: dict) -> tuple[str, str, list[str], list[str], str]:
    if not article.get("success"):
        raise ReconciliationError(
            f"Published article could not be loaded: {article.get('error', 'unknown error')}"
        )
    title = str(article.get("title") or "").strip()
    recipe_schema = article.get("recipe_schema") or {}
    if not title or not isinstance(recipe_schema, dict):
        raise ReconciliationError("Published article is missing canonical recipe context")
    ingredients = [
        str(item).strip() for item in recipe_schema.get("recipeIngredient", []) if str(item).strip()
    ]
    steps = [
        str(item.get("text", "") if isinstance(item, dict) else item).strip()
        for item in recipe_schema.get("recipeInstructions", [])
        if str(item.get("text", "") if isinstance(item, dict) else item).strip()
    ]
    if not ingredients or not steps:
        raise ReconciliationError("Published article has no real recipe ingredients or steps")
    return (
        title,
        str(article.get("category") or "").strip(),
        ingredients,
        steps,
        str(article.get("chef_tip") or "").strip(),
    )


async def _launch_remaster_campaign(**kwargs) -> dict:
    from backend.scripts.turbo_articles import _launch_article_remaster_campaign

    return await _launch_article_remaster_campaign(**kwargs)


def _validate_remaster_report(
    report: dict,
    *,
    domain_handle: str,
    slug: str,
    pipeline_run_id: str,
) -> tuple[bool, str]:
    from backend.scripts.turbo_articles import _validate_article_remaster_report

    return _validate_article_remaster_report(
        report,
        target_count=30,
        expected_domain_handle=domain_handle,
        expected_slug=slug,
        expected_pipeline_run_id=pipeline_run_id,
    )


def _load_and_validate_campaign_report(
    *,
    project_root: Path,
    report_path_value: Any,
    domain_handle: str,
    slug: str,
    pipeline_run_id: str,
) -> Path:
    report_path = Path(str(report_path_value or "")).resolve()
    expected_root = (project_root / "data" / "reports" / "campaigns").resolve()
    try:
        report_path.relative_to(expected_root)
    except ValueError as exc:
        raise ReconciliationError("Campaign report is outside the maintained report directory") from exc
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ReconciliationError(f"Campaign report is unreadable: {exc}") from exc
    valid, reason = _validate_remaster_report(
        report,
        domain_handle=domain_handle,
        slug=slug,
        pipeline_run_id=pipeline_run_id,
    )
    if not valid:
        raise ReconciliationError(f"Campaign report failed the 15x2 proof contract: {reason}")
    return report_path


def _already_reconciled_result(
    context: BatchArticle,
    *,
    batch_id: str,
    domain_handle: str,
    pipeline_run_id: str,
    primary_job_id: str,
) -> dict | None:
    if context.state != "verified":
        return None
    proof = context.article.get("reconciliation_proof") or {}
    if not isinstance(proof, dict) or proof.get("primary_job_id") != primary_job_id:
        raise ReconciliationError("Batch article is already verified by different or missing proof")
    return {
        "success": True,
        "reconciled": False,
        "already_reconciled": True,
        "batch_id": batch_id,
        "domain_handle": domain_handle,
        "pipeline_run_id": pipeline_run_id,
        "keyword": context.keyword,
        "pin_id": str(proof.get("pin_id") or ""),
        "pin_url": str(proof.get("pin_url") or ""),
        "campaign_report": str(proof.get("campaign_report") or ""),
    }


async def reconcile_production_article(
    *,
    batch_id: str,
    domain_handle: str,
    pipeline_run_id: str,
    primary_job_id: str,
    project_root: Path = PROJECT_ROOT,
    pipeline_db_path: Path | None = None,
    batch_tracker: ProductionBatchTracker | None = None,
) -> dict:
    """Reconcile one late primary-pin result through the complete proof chain."""

    project_root = Path(project_root).resolve()
    if batch_tracker is not None and batch_tracker.batch_id != batch_id:
        raise ReconciliationError("Live batch tracker identity does not match the reconciliation")
    context = _load_batch_article(
        project_root=project_root,
        batch_id=batch_id,
        domain_handle=domain_handle,
        pipeline_run_id=pipeline_run_id,
    )
    already_reconciled = _already_reconciled_result(
        context,
        batch_id=batch_id,
        domain_handle=domain_handle,
        pipeline_run_id=pipeline_run_id,
        primary_job_id=primary_job_id,
    )
    if already_reconciled is not None:
        return already_reconciled
    if context.state != "needs verification":
        raise ReconciliationError(f"Batch article state is {context.state!r}, expected 'needs verification'")

    db_path = Path(pipeline_db_path or PIPELINE_DB)
    run = _load_pipeline_run(
        db_path=db_path,
        pipeline_run_id=pipeline_run_id,
        domain_handle=domain_handle,
        keyword=context.keyword,
    )
    domain = get_registry().get(domain_handle)
    outcome = _get_primary_job_outcome(primary_job_id)
    proof = _validate_primary_job(outcome, domain=domain, slug=run.slug)

    before = _get_supabase_article(run.slug, domain.handle)
    title, category, ingredients, steps, tip_text = _canonical_recipe_context(before)
    existing_pin_id = str(before.get("pinterest_pin_id") or "").strip()
    if existing_pin_id and existing_pin_id != proof.pin_id:
        raise ReconciliationError("Supabase already contains a different Pinterest pin ID")
    update = _update_supabase_pin(run.slug, proof.pin_id, domain.handle)
    if not update.get("success"):
        raise ReconciliationError(f"Supabase pin linkage failed: {update.get('error', 'unknown error')}")
    after = _get_supabase_article(run.slug, domain.handle)
    after_title, after_category, after_ingredients, after_steps, after_tip = _canonical_recipe_context(after)
    if str(after.get("pinterest_pin_id") or "").strip() != proof.pin_id:
        raise ReconciliationError("Supabase re-read did not confirm the exact primary pin ID")

    record_pipeline_stage(
        pipeline_run_id,
        "primary_pin_publish",
        "complete",
        "Late primary pin completion reconciled with verified proof",
        details={
            "primary_job_id": primary_job_id,
            "pin_id": proof.pin_id,
            "pin_url": proof.pin_url,
            "account_handle": proof.account_handle,
        },
        slug=run.slug,
        db_path=db_path,
    )
    record_pipeline_stage(
        pipeline_run_id,
        "verification",
        "running",
        "Primary pin is proven; verifying the complete 30-pin campaign",
        details={
            "primary_job_id": primary_job_id,
            "pin_id": proof.pin_id,
            "article_url": proof.article_url,
        },
        slug=run.slug,
        db_path=db_path,
    )

    remaster = await _launch_remaster_campaign(
        keyword=context.keyword,
        title=after_title or title,
        slug=run.slug,
        category=after_category or category or context.cluster,
        domain=domain,
        pipeline_run_id=pipeline_run_id,
        recipe_ingredients=after_ingredients or ingredients,
        recipe_steps=after_steps or steps,
        tip_text=after_tip or tip_text,
    )
    if not remaster.get("success"):
        record_pipeline_stage(
            pipeline_run_id,
            "pinterest_siphon",
            "failed",
            "Late reconciliation could not prove the complete paired campaign",
            details={"error": str(remaster.get("error") or "")[:240]},
            slug=run.slug,
            db_path=db_path,
        )
        set_pipeline_run_status(pipeline_run_id, "needs_verification", db_path=db_path)
        raise ReconciliationError(
            f"Remaster campaign is incomplete: {remaster.get('error', 'unknown error')}"
        )
    report_path = _load_and_validate_campaign_report(
        project_root=project_root,
        report_path_value=remaster.get("report_path"),
        domain_handle=domain.handle,
        slug=run.slug,
        pipeline_run_id=pipeline_run_id,
    )

    record_pipeline_stage(
        pipeline_run_id,
        "pinterest_siphon",
        "complete",
        "Reused or completed 15 source pairs and 30 queued pin variants",
        details={
            "generated": 30,
            "pairs": 15,
            "jobs_enqueued": 30,
            "report_path": str(report_path),
            "reused_existing_report": bool(remaster.get("reused_existing_report")),
        },
        slug=run.slug,
        db_path=db_path,
    )
    record_pipeline_stage(
        pipeline_run_id,
        "verification",
        "complete",
        "Late primary pin and complete 30-pin campaign verified",
        details={
            "pin_id": proof.pin_id,
            "pin_url": proof.pin_url,
            "article_url": proof.article_url,
            "campaign_report": str(report_path),
        },
        slug=run.slug,
        db_path=db_path,
    )
    set_pipeline_run_status(pipeline_run_id, "complete", db_path=db_path)

    roadmap_title = f"{domain.display_name} Keyword Roadmap"
    if not mark_keyword_status(
        domain.keywords_file,
        roadmap_title,
        context.keyword,
        "Live",
    ):
        set_pipeline_run_status(pipeline_run_id, "needs_verification", db_path=db_path)
        raise ReconciliationError("Keyword was not found in the domain roadmap; batch not credited")

    tracker = batch_tracker or ProductionBatchTracker(
        project_root=project_root,
        batch_id=batch_id,
        domain_handles=list(context.batch["domains"]),
        target_per_domain=int(context.batch["target_per_domain"]),
    )
    credited = tracker.reconcile_needs_verification(
        domain.handle,
        context.keyword,
        pipeline_run_id=pipeline_run_id,
        primary_job_id=primary_job_id,
        pin_id=proof.pin_id,
        pin_url=proof.pin_url,
        campaign_report=str(report_path),
    )
    if not credited:
        raise ReconciliationError("Batch article changed before exact-run credit could be recorded")
    batch_complete = tracker.finish_if_complete()
    return {
        "success": True,
        "reconciled": True,
        "already_reconciled": False,
        "batch_id": batch_id,
        "batch_complete": batch_complete,
        "domain_handle": domain.handle,
        "pipeline_run_id": pipeline_run_id,
        "keyword": context.keyword,
        "slug": run.slug,
        "article_url": proof.article_url,
        "primary_job_id": primary_job_id,
        "account_handle": proof.account_handle,
        "pin_id": proof.pin_id,
        "pin_url": proof.pin_url,
        "campaign_report": str(report_path),
        "campaign_jobs": 30,
    }
