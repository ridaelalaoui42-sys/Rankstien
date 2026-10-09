"""
RankStein Pinterest Campaign Engine — Auto-Campaign on Article Publish

When an article is published to Supabase, this module:
1. Creates a Pinterest pin image (from hero or remastered stock)
2. Routes each asset to one account in the domain's configured cohort
3. Optionally adds a bounded number of cohort-local cross-saves

Usage:
    # Programmatic — called after publish_article_to_supabase
    from pinterest_automation.campaign import create_pinterest_campaign
    create_pinterest_campaign(slug, title, excerpt, domain_handle, image_path)

    # CLI — enqueue ALL images in remaster_final
    python run_autonomous.py enqueue-folder
"""

import hashlib
import json
import logging
import threading
import time
from collections import defaultdict
from pathlib import Path

from .config import get_config, normalize_board_name
from .job_queue import Job, get_job_queue
from .routing import account_cohort, select_upload_account
from .utils import extract_slug_from_filename, get_title_from_slug, normalize_slug

logger = logging.getLogger("rankstein.campaign")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
MEDIA_DIR = PROJECT_ROOT / "data" / "media"
REMASTER_DIR = MEDIA_DIR / "remaster_final"
NANOBANANA_DIR = PROJECT_ROOT / "nanobanana-output"

