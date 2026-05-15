"""
RankStein Pinterest Campaign Engine — Auto-Campaign on Article Publish

When an article is published to Supabase, this module:
1. Creates a Pinterest pin image (from hero or remastered stock)
2. Enqueues pin_upload jobs for ALL configured Pinterest accounts
3. Cross-save jobs auto-fire via supervisor after each upload succeeds

Usage:
    # Programmatic — called after publish_article_to_supabase
    from pinterest_automation.campaign import create_pinterest_campaign
    create_pinterest_campaign(slug, title, excerpt, domain_handle, image_path)

    # CLI — enqueue ALL images in remaster_final
    python run_autonomous.py enqueue-folder
"""

import logging
import re
from pathlib import Path

from .config import get_config
from .job_queue import get_job_queue
from .utils import normalize_slug, extract_slug_from_filename, get_title_from_slug

logger = logging.getLogger("rankstein.campaign")

import time
import threading

PROJECT_ROOT = Path(__file__).resolve().parent.parent
MEDIA_DIR = PROJECT_ROOT / "data" / "media"
REMASTER_DIR = MEDIA_DIR / "remaster_final"
NANOBANANA_DIR = PROJECT_ROOT / "nanobanana-output"

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
                    for f in d.iterdir():
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
                                "mtime": fstat.st_mtime
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
            logger.info(f"Image index refreshed: {len(self._cache)} files indexed, {len(self._map)} unique slugs")

    def find_best(self, slug: str) -> Path | None:
        """Search the indexed cache for the best image matching the slug."""
        self.refresh() # Auto-refresh if stale
        
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
            if not d.exists(): continue
            for f in d.iterdir():
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
                    return board_name

    if boards_default:
        for category, board in boards_default.items():
            if category != "_default" and category.lower() in slug_lower:
                return board
        if "_default" in boards_default:
            return boards_default["_default"]

    return config.default_board


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

    Enqueues pin_upload jobs for ALL configured Pinterest accounts.
    Cross-saves are handled automatically by the supervisor after each upload.

    Returns: {success, jobs_created, account_handles, image_path}
    """
    config = get_config()
    queue = get_job_queue()
    account_handles = sorted(config.accounts.keys())

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

    jobs_created = []
    for handle in account_handles:
        job_id = queue.enqueue_pin_upload(
            image_path=str(img),
            title=title,
            description=desc,
            link=link,
            board_name=board,
            priority=priority,
            extra={
                "slug": slug,
                "account_handle": handle,
                "domain_handle": domain_handle,
                "campaign_type": "article_publish",
            },
        )
        jobs_created.append({"job_id": job_id, "account": handle})
        logger.info(f"Campaign job enqueued: {handle} → {slug} (job={job_id})")

    logger.info(
        f"Pinterest campaign created for '{slug}': "
        f"{len(jobs_created)} jobs across {len(account_handles)} accounts"
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
    """Enqueue ALL pin images from a folder for ALL Pinterest accounts.

    Each image gets one pin_upload job per account.
    The supervisor's cross-save logic handles cross-pollination after upload.

    Returns: {total_images, jobs_enqueued, accounts, skipped}
    """
    if folder is None:
        folder = REMASTER_DIR

    if not folder.exists():
        return {"success": False, "error": f"Folder not found: {folder}"}

    config = get_config()
    queue = get_job_queue()
    account_handles = sorted(config.accounts.keys())

    if not account_handles:
        return {"success": False, "error": "No Pinterest accounts configured"}

    # Collect all images
    images = sorted(
        f for f in folder.iterdir()
        if f.is_file() and f.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp")
    )

    if not images:
        return {"success": False, "error": f"No images found in {folder}"}

    # Group images by slug (deduplicate — pick the largest per slug)
    slug_map: dict[str, Path] = {}
    for img in images:
        slug = extract_slug_from_filename(img.name)

        if slug not in slug_map or img.stat().st_size > slug_map[slug].stat().st_size:
            slug_map[slug] = img

    logger.info(f"Found {len(images)} images → {len(slug_map)} unique slugs")

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

        for handle in account_handles:
            queue.enqueue_pin_upload(
                image_path=str(img),
                title=title[:99],
                description=desc[:499],
                link=link,
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