_ARTICLE_REMASTER_ASSET_TARGET = 30
_ARTICLE_REMASTER_SOURCE_TARGET = 15
_ARTICLE_REMASTER_VARIANTS = {"viral_visual", "recipe_card"}
_IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}
_INSERT_JOB_SQL = """
INSERT INTO jobs (
    id, type, payload_json, status, created_at, started_at, completed_at,
    attempt, max_attempts, next_retry_at, error_log_json, result_json, priority
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""


class ImagePathIndex:
    """In-memory index of images to avoid repeated disk scanning."""

    def __init__(self, media_dirs: list[Path]):
        self.media_dirs = media_dirs
        self._cache: list[dict] = []
        self._map: dict[str, list[dict]] = {}  # stripped slug -> list of candidate dicts
        self._last_refresh = 0
        self._lock = threading.Lock()
        self.refresh_interval = 300  # 5 minutes

    def refresh(self, force=False):
        """Build/rebuild the index of all images in media directories."""
        with self._lock:
            now = time.time()
            if not force and now - self._last_refresh < self.refresh_interval:
                return

            new_cache = []
            new_map = {}
            for d in self.media_dirs:
                if not d.exists():
                    continue
                try:
                    for f in d.rglob("*"):
                        if not f.is_file() or f.suffix.lower() not in (".jpg", ".jpeg", ".png", ".webp"):
                            continue

                        fname = f.name.lower()
                        # Use unified utility to extract the core slug
                        stripped = extract_slug_from_filename(fname)

                        try:
                            fstat = f.stat()
                            item = {
                                "path": f,
                                "name": fname,
                                "stripped": stripped,
                                "size": fstat.st_size,
                                "mtime": fstat.st_mtime,
                            }
                            new_cache.append(item)

                            # Build exact match map
                            if stripped not in new_map:
                                new_map[stripped] = []
                            new_map[stripped].append(item)

                        except (FileNotFoundError, PermissionError):
                            continue
                except Exception as e:
                    logger.warning(f"Error scanning directory {d}: {e}")

            self._cache = new_cache
            self._map = new_map
            self._last_refresh = now
            logger.info(
                f"Image index refreshed: {len(self._cache)} files indexed, {len(self._map)} unique slugs"
            )

    def find_best(self, slug: str) -> Path | None:
        """Search the indexed cache for the best image matching the slug."""
        self.refresh()  # Auto-refresh if stale

        slug_norm = normalize_slug(slug)
        slug_underscored = slug_norm.replace("-", "_")

        # 1. Try EXACT match via map first (O(1))
        exact_candidates = self._map.get(slug_norm)
        if exact_candidates:
            best = max(exact_candidates, key=lambda x: x["size"])
            return best["path"]

        # 2. Fallback to fuzzy search (O(N))
        candidates = []
        for item in self._cache:
            fname = item["name"]
            stripped = item["stripped"]

            # Match against stripped slug or full filename
            if (
                slug_norm in stripped
                or slug_norm in fname
                or slug_underscored in stripped
                or slug_underscored in fname
            ):
                candidates.append(item)

        if not candidates:
            return None

        # Return the path of the largest candidate
        best = max(candidates, key=lambda x: x["size"])
        return best["path"]


# Singleton indexer
_IMAGE_INDEX = ImagePathIndex([REMASTER_DIR, NANOBANANA_DIR, MEDIA_DIR])


def refresh_image_index():
    """Manually trigger a refresh of the image index (e.g. after generating new files)."""
    _IMAGE_INDEX.refresh(force=True)


def find_best_image(slug: str, media_dirs: list[Path] | None = None) -> Path | None:
    """Find the best remastered/hero image for a given post slug using the cached index."""
    # If custom media_dirs are provided, we don't use the global index
    if media_dirs is not None:
        # Fallback to legacy scan for custom dirs (rarely used)
        slug_norm = normalize_slug(slug)
        slug_underscored = slug_norm.replace("-", "_")

        candidates: list[Path] = []
        for d in media_dirs:
            if not d.exists():
                continue
            for f in d.rglob("*"):
                if not f.is_file() or f.suffix.lower() not in (".jpg", ".jpeg", ".png", ".webp"):
                    continue
                fname = f.name.lower()
                stripped = extract_slug_from_filename(fname)
                if (
                    slug_norm == stripped
                    or slug_norm in stripped
                    or slug_norm in fname
                    or slug_underscored in stripped
                    or slug_underscored in fname
                ):
                    candidates.append(f)
        return max(candidates, key=lambda f: f.stat().st_size) if candidates else None

    return _IMAGE_INDEX.find_best(slug)


def _get_board_for_slug(slug: str, boards_default: dict | None = None) -> str:
    """Pick a board name based on slug keywords."""
    config = get_config()
    slug_lower = slug.lower()

    for board_name, keywords in config.boards.items():
        if isinstance(keywords, list):
            for kw in keywords:
                if kw in slug_lower:
                    return normalize_board_name(board_name)

    if boards_default:
        for category, board in boards_default.items():
            if category != "_default" and category.lower() in slug_lower:
                return normalize_board_name(board)
        if "_default" in boards_default:
            return normalize_board_name(boards_default["_default"])

    return normalize_board_name(config.default_board)


def _build_recipe_alt_text(title: str) -> str:
    """Return concise Spanish accessibility text for generated recipe pins."""
    return f"Foto vertical de {title}, receta terminada y lista para servir."[:500]


def create_pinterest_campaign(
    slug: str,
    title: str,
    excerpt: str,
    domain_handle: str = "",
    domain_url: str = "",
    image_path: str | None = None,
    boards_default: dict | None = None,
    priority: int = 3,  # Higher priority than batch (5) since these are fresh articles
) -> dict:
    """Create a full Pinterest campaign for a newly published article.

    Enqueues one pin_upload job on a deterministic account in the domain cohort.

    Returns: {success, jobs_created, account_handles, image_path}
    """
    config = get_config()
    queue = get_job_queue()
    if not domain_handle:
        return {"success": False, "error": "domain_handle is required"}
    account_handles = account_cohort(domain_handle, config=config)

    if not account_handles:
        return {"success": False, "error": "No Pinterest accounts configured"}

    # Find image
    img = Path(image_path) if image_path else None
    if not img or not img.exists():
        img = find_best_image(slug)

    if not img:
        logger.warning(f"No image found for campaign: {slug}")
        return {"success": False, "error": f"No image found for slug: {slug}"}

    # Build pin metadata
    link = f"https://{domain_url}/{slug}" if domain_url else f"https://recetagenial.com/{slug}"
    desc = excerpt[:499] if excerpt else f"Aprende a preparar {title} paso a paso."
    board = _get_board_for_slug(slug, boards_default)

    handle = select_upload_account(domain_handle, slug, config=config)
    job_id = queue.enqueue_pin_upload(
        image_path=str(img),
        title=title,
        description=desc,
        link=link,
        alt_text=_build_recipe_alt_text(title),
        board_name=board,
        priority=priority,
        extra={
            "slug": slug,
            "account_handle": handle,
            "domain_handle": domain_handle,
            "campaign_type": "article_publish",
        },
    )
    jobs_created = [{"job_id": job_id, "account": handle}]
    logger.info(f"Campaign job enqueued: {handle} -> {slug} (job={job_id})")

    logger.info(
        f"Pinterest campaign created for '{slug}': "
        f"{len(jobs_created)} job routed across a {len(account_handles)}-account cohort"
    )

    return {
        "success": True,
        "slug": slug,
        "jobs_created": len(jobs_created),
        "account_handles": account_handles,
        "image_path": str(img),
        "board": board,
        "link": link,
        "details": jobs_created,
    }


def enqueue_folder(
    folder: Path | None = None,
    domain_url: str = "recetagenial.com",
    domain_handle: str = "",
    boards_default: dict | None = None,
) -> dict:
    """Enqueue each unique image once using the domain account cohort.

    Returns: {total_images, jobs_enqueued, accounts, skipped}
    """
    if folder is None:
        folder = REMASTER_DIR

    if not folder.exists():
        return {"success": False, "error": f"Folder not found: {folder}"}

    config = get_config()
    queue = get_job_queue()
    if not domain_handle:
        return {"success": False, "error": "domain_handle is required"}
    account_handles = account_cohort(domain_handle, config=config)

    if not account_handles:
        return {"success": False, "error": "No Pinterest accounts configured"}

    # Collect all images
    images = sorted(
        f for f in folder.rglob("*") if f.is_file() and f.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp")
    )

    if not images:
        return {"success": False, "error": f"No images found in {folder}"}

    # Group images by slug (deduplicate: pick the largest per slug)
    slug_map: dict[str, Path] = {}
    for img in images:
        slug = extract_slug_from_filename(img.name)

        if slug not in slug_map or img.stat().st_size > slug_map[slug].stat().st_size:
            slug_map[slug] = img

    logger.info(f"Found {len(images)} images -> {len(slug_map)} unique slugs")

    jobs_enqueued = 0
    skipped = 0
    for slug, img in sorted(slug_map.items()):
        # Build a title from the slug using unified utility
        title = get_title_from_slug(slug)
        if len(title) < 5:
            skipped += 1
            continue

        desc = f"Descubre esta deliciosa receta: {title}. Paso a paso con trucos de chef."
        link = f"https://{domain_url}/{slug}"
        board = _get_board_for_slug(slug, boards_default)

        handle = select_upload_account(domain_handle, slug, config=config)
        queue.enqueue_pin_upload(
            image_path=str(img),
            title=title[:99],
            description=desc[:499],
            link=link,
            alt_text=_build_recipe_alt_text(title),
            board_name=board,
            priority=5,
            extra={
                "slug": slug,
                "account_handle": handle,
                "domain_handle": domain_handle,
                "campaign_type": "folder_batch",
            },
        )
        jobs_enqueued += 1

    return {
        "success": True,
        "total_images": len(images),
        "unique_slugs": len(slug_map),
        "jobs_enqueued": jobs_enqueued,
        "accounts": account_handles,
        "skipped": skipped,
        "folder": str(folder),
    }


def _article_remaster_failure(error: str, *, slug: str = "", **details) -> dict:
    return {
        "success": False,
        "error": error,
        "slug": slug,
        "images_enqueued": 0,
        "jobs_enqueued": 0,
        "jobs_created": 0,
        "duplicates_skipped": int(details.pop("duplicates_skipped", 0)),
        "details": details.pop("job_details", []),
        **details,
    }


def _canonical_path(path: str | Path) -> str:
    return str(Path(path).resolve()).casefold()


def _validate_article_remaster_assets(
    *,
    image_paths: list[str] | None,
    asset_metadata: list[dict] | None,
    limit: int,
    domain_handle: str,
) -> tuple[list[tuple[Path, dict]], list[str]]:
    """Return the exact ordered 15x2 Pinterest set or validation errors."""
    paths = image_paths if isinstance(image_paths, list) else []
    assets = asset_metadata if isinstance(asset_metadata, list) else []
    errors: list[str] = []

    if limit != _ARTICLE_REMASTER_ASSET_TARGET:
        errors.append(
            f"production enqueue limit must be exactly {_ARTICLE_REMASTER_ASSET_TARGET}; received {limit}"
        )
    if len(paths) != _ARTICLE_REMASTER_ASSET_TARGET:
        errors.append(
            "production enqueue requires exactly "
            f"{_ARTICLE_REMASTER_ASSET_TARGET} validated assets; received {len(paths)}"
        )
    if len(assets) != _ARTICLE_REMASTER_ASSET_TARGET:
        errors.append(
            "production enqueue requires exactly "
            f"{_ARTICLE_REMASTER_ASSET_TARGET} asset metadata rows; received {len(assets)}"
        )

    ordered_paths: list[Path] = []
    path_keys: list[str] = []
    for raw_path in paths:
        if not isinstance(raw_path, (str, Path)) or not str(raw_path).strip():
            errors.append("every remaster asset must provide a non-empty image path")
            continue
        image = Path(raw_path)
        path_key = _canonical_path(image)
        if path_key in path_keys:
            errors.append(f"duplicate remaster image path: {image}")
            continue
        path_keys.append(path_key)
        if not image.is_file() or image.suffix.lower() not in _IMAGE_SUFFIXES:
            errors.append(f"missing or invalid remaster image: {image}")
        ordered_paths.append(image)

    metadata_by_path: dict[str, dict] = {}
    for asset in assets:
        if not isinstance(asset, dict):
            errors.append("every asset metadata row must be an object")
            continue
        raw_path = str(asset.get("remastered_path") or "").strip()
        if not raw_path:
            errors.append("every asset metadata row must include remastered_path")
            continue
        path_key = _canonical_path(raw_path)
        if path_key in metadata_by_path:
            errors.append(f"duplicate asset metadata path: {raw_path}")
            continue
        metadata_by_path[path_key] = asset

    if set(path_keys) != set(metadata_by_path):
        errors.append("image_paths and asset_metadata must describe the same exact 30 files")

    ordered_assets: list[tuple[Path, dict]] = []
    for image, path_key in zip(ordered_paths, path_keys, strict=False):
        asset = metadata_by_path.get(path_key)
        if asset is not None:
            ordered_assets.append((image, asset))

    pair_assets: dict[str, list[dict]] = defaultdict(list)
    for _image, asset in ordered_assets:
        pair_id = str(asset.get("pair_id") or "").strip()
        if not pair_id:
            errors.append("every remaster asset must include pair_id")
            continue
        pair_assets[pair_id].append(asset)

        if str(asset.get("source") or "").strip().lower() != "pinterest":
            errors.append(f"{pair_id} is not backed exclusively by a Pinterest source")
        if not str(asset.get("original_pin_id") or "").strip():
            errors.append(f"{pair_id} is missing its Pinterest source pin id")
        quality = asset.get("source_quality")
        source_path = Path(str(asset.get("source_path") or ""))
        source_hash = str(asset.get("source_hash") or "")
        if (
            not isinstance(quality, dict)
            or quality.get("accepted") is not True
            or quality.get("policy") != "text_free_pinterest_source"
            or quality.get("version") != 1
            or not source_hash
            or quality.get("source_hash") != source_hash
        ):
            errors.append(f"{pair_id} has no accepted, hash-bound source text review")
        else:
            try:
                if hashlib.sha256(source_path.read_bytes()).hexdigest() != source_hash:
                    errors.append(f"{pair_id} source changed after its text review")
            except OSError:
                errors.append(f"{pair_id} reviewed source image is unavailable")
        asset_domain = str(asset.get("domain_handle") or "").strip()
        if asset_domain and asset_domain.casefold() != domain_handle.casefold():
            errors.append(f"{pair_id} belongs to domain {asset_domain}, not requested domain {domain_handle}")

    if len(pair_assets) != _ARTICLE_REMASTER_SOURCE_TARGET:
        errors.append(
            "production requires exactly "
            f"{_ARTICLE_REMASTER_SOURCE_TARGET} Pinterest source pairs; received {len(pair_assets)}"
        )

    source_pin_ids: set[str] = set()
    for pair_id, pair in sorted(pair_assets.items()):
        variants = {str(item.get("variant") or "").strip() for item in pair}
        if len(pair) != 2 or variants != _ARTICLE_REMASTER_VARIANTS:
            errors.append(f"{pair_id} must contain exactly viral_visual and recipe_card")

        pin_ids = {str(item.get("original_pin_id") or "").strip() for item in pair}
        pin_ids.discard("")
        if len(pin_ids) != 1:
            errors.append(f"{pair_id} must reference one Pinterest source pin id")
            continue
        source_pin_id = next(iter(pin_ids))
        if source_pin_id in source_pin_ids:
            errors.append(f"Pinterest source pin {source_pin_id} is duplicated across pairs")
        source_pin_ids.add(source_pin_id)

    if len(source_pin_ids) != _ARTICLE_REMASTER_SOURCE_TARGET:
        errors.append(
            f"production requires {_ARTICLE_REMASTER_SOURCE_TARGET} unique Pinterest source pin ids; "
            f"received {len(source_pin_ids)}"
        )

    return ordered_assets, list(dict.fromkeys(errors))


def _remaster_idempotency_key(
    *,
    domain_handle: str,
    slug: str,
    source_pin_id: str,
    variant: str,
    account_handle: str,
) -> str:
    return "|".join(
        (
            domain_handle.strip().casefold(),
            slug.strip().casefold(),
            source_pin_id.strip().casefold(),
            variant.strip().casefold(),
            account_handle.strip().casefold(),
        )
    )


def _remaster_job_id(idempotency_key: str) -> str:
    digest = hashlib.sha256(idempotency_key.encode("utf-8")).hexdigest()[:24]
    return f"remaster-{digest}"


def _job_row(job: Job) -> tuple:
    return (
        job.id,
        job.type,
        json.dumps(job.payload, ensure_ascii=False),
        job.status,
        job.created_at,
        job.started_at,
        job.completed_at,
        job.attempt,
        job.max_attempts,
        job.next_retry_at,
        json.dumps(job.error_log, ensure_ascii=False),
        json.dumps(job.result, ensure_ascii=False) if job.result is not None else None,
        job.priority,
    )


def _existing_remaster_job(conn, *, job_id: str, idempotency_key: str) -> dict | None:
    lookups = (
        (
            "jobs",
            "payload_json",
            "$.extra.idempotency_key",
            "status",
            "active",
        ),
        (
            "dlq",
            "job_json",
            "$.payload.extra.idempotency_key",
            "'dead'",
            "dlq",
        ),
        (
            "completed_log",
            "job_json",
            "$.payload.extra.idempotency_key",
            "'completed'",
            "completed",
        ),
    )
    for table, json_column, key_path, state_expression, location in lookups:
        row = conn.execute(
            f"""
            SELECT id, {state_expression} AS state
            FROM {table}
            WHERE id = ?
               OR (json_valid({json_column}) AND json_extract({json_column}, ?) = ?)
            LIMIT 1
            """,
            (job_id, key_path, idempotency_key),
        ).fetchone()
        if row is not None:
            return {"job_id": str(row["id"]), "state": str(row["state"]), "location": location}
    return None


def _enqueue_remaster_jobs_atomically(queue, plans: list[dict]) -> dict:
    """Insert all missing jobs in one SQLite transaction.

    The maintained queue exposes its SQLite connection and process lock as the
    concurrency boundary. Fail closed for alternate queue implementations so a
    production 30-asset batch can never degrade to partially committed writes.
    """
    if not hasattr(queue, "_conn") or not hasattr(queue, "_lock"):
        raise TypeError("Pinterest queue does not support atomic remaster batches")

    with queue._lock, queue._conn() as conn:
        conn.execute("BEGIN IMMEDIATE;")
        try:
            records: list[dict] = []
            missing: list[dict] = []
            blocked: list[dict] = []
            for plan in plans:
                existing = _existing_remaster_job(
                    conn,
                    job_id=plan["job"].id,
                    idempotency_key=plan["idempotency_key"],
                )
                if existing is None:
                    missing.append(plan)
                    records.append(
                        {
                            **plan["detail"],
                            "job_id": plan["job"].id,
                            "state": "not_enqueued",
                            "created": False,
                        }
                    )
                    continue
                record = {**plan["detail"], **existing, "created": False}
                records.append(record)
                if existing["location"] == "dlq" or existing["state"] in {"dead", "failed", "held"}:
                    blocked.append(record)

            if blocked:
                conn.execute("ROLLBACK;")
                return {
                    "created": 0,
                    "existing": len(plans) - len(missing),
                    "records": records,
                    "blocked": blocked,
                }

            if missing:
                conn.executemany(_INSERT_JOB_SQL, [_job_row(plan["job"]) for plan in missing])
            conn.execute("COMMIT;")
        except Exception:
            conn.execute("ROLLBACK;")
            raise

    created_ids = {plan["job"].id for plan in missing}
    for record in records:
        if record["job_id"] in created_ids:
            record["state"] = "pending"
            record["created"] = True
    for plan in missing:
        logger.info("Enqueued atomic remaster job %s", plan["job"].id)
    return {
        "created": len(missing),
        "existing": len(plans) - len(missing),
        "records": records,
        "blocked": [],
    }


def enqueue_article_remasters(
    slug: str,
    title: str,
    excerpt: str = "",
    domain_url: str = "recetagenial.com",
    domain_handle: str = "",
    folder: Path | None = None,
    boards_default: dict | None = None,
    limit: int = 30,
    priority: int = 4,
    image_paths: list[str] | None = None,
    asset_metadata: list[dict] | None = None,
    pipeline_run_id: str = "",
) -> dict:
    """Atomically ensure one queued job for each validated 15x2 remaster asset.

    Production callers must provide the exact 30 just-generated files and their
    paired Pinterest-source metadata. The stable identity is
    ``domain|slug|source pin|variant|account``; it deliberately excludes file
    path and pipeline run so retries cannot duplicate active, DLQ, or recently
    completed work.
    """
    del folder  # Retained for API compatibility; production never scans stale folders.
    slug_norm = normalize_slug(slug)
    domain_handle = str(domain_handle or "").strip()
    if not domain_handle:
        return _article_remaster_failure("domain_handle is required", slug=slug_norm)
    if not slug_norm:
        return _article_remaster_failure("A valid article slug is required", slug=slug_norm)

    validated_assets, validation_errors = _validate_article_remaster_assets(
        image_paths=image_paths,
        asset_metadata=asset_metadata,
        limit=limit,
        domain_handle=domain_handle,
    )
    if validation_errors:
        return _article_remaster_failure(
            "Queue blocked by article remaster asset contract: " + "; ".join(validation_errors),
            slug=slug_norm,
            asset_validation={"success": False, "errors": validation_errors},
        )

    config = get_config()
    queue = get_job_queue()
    account_handles = account_cohort(domain_handle, config=config)
    if not account_handles:
        return _article_remaster_failure(
            "No Pinterest accounts configured",
            slug=slug_norm,
            asset_validation={"success": True},
        )

    configured_handles = {
        str(handle).strip().casefold(): str(handle).strip()
        for handle in account_handles
        if str(handle).strip()
    }
    desc = excerpt[:499] if excerpt else f"Aprende a preparar {title} paso a paso."
    link = f"https://{domain_url}/{slug_norm}"
    board = _get_board_for_slug(slug_norm, boards_default)
    plans: list[dict] = []
    routing_errors: list[str] = []
    for image, asset in validated_assets:
        source_pin_id = str(asset["original_pin_id"]).strip()
        variant = str(asset["variant"]).strip()
        routing_identity = f"{slug_norm}:{source_pin_id}:{variant}"
        selected_handle = str(
            select_upload_account(domain_handle, routing_identity, config=config) or ""
        ).strip()
        handle = configured_handles.get(selected_handle.casefold())
        if not handle:
            routing_errors.append(
                f"Account router returned unconfigured handle {selected_handle or '<empty>'}"
            )
            continue

        idempotency_key = _remaster_idempotency_key(
            domain_handle=domain_handle,
            slug=slug_norm,
            source_pin_id=source_pin_id,
            variant=variant,
            account_handle=handle,
        )
        creative_metadata = {
            key: asset[key]
            for key in (
                "pair_id",
                "source_index",
                "variant",
                "variant_label",
                "source_batch",
                "source",
                "original_pin_id",
                "original_url",
                "source_path",
                "source_hash",
                "source_quality",
            )
            if asset.get(key) not in (None, "")
        }
        extra = {
            "slug": slug_norm,
            "account_handle": handle,
            "domain_handle": domain_handle,
            "campaign_type": "article_remaster_pairs",
            "source_pin_id": source_pin_id,
            "idempotency_key": idempotency_key,
            "idempotency_version": 1,
            **creative_metadata,
            **({"pipeline_run_id": pipeline_run_id} if pipeline_run_id else {}),
        }
        job = Job(
            id=_remaster_job_id(idempotency_key),
            type="pin_upload",
            payload={
                "image_path": str(image),
                "title": title[:99],
                "description": desc,
                "link": link,
                "alt_text": _build_recipe_alt_text(title),
                "board_name": board,
                "extra": extra,
                "account_handle": handle,
                "domain_handle": domain_handle,
            },
            priority=priority,
            max_attempts=3,
        )
        plans.append(
            {
                "job": job,
                "idempotency_key": idempotency_key,
                "detail": {
                    "account": handle,
                    "image": str(image),
                    "idempotency_key": idempotency_key,
                    **creative_metadata,
                },
            }
        )

    if routing_errors or len(plans) != _ARTICLE_REMASTER_ASSET_TARGET:
        return _article_remaster_failure(
            "Queue blocked before mutation: "
            + "; ".join(dict.fromkeys(routing_errors or ["failed to build all 30 queue jobs"])),
            slug=slug_norm,
            asset_validation={"success": True},
        )

    try:
        enqueue_result = _enqueue_remaster_jobs_atomically(queue, plans)
    except Exception as exc:
        logger.exception("Atomic article remaster enqueue failed for %s", slug_norm)
        return _article_remaster_failure(
            f"Pinterest remaster batch enqueue failed atomically: {exc}",
            slug=slug_norm,
            asset_validation={"success": True},
        )

    if enqueue_result["blocked"]:
        return _article_remaster_failure(
            "Remaster batch retry found held or dead-lettered Pinterest job(s); "
            "use fresh reviewed sources for quality holds, or reconcile the DLQ before retrying",
            slug=slug_norm,
            duplicates_skipped=enqueue_result["existing"],
            job_details=enqueue_result["records"],
            blocked_job_ids=[item["job_id"] for item in enqueue_result["blocked"]],
            asset_validation={"success": True},
        )

    return {
        "success": True,
        "slug": slug_norm,
        "images_enqueued": _ARTICLE_REMASTER_ASSET_TARGET,
        "jobs_enqueued": _ARTICLE_REMASTER_ASSET_TARGET,
        "jobs_created": enqueue_result["created"],
        "duplicates_skipped": enqueue_result["existing"],
        "accounts": account_handles,
        "board": board,
        "link": link,
        "pipeline_run_id": pipeline_run_id,
        "asset_validation": {
            "success": True,
            "asset_count": _ARTICLE_REMASTER_ASSET_TARGET,
            "source_count": _ARTICLE_REMASTER_SOURCE_TARGET,
        },
        "details": enqueue_result["records"],
    }
