"""
RankStein Remasterer — Viral Pin Resurrection Engine
Scrapes, downloads, edits, and republishes viral pins with luxury branding.
"""

import asyncio
import json
import math
import os
import re
import sqlite3
import sys
import time
import unicodedata
from contextlib import suppress
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from urllib.parse import quote_plus
from uuid import uuid4

import httpx
import piexif
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont
from playwright.async_api import async_playwright
from playwright_stealth import Stealth

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from rankstein.pipeline_events import record_pipeline_stage, set_pipeline_run_status
from rankstein.remaster_variants import create_recipe_card_pin, create_viral_visual_pin
from rankstein.source_image_quality import assess_source_image


def _pipeline_event(
    run_id: str,
    stage: str,
    state: str,
    message: str,
    **details,
) -> None:
    """Keep telemetry failures isolated from long-running image production."""

    if not run_id:
        return
    try:
        record_pipeline_stage(
            run_id,
            stage,
            state,
            message,
            details=details,
        )
    except Exception:
        pass


def _pipeline_status(run_id: str, status: str) -> None:
    if not run_id:
        return
    try:
        set_pipeline_run_status(run_id, status)
    except Exception:
        pass


# Configuration
PINTEREST_BASE = "https://es.pinterest.com"
SESSION_DIR = Path("data/sessions/remasterer_v1")
DOWNLOAD_DIR = Path("data/media/remaster_raw")
REMASTER_DIR = Path("data/media/remaster_final")
CAMPAIGN_REPORT_DIR = Path("data/reports/campaigns")
[d.mkdir(parents=True, exist_ok=True) for d in [DOWNLOAD_DIR, REMASTER_DIR, CAMPAIGN_REPORT_DIR]]

DEFAULT_PINS_PER_KEYWORD = int(os.environ.get("RANKSTEIN_REMASTER_PINS_PER_KEYWORD", "30"))
MIN_RELEVANCE_SCORE = int(os.environ.get("RANKSTEIN_IMAGE_RELEVANCE_MIN_SCORE", "2"))
MIN_IMAGE_WIDTH = int(os.environ.get("RANKSTEIN_REMASTER_MIN_IMAGE_WIDTH", "500"))
MIN_IMAGE_HEIGHT = int(os.environ.get("RANKSTEIN_REMASTER_MIN_IMAGE_HEIGHT", "700"))
PRODUCTION_SOURCE_TARGET = 15
PRODUCTION_ASSET_TARGET = 30
PRODUCTION_VARIANTS = {"viral_visual", "recipe_card"}
COLLECTION_TIMEOUT_SECONDS = 600.0
BROWSER_START_TIMEOUT_SECONDS = 60.0
BROWSER_STOP_TIMEOUT_SECONDS = 20.0
SOURCE_INTAKE_TIMEOUT_SECONDS = 680.0
COLLECTION_PROGRESS_INTERVAL_SECONDS = 5.0
DEFAULT_CANDIDATE_LIMIT = 90
PINTEREST_PIN_CARD_SELECTOR = '[data-test-id="pin"], [data-grid-item="true"]'
PINTEREST_LOGIN_WALL_MARKERS = (
    "has cerrado sesión",
    "you've been logged out",
    "you have been logged out",
)


def _bounded_seconds(name: str, default: float, maximum: float, requested=None) -> float:
    try:
        value = float(os.environ.get(name, str(default)) if requested is None else requested)
        if not math.isfinite(value) or value <= 0:
            raise ValueError("invalid deadline")
    except (TypeError, ValueError):
        value = default
    return min(maximum, max(0.01, value))


def _candidate_limit(requested=None) -> int:
    try:
        value = int(
            os.environ.get("RANKSTEIN_REMASTER_CANDIDATE_LIMIT", str(DEFAULT_CANDIDATE_LIMIT))
            if requested is None
            else requested
        )
    except (TypeError, ValueError):
        value = DEFAULT_CANDIDATE_LIMIT
    return max(1, min(value, 150))


def _isolated_remaster_directories(domain_handle: str, pipeline_run_id: str) -> tuple[Path, Path]:
    """Each attempt owns new paths; held queue payload files are never replaced."""
    domain = re.sub(r"[^a-zA-Z0-9_-]+", "-", domain_handle).strip("-") or "manual"
    run = re.sub(r"[^a-zA-Z0-9_-]+", "-", pipeline_run_id).strip("-") or "manual"
    attempt = f"{datetime.now(UTC):%Y%m%d_%H%M%S_%f}-{uuid4().hex[:8]}"
    suffix = Path(domain) / run / attempt
    return DOWNLOAD_DIR / suffix, REMASTER_DIR / suffix


def _held_campaign_source_pin_ids(
    domain_handle: str,
    pipeline_run_id: str,
    *,
    queue_paths: list[Path] | None = None,
) -> set[str]:
    """Read only actual held jobs for this exact domain/run, never report claims.

    Do not instantiate JobQueue here: its initialization can migrate legacy
    queue state. Both shared and domain partitions are checked read-only.
    """
    if not domain_handle or not pipeline_run_id:
        return set()
    if queue_paths is None:
        from pinterest_automation.job_queue import DB_FILE
        from rankstein.domain import get_registry

        domain = get_registry().get(domain_handle)
        queue_paths = [Path(DB_FILE), domain.root / "jobs.db"]
    excluded: set[str] = set()
    deadline = time.monotonic() + 3.0
    for path in dict.fromkeys(Path(value).resolve() for value in queue_paths):
        if not path.is_file():
            continue
        with sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True, timeout=3.0) as connection:
            connection.set_progress_handler(lambda: int(time.monotonic() >= deadline), 1000)
            for (payload_json,) in connection.execute(
                "SELECT payload_json FROM jobs WHERE status = 'held' AND type = 'pin_upload'"
            ):
                payload = json.loads(payload_json)
                extra = payload.get("extra") if isinstance(payload, dict) else None
                if not isinstance(extra, dict):
                    continue
                if (
                    extra.get("campaign_type") != "article_remaster_pairs"
                    or extra.get("pipeline_run_id") != pipeline_run_id
                    or extra.get("domain_handle") != domain_handle
                    or payload.get("domain_handle", domain_handle) != domain_handle
                ):
                    continue
                pin_id = str(extra.get("source_pin_id") or "").strip()
                if re.fullmatch(r"[0-9]+", pin_id):
                    excluded.add(pin_id)
    return excluded


def _emit_source_progress(studio, *, deadline: float) -> None:
    diagnostics = getattr(studio, "last_collection_diagnostics", {})
    diagnostics["remaining_seconds"] = round(max(0.0, deadline - time.monotonic()), 1)
    print(
        "SOURCE_COLLECTION_PROGRESS "
        f"phase={diagnostics.get('phase', 'collecting')} "
        f"accepted={diagnostics.get('accepted', 0)} "
        f"examined={diagnostics.get('pins_examined', 0)} "
        f"ocr_running={diagnostics.get('ocr_in_progress', 0)} "
        f"text_rejected={diagnostics.get('text_rejected', 0)} "
        f"text_unavailable={diagnostics.get('text_unavailable', 0)} "
        f"held_sources_skipped={diagnostics.get('held_sources_skipped', 0)} "
        f"blocked_reason={diagnostics.get('blocked_reason', '')} "
        f"remaining_seconds={diagnostics['remaining_seconds']}",
        flush=True,
    )


async def _source_progress_heartbeat(studio, finished: asyncio.Event, *, deadline: float) -> None:
    # An Event waiter avoids a tight loop if a caller replaces asyncio.sleep.
    while not finished.is_set():
        try:
            await asyncio.wait_for(finished.wait(), timeout=COLLECTION_PROGRESS_INTERVAL_SECONDS)
        except TimeoutError:
            _emit_source_progress(studio, deadline=deadline)


class _ProfileLease:
    """Nonblocking cross-process lease; the OS releases it if its owner dies."""

    def __init__(self, profile: Path):
        self.path = profile / ".rankstein-remaster.lease"
        self.stream = None

    def acquire(self) -> bool:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        stream = self.path.open("a+b")
        try:
            if stream.seek(0, 2) == 0:
                stream.write(b"0")
                stream.flush()
            stream.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            stream.close()
            return False
        self.stream = stream
        return True

    def release(self) -> None:
        if self.stream is None:
            return
        try:
            self.stream.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(self.stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(self.stream.fileno(), fcntl.LOCK_UN)
        finally:
            self.stream.close()
            self.stream = None


def _resolve_session_name(session_name: str | None = None, *, domain_handle: str = "") -> str:
    """Return a filesystem-safe browser session name for one remaster run.

    Explicit names allow the campaign launcher to dedicate one persistent
    Chromium profile to each domain.  Direct callers that provide neither a
    name nor a domain get a unique profile so concurrent jobs cannot close or
    unlock one another's browser context.
    """

    requested = str(session_name or "").strip()
    if not requested and domain_handle:
        requested = f"remasterer_{domain_handle}"
    if not requested:
        requested = f"remasterer_{os.getpid()}_{uuid4().hex[:8]}"

    safe_name = re.sub(r"[^A-Za-z0-9_.-]+", "-", requested).strip("._-")
    if not safe_name:
        raise ValueError("Remaster browser session name cannot be empty")
    return safe_name[:96]


def _is_pinterest_login_wall_text(value: str) -> bool:
    normalized = str(value or "").casefold()
    return any(marker in normalized for marker in PINTEREST_LOGIN_WALL_MARKERS)


async def _page_has_pinterest_login_wall(page) -> bool:
    try:
        body_text = await page.locator("body").inner_text(timeout=5000)
    except Exception:
        return False
    return _is_pinterest_login_wall_text(body_text)


async def _query_pinterest_pin_cards(page):
    return await page.query_selector_all(PINTEREST_PIN_CARD_SELECTOR)


DEFAULT_BLOCKED_TERMS = {
    "outfit",
    "moda",
    "nails",
    "uñas",
    "makeup",
    "maquillaje",
    "hair",
    "cabello",
    "tattoo",
    "decor",
    "wedding",
    "boda",
    "meme",
    "quote",
    "frase",
    "wallpaper",
    "fitness",
    "workout",
}

RECIPE_SIGNAL_TERMS = {
    "receta",
    "recetas",
    "recipe",
    "recipes",
    "comida",
    "plato",
    "dish",
    "food",
    "cocina",
    "cocinar",
    "ingrediente",
    "ingredientes",
    "preparacion",
    "preparación",
    "almuerzo",
    "cena",
    "desayuno",
    "postre",
    "ensalada",
    "sopa",
    "pollo",
    "pasta",
    "arroz",
}

RELEVANCE_STOPWORDS = {
    "con",
    "sin",
    "para",
    "por",
    "las",
    "los",
    "una",
    "uno",
    "unas",
    "unos",
    "del",
    "de",
    "la",
    "el",
    "al",
    "estilo",
    "receta",
    "recetas",
    "facil",
    "faciles",
    "casera",
    "casero",
    "rapida",
    "rapido",
}

GENERIC_DISH_TERMS = {
    "aire",
    "aperitivo",
    "aperitivos",
    "asada",
    "asado",
    "comida",
    "cocina",
    "ensalada",
    "ensaladas",
    "freidora",
    "frita",
    "frito",
    "horno",
    "olla",
    "plato",
    "postre",
    "postres",
    "tarta",
    "tartas",
}


def _paired_output_target(value: int | str | None) -> int:
    """Return the fixed production contract: fifteen sources, two variants each."""

    del value
    return PRODUCTION_ASSET_TARGET


def _normalize_text(value: str) -> str:
    text = unicodedata.normalize("NFKD", value or "")
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def _keyword_tokens(keyword: str) -> set[str]:
    return {
        tok for tok in _normalize_text(keyword).split() if len(tok) >= 3 and tok not in RELEVANCE_STOPWORDS
    }


def _term_set(value: str | list[str] | tuple[str, ...] | set[str] | None) -> set[str]:
    if value is None:
        return set()
    if isinstance(value, str):
        raw = re.split(r"[,;\n]+", value)
    else:
        raw = list(value)
    terms: set[str] = set()
    for item in raw:
        terms.update(_keyword_tokens(str(item)))
    return terms


def _value_list(value: str | list[str] | tuple[str, ...] | set[str] | None) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, str):
        return [str(item).strip() for item in value if str(item).strip()]
    text = value.strip()
    if not text:
        return []
    if text.startswith("["):
        try:
            parsed = json.loads(text)
            if isinstance(parsed, list):
                return [str(item).strip() for item in parsed if str(item).strip()]
        except json.JSONDecodeError:
            pass
    return [item.strip() for item in re.split(r"\|\||[\r\n]+", text) if item.strip()]


def score_pin_relevance(
    keyword: str,
    alt_text: str = "",
    href: str = "",
    title: str = "",
    description: str = "",
    board_name: str = "",
    core_terms: str | list[str] | tuple[str, ...] | set[str] | None = None,
    min_core_matches: int | None = None,
    expected_terms: str | list[str] | tuple[str, ...] | set[str] | None = None,
    blocked_terms: str | list[str] | tuple[str, ...] | set[str] | None = None,
) -> int:
    """Score whether a scraped Pinterest image matches the generated scrape brief."""

    haystack = _normalize_text(f"{alt_text} {title} {description} {board_name} {href}")
    if not haystack:
        return 0
    tokens = set(haystack.split())
    keyword_terms = _keyword_tokens(keyword)
    dish_core = _term_set(core_terms) or (keyword_terms - GENERIC_DISH_TERMS)
    if not dish_core:
        dish_core = keyword_terms
    generated_terms = _term_set(expected_terms)
    blocked = (
        _term_set(blocked_terms)
        or _term_set(os.environ.get("RANKSTEIN_IMAGE_BLOCKED_TERMS"))
        or DEFAULT_BLOCKED_TERMS
    )
    keyword_hits = len(keyword_terms & tokens)
    core_hits = len(dish_core & tokens)
    required_core_hits = max(1, min(int(min_core_matches or 1), len(dish_core)))
    generated_hits = len((generated_terms - keyword_terms) & tokens)
    blocked_hits = len(blocked & tokens)
    if blocked_hits:
        return -blocked_hits * 4
    if dish_core and core_hits < required_core_hits:
        return -6 - (required_core_hits - core_hits)
    if keyword_terms and keyword_hits == 0:
        return -4

    normalized_keyword = _normalize_text(keyword)
    exact_phrase = bool(normalized_keyword and normalized_keyword in haystack)
    recipe_hits = len(tokens & RECIPE_SIGNAL_TERMS)
    generic_keyword_hits = max(0, keyword_hits - core_hits)
    score = core_hits * 4 + generic_keyword_hits * 2 + generated_hits
    score += min(recipe_hits, 2) * 2
    if exact_phrase:
        score += 4
    if not recipe_hits and not exact_phrase and keyword_hits < 2:
        score -= 3
    return score


def is_relevant_recipe_pin(
    keyword: str,
    alt_text: str = "",
    href: str = "",
    title: str = "",
    description: str = "",
    board_name: str = "",
    core_terms: str | list[str] | tuple[str, ...] | set[str] | None = None,
    min_core_matches: int | None = None,
    expected_terms: str | list[str] | tuple[str, ...] | set[str] | None = None,
    blocked_terms: str | list[str] | tuple[str, ...] | set[str] | None = None,
) -> bool:
    return (
        score_pin_relevance(
            keyword,
            alt_text,
            href,
            title=title,
            description=description,
            board_name=board_name,
            core_terms=core_terms,
            min_core_matches=min_core_matches,
            expected_terms=expected_terms,
            blocked_terms=blocked_terms,
        )
        >= MIN_RELEVANCE_SCORE
    )


def inject_seo_metadata(image_path, title, description, keywords):
    """Injects EXIF metadata (Title, Description, Keywords) into JPEG images for SEO."""
    try:
        # Only works on JPEGs easily with piexif
        if str(image_path).lower().endswith((".png", ".webp")):
            return  # Skip PNG/WEBP for now, or convert to JPEG first

        exif_dict = {"0th": {}, "Exif": {}, "GPS": {}, "1st": {}, "Interop": {}}

        # Standard Exif
        exif_dict["0th"][piexif.ImageIFD.ImageDescription] = description.encode("utf-8")

        # Windows XP Tags (Highly read by search engines)
        exif_dict["0th"][piexif.ImageIFD.XPTitle] = title.encode("utf-16le")
        exif_dict["0th"][piexif.ImageIFD.XPComment] = description.encode("utf-16le")
        exif_dict["0th"][piexif.ImageIFD.XPKeywords] = keywords.encode("utf-16le")

        exif_bytes = piexif.dump(exif_dict)
        piexif.insert(exif_bytes, str(image_path))
        print(f"   SEO Metadata injected into {Path(image_path).name}")
    except Exception as e:
        print(f"   FAILED to inject metadata: {e}")


class PinRemasterer:
    def __init__(self, headless=True, session_name: str | None = None):
        self.headless = headless
        self.session_name = _resolve_session_name(session_name)
        self.session_dir = SESSION_DIR.parent / self.session_name
        self.session_dir.mkdir(parents=True, exist_ok=True)
        self.pw = None
        self.context = None
        self.page = None
        self._profile_lease = None
        self.last_collection_diagnostics: dict[str, int | str] = {}

    async def start(self):
        # Never delete locks or kill another campaign's browser. A legacy
        # owner without this lease is protected by Chromium's profile lock.
        lease = _ProfileLease(self.session_dir)
        if self._profile_lease is not None or not lease.acquire():
            raise RuntimeError("remaster_profile_busy")
        self._profile_lease = lease
        try:
            await self._start_browser()
        except BaseException:
            lease.release()
            self._profile_lease = None
            raise

    async def _start_browser(self):
        self.pw = await async_playwright().start()
        launch_options = {
            "user_data_dir": str(self.session_dir),
            "headless": self.headless,
            "viewport": {"width": 1440, "height": 900},
            "locale": "es-ES",
            "args": [
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
                "--disable-blink-features=AutomationControlled",
            ],
        }
        chromium_channel = os.environ.get("PINTEREST_CHROMIUM_CHANNEL", "chrome").strip()
        if chromium_channel:
            launch_options["channel"] = chromium_channel
            launch_options["ignore_default_args"] = ["--enable-automation"]
        self.context = await self.pw.chromium.launch_persistent_context(
            **launch_options,
        )
        await self.context.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"
        )
        self.page = self.context.pages[0] if self.context.pages else await self.context.new_page()
        await Stealth().apply_stealth_async(self.page)

    async def stop(self):
        try:
            if self.context:
                await self.context.close()
            if self.pw:
                await self.pw.stop()
        finally:
            if self._profile_lease is not None:
                self._profile_lease.release()
                self._profile_lease = None

    async def collect_and_download(
        self,
        keyword: str,
        count: int = 50,
        search_query: str = "",
        search_queries: str | list[str] | tuple[str, ...] | set[str] | None = None,
        core_terms: str | list[str] | tuple[str, ...] | set[str] | None = None,
        min_core_matches: int | None = None,
        expected_terms: str | list[str] | tuple[str, ...] | set[str] | None = None,
        blocked_terms: str | list[str] | tuple[str, ...] | set[str] | None = None,
        excluded_pin_ids: set[str] | list[str] | None = None,
        download_dir: Path | None = None,
        max_candidates: int | None = None,
        timeout_seconds: float | None = None,
        progress_enabled: bool = True,
    ):
        """Bound collection, including navigation/download/OCR, to ten minutes."""
        timeout = _bounded_seconds(
            "RANKSTEIN_REMASTER_COLLECTION_TIMEOUT_SECONDS",
            COLLECTION_TIMEOUT_SECONDS,
            COLLECTION_TIMEOUT_SECONDS,
            timeout_seconds,
        )
        deadline = time.monotonic() + timeout
        finished = asyncio.Event()
        heartbeat = (
            asyncio.create_task(_source_progress_heartbeat(self, finished, deadline=deadline))
            if progress_enabled
            else None
        )
        try:
            results = await asyncio.wait_for(
                self._collect_and_download(
                    keyword,
                    count=count,
                    search_query=search_query,
                    search_queries=search_queries,
                    core_terms=core_terms,
                    min_core_matches=min_core_matches,
                    expected_terms=expected_terms,
                    blocked_terms=blocked_terms,
                    excluded_pin_ids=set(excluded_pin_ids or []),
                    download_dir=download_dir or _isolated_remaster_directories("collector", "")[0],
                    max_candidates=_candidate_limit(max_candidates),
                ),
                timeout=timeout,
            )
            if len(results) < count and not self.last_collection_diagnostics.get("blocked_reason"):
                self.last_collection_diagnostics["blocked_reason"] = "insufficient_clean_sources"
            return results
        except TimeoutError:
            self.last_collection_diagnostics.update(blocked_reason="collection_timeout", deadline_exceeded=1)
            return []
        except asyncio.CancelledError:
            self.last_collection_diagnostics["blocked_reason"] = "collection_cancelled"
            raise
        finally:
            self.last_collection_diagnostics["ocr_in_progress"] = 0
            finished.set()
            if heartbeat:
                heartbeat.cancel()
                with suppress(asyncio.CancelledError):
                    await heartbeat
            _emit_source_progress(self, deadline=deadline)

    async def _collect_and_download(
        self,
        keyword: str,
        count: int = 50,
        search_query: str = "",
        search_queries: str | list[str] | tuple[str, ...] | set[str] | None = None,
        core_terms: str | list[str] | tuple[str, ...] | set[str] | None = None,
        min_core_matches: int | None = None,
        expected_terms: str | list[str] | tuple[str, ...] | set[str] | None = None,
        blocked_terms: str | list[str] | tuple[str, ...] | set[str] | None = None,
        excluded_pin_ids: set[str] | None = None,
        download_dir: Path | None = None,
        max_candidates: int = DEFAULT_CANDIDATE_LIMIT,
    ):
        """Scrape multiple generated queries and download strongly relevant pins."""
        print(f"Collecting {count} viral pins for: {keyword}...")
        results = []
        excluded_pin_ids = excluded_pin_ids or set()
        download_dir = download_dir or DOWNLOAD_DIR
        download_dir.mkdir(parents=True, exist_ok=True)
        generated_queries = _value_list(search_queries)
        primary_query = (search_query or keyword).strip()
        if primary_query and primary_query not in generated_queries:
            generated_queries.insert(0, primary_query)
        try:
            query_limit = max(1, min(int(os.environ.get("RANKSTEIN_REMASTER_QUERY_LIMIT", "6")), 8))
        except (TypeError, ValueError):
            query_limit = 6
        try:
            navigation_attempts = max(
                1,
                min(int(os.environ.get("RANKSTEIN_REMASTER_QUERY_ATTEMPTS", "2")), 3),
            )
        except (TypeError, ValueError):
            navigation_attempts = 2
        try:
            scroll_rounds = max(
                4,
                min(int(os.environ.get("RANKSTEIN_REMASTER_SCROLL_ROUNDS", "10")), 20),
            )
        except (TypeError, ValueError):
            scroll_rounds = 10

        generated_queries = list(dict.fromkeys(generated_queries))[:query_limit] or [keyword]
        examined_pin_ids: set[str] = set()
        diagnostics = {
            "queries_planned": len(generated_queries),
            "query_attempts": 0,
            "queries_succeeded": 0,
            "query_failures": 0,
            "login_wall_detected": 0,
            "blocked_reason": "",
            "result_cards_seen": 0,
            "pin_images_seen": 0,
            "pin_links_seen": 0,
            "pins_examined": 0,
            "duplicates_skipped": 0,
            "relevance_rejected": 0,
            "download_failed": 0,
            "undersized_rejected": 0,
            "invalid_image_rejected": 0,
            "text_rejected": 0,
            "text_unavailable": 0,
            "held_sources_skipped": 0,
            "excluded_source_count": len(excluded_pin_ids),
            "candidate_limit": max_candidates,
            "deadline_exceeded": 0,
            "ocr_checks_started": 0,
            "ocr_checks_completed": 0,
            "ocr_in_progress": 0,
            "phase": "collecting",
            "accepted": 0,
        }
        self.last_collection_diagnostics = diagnostics

        timeout = httpx.Timeout(30.0, connect=15.0)
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            for query_index, resolved_query in enumerate(generated_queries, 1):
                if len(results) >= count or diagnostics["pins_examined"] >= max_candidates:
                    break
                print(f"   Search {query_index}/{len(generated_queries)}: {resolved_query}")
                search_url = f"{PINTEREST_BASE}/search/pins/?q={quote_plus(resolved_query)}&rs=typed"
                navigation_succeeded = False
                for navigation_attempt in range(1, navigation_attempts + 1):
                    diagnostics["query_attempts"] += 1
                    try:
                        await self.page.goto(search_url, wait_until="domcontentloaded", timeout=60000)
                        diagnostics["queries_succeeded"] += 1
                        navigation_succeeded = True
                        break
                    except Exception as exc:
                        diagnostics["query_failures"] += 1
                        print(
                            f"   Search {query_index} attempt "
                            f"{navigation_attempt}/{navigation_attempts} unavailable: "
                            f"{type(exc).__name__}"
                        )
                        if (self.page is None or self.page.is_closed()) and self.context is not None:
                            self.page = await self.context.new_page()
                            await Stealth().apply_stealth_async(self.page)
                if not navigation_succeeded:
                    print(f"   Search {query_index} exhausted; continuing with bounded query set")
                    continue
                await asyncio.sleep(3)
                if await _page_has_pinterest_login_wall(self.page):
                    diagnostics["login_wall_detected"] += 1
                    diagnostics["blocked_reason"] = "pinterest_login_required"
                    try:
                        diagnostics["result_cards_seen"] = await self.page.locator(
                            '[data-grid-item="true"]'
                        ).count()
                        diagnostics["pin_images_seen"] = await self.page.locator(
                            'img[src*="pinimg.com"]'
                        ).count()
                        diagnostics["pin_links_seen"] = await self.page.locator('a[href*="/pin/"]').count()
                    except Exception:
                        pass
                    print(
                        "   Pinterest session is logged out; domain remaster profile must be "
                        "authenticated before source collection"
                    )
                    break

                stagnant_rounds = 0
                previous_examined = len(examined_pin_ids)
                for _scroll_round in range(scroll_rounds):
                    pins = await _query_pinterest_pin_cards(self.page)
                    diagnostics["result_cards_seen"] = max(diagnostics["result_cards_seen"], len(pins))
                    for pin in pins:
                        if len(results) >= count:
                            break
                        try:
                            link_el = await pin.query_selector('a[href*="/pin/"]')
                            img_el = await pin.query_selector("img")
                            if not link_el or not img_el:
                                continue

                            diagnostics["pin_links_seen"] += 1

                            href = await link_el.get_attribute("href") or ""
                            pin_match = re.search(r"/pin/(\d+)", href)
                            if not pin_match:
                                continue
                            pin_id = pin_match.group(1)
                            if pin_id in examined_pin_ids:
                                diagnostics["duplicates_skipped"] += 1
                                continue
                            examined_pin_ids.add(pin_id)
                            if pin_id in excluded_pin_ids:
                                diagnostics["held_sources_skipped"] += 1
                                continue
                            if diagnostics["pins_examined"] >= max_candidates:
                                diagnostics["blocked_reason"] = "candidate_limit"
                                break
                            diagnostics["pins_examined"] += 1

                            img_url = await img_el.get_attribute("src") or ""
                            srcset = await img_el.get_attribute("srcset") or ""
                            if srcset:
                                srcset_urls = [
                                    item.strip().split()[0] for item in srcset.split(",") if item.strip()
                                ]
                                if srcset_urls:
                                    img_url = srcset_urls[-1]
                            if not img_url:
                                continue
                            img_url = (
                                img_url.replace("236x", "originals")
                                .replace("474x", "originals")
                                .replace("736x", "originals")
                            )

                            alt_text = await img_el.get_attribute("alt") or ""
                            title = (
                                await link_el.get_attribute("aria-label")
                                or await link_el.get_attribute("title")
                                or ""
                            )
                            description = (await pin.inner_text()).strip()
                            board_el = await pin.query_selector('[data-test-id*="board"]')
                            board_name = (await board_el.inner_text()).strip() if board_el else ""
                            relevance_score = score_pin_relevance(
                                keyword,
                                alt_text,
                                href,
                                title=title,
                                description=description,
                                board_name=board_name,
                                core_terms=core_terms,
                                min_core_matches=min_core_matches,
                                expected_terms=expected_terms,
                                blocked_terms=blocked_terms,
                            )
                            if relevance_score < MIN_RELEVANCE_SCORE:
                                diagnostics["relevance_rejected"] += 1
                                continue

                            resp = await client.get(
                                img_url,
                                headers={"Referer": "https://www.pinterest.com/"},
                            )
                            if resp.status_code != 200:
                                diagnostics["download_failed"] += 1
                                continue
                            try:
                                with Image.open(BytesIO(resp.content)) as probe:
                                    width, height = probe.size
                                    image_format = (probe.format or "JPEG").lower()
                                if width < MIN_IMAGE_WIDTH or height < MIN_IMAGE_HEIGHT:
                                    diagnostics["undersized_rejected"] += 1
                                    continue
                            except Exception:
                                diagnostics["invalid_image_rejected"] += 1
                                continue

                            file_ext = ".png" if image_format == "png" else ".jpg"
                            raw_path = download_dir / f"{pin_id}{file_ext}"
                            raw_path.write_bytes(resp.content)
                            diagnostics["ocr_checks_started"] += 1
                            diagnostics["ocr_in_progress"] = 1
                            try:
                                source_quality = await asyncio.to_thread(assess_source_image, raw_path)
                            finally:
                                diagnostics["ocr_in_progress"] = 0
                            diagnostics["ocr_checks_completed"] += 1
                            if not source_quality.get("accepted"):
                                rejection = (
                                    "text_rejected"
                                    if source_quality.get("reason") == "embedded_text"
                                    else "text_unavailable"
                                )
                                diagnostics[rejection] += 1
                                continue
                            results.append(
                                {
                                    "pin_id": pin_id,
                                    "raw_path": str(raw_path),
                                    "original_url": f"{PINTEREST_BASE}{href}",
                                    "original_title": title or alt_text,
                                    "original_description": description[:500],
                                    "board_name": board_name,
                                    "search_query": resolved_query,
                                    "relevance_score": relevance_score,
                                    "source": "pinterest",
                                    "source_hash": source_quality["source_hash"],
                                    "source_quality": source_quality,
                                }
                            )
                            diagnostics["accepted"] = len(results)
                            if len(results) % 10 == 0:
                                print(f"   Downloaded {len(results)} images...")
                        except Exception:
                            diagnostics["download_failed"] += 1
                            continue

                    if len(results) >= count:
                        break
                    if diagnostics["pins_examined"] >= max_candidates:
                        diagnostics["blocked_reason"] = "candidate_limit"
                        break
                    if len(examined_pin_ids) == previous_examined:
                        stagnant_rounds += 1
                    else:
                        stagnant_rounds = 0
                    if stagnant_rounds >= 2:
                        break
                    previous_examined = len(examined_pin_ids)
                    await self.page.mouse.wheel(0, 2800)
                    await asyncio.sleep(1.5)

        print(
            "   Collection diagnostics: "
            f"accepted={diagnostics['accepted']}/{count} "
            f"examined={diagnostics['pins_examined']} "
            f"relevance_rejected={diagnostics['relevance_rejected']} "
            f"text_rejected={diagnostics['text_rejected']} "
            f"text_unavailable={diagnostics['text_unavailable']} "
            f"query_failures={diagnostics['query_failures']}"
        )
        return results

    def _get_accent_color(self, img):
        """Extracts the dominant vibrant color using a more robust sampling."""
        try:
            # Resize and convert to RGB for easier processing
            small_img = img.resize((100, 100)).convert("RGB")
            # Get pixels and filter out extremes
            pixels = list(small_img.getdata())
            vibrant_pixels = []
            for r, g, b in pixels:
                # Check for saturation (vibrancy)
                if max(r, g, b) - min(r, g, b) > 40:  # Saturation threshold
                    # Check for brightness (not too dark, not too light)
                    if 40 < (r + g + b) / 3 < 200:
                        vibrant_pixels.append((r, g, b))

            if vibrant_pixels:
                # Pick the average of the most vibrant ones
                vibrant_pixels.sort(key=lambda p: max(p) - min(p), reverse=True)
                return vibrant_pixels[0]

            return (230, 0, 35)  # Default Pinterest Red
        except:
            return (230, 0, 35)

    def _get_font(self, name, size, weight="Regular"):
        """Class-level font loader with robust fallbacks."""
        font_dir = Path("data/fonts")
        sys_font_dir = Path("C:/Windows/Fonts")

        # 1. Try local data/fonts
        local_path = font_dir / f"{name}-{weight}.ttf"
        if local_path.exists():
            try:
                return ImageFont.truetype(str(local_path), size)
            except:
                pass

        # 2. Try System Fallbacks
        fallbacks = {
            "PlayfairDisplay": ["timesbd.ttf", "georgiab.ttf", "pala.ttf"],
            "Montserrat": ["segoeuib.ttf", "arialbd.ttf", "tahomabd.ttf"],
            "GreatVibes": ["GreatVibes-Regular.ttf"],
        }

        for fallback in fallbacks.get(name, []):
            fb_path = sys_font_dir / fallback
            if fb_path.exists():
                try:
                    return ImageFont.truetype(str(fb_path), size)
                except:
                    pass

        return ImageFont.load_default()

    def _draw_text_fitted(
        self,
        draw,
        text,
        font_name,
        size,
        color,
        target_w,
        max_width,
        start_y,
        max_height=None,
        weight="Bold",
        line_spacing=1.1,
        shadow=False,
        align="center",
    ):
        """Draws text wrapped and scaled to fit the target width AND height perfectly."""

        def get_wrapped_lines(text, font, max_pixel_width):
            lines = []
            words = text.split()
            if not words:
                return []

            current_line = words[0]
            for word in words[1:]:
                test_line = current_line + " " + word
                bbox = draw.textbbox((0, 0), test_line, font=font)
                if (bbox[2] - bbox[0]) <= max_pixel_width:
                    current_line = test_line
                else:
                    lines.append(current_line)
                    current_line = word
            lines.append(current_line)
            return lines

        # Initial font sizing
        current_size = size
        font = self._get_font(font_name, current_size, weight)

        # Dynamic Scaling: Shrink font if lines are too wide OR too tall
        while current_size > 22:  # Lower minimum to handle very long titles
            current_font = self._get_font(font_name, current_size, weight)
            wrapped_lines = get_wrapped_lines(text.upper(), current_font, max_width)

            # Calculate total height
            total_h = 0
            for line in wrapped_lines:
                bbox = draw.textbbox((0, 0), line, font=current_font)
                total_h += (bbox[3] - bbox[1]) * line_spacing

            if not max_height or total_h <= max_height:
                font = current_font
                break

            current_size -= 2

        # Final wrap with the chosen font
        wrapped_lines = get_wrapped_lines(text.upper(), font, max_width)

        # Render lines centered
        curr_y = start_y
        for line in wrapped_lines:
            l_bbox = draw.textbbox((0, 0), line, font=font)
            tw = l_bbox[2] - l_bbox[0]
            th = l_bbox[3] - l_bbox[1]

            if align == "center":
                tx = (target_w - tw) // 2
            else:  # left
                tx = 100

            if shadow:
                # Subtler but visible shadow
                draw.text((tx + 2, curr_y + 2), line, font=font, fill=(0, 0, 0, 180))

            draw.text((tx, curr_y), line, font=font, fill=color)
            curr_y += int(th * line_spacing)

        return curr_y

    def _apply_texture(self, img):
        """Adds a subtle grain texture for a 'tactile' 2026 feel."""
        import numpy as np

        width, height = img.size
        # Finer, more sophisticated grain
        noise = np.random.normal(0, 8, (height, width, 3)).astype(np.uint8)
        noise_img = Image.fromarray(noise).convert("RGBA")

        # Super subtle blend
        return Image.blend(img, noise_img, 0.03)

    def apply_editorial_overlay(
        self, image_path, title_text, hook=None, layout="editorial", brand_name="RecetaDolce"
    ):
        """
        Advanced V4.2 Design Engine — Luxury Pinterest Edition.
        Layouts: editorial, tutorial, minimalist, luxury, split.
        """
        try:
            import random

            if not hook:
                hooks = [
                    "PASO A PASO",
                    "RECETA VIRAL",
                    "SECRETO REVELADO",
                    "EDICIÓN 2026",
                    "CALIDAD PREMIUM",
                    "TENDENCIA VIRAL",
                ]
                hook = random.choice(hooks)

            with Image.open(image_path) as img:
                target_w, target_h = 1000, 1500
                if img.mode != "RGBA":
                    img = img.convert("RGBA")

                # --- 1. Smart Cropping & Padding ---
                if layout == "split":
                    img_h = int(target_h * 0.65)
                    img_w = target_w
                    img_ratio = img.width / img.height
                    target_ratio = img_w / img_h

                    if img_ratio > target_ratio:
                        new_h = img_h
                        new_w = int(new_h * img_ratio)
                        canvas_img = img.resize((new_w, new_h), Image.Resampling.LANCZOS)
                        left = (new_w - img_w) // 2
                        canvas_img = canvas_img.crop((left, 0, left + img_w, img_h))
                    else:
                        new_w = img_w
                        new_h = int(new_w / img_ratio)
                        canvas_img = img.resize((new_w, new_h), Image.Resampling.LANCZOS)
                        top = (new_h - img_h) // 2
                        canvas_img = canvas_img.crop((0, top, img_w, top + img_h))

                    full_canvas = Image.new("RGBA", (target_w, target_h), (252, 248, 242, 255))
                    full_canvas.paste(canvas_img, (0, 0))
                    canvas_img = full_canvas
                else:
                    img_ratio = img.width / img.height
                    target_ratio = target_w / target_h
                    if img_ratio > target_ratio:
                        new_h = target_h
                        new_w = int(new_h * img_ratio)
                        canvas_img = img.resize((new_w, new_h), Image.Resampling.LANCZOS)
                        left = (new_w - target_w) // 2
                        canvas_img = canvas_img.crop((left, 0, left + target_w, target_h))
                    else:
                        new_w = target_w
                        new_h = int(new_w / img_ratio)
                        canvas_img = img.resize((new_w, new_h), Image.Resampling.LANCZOS)
                        top = (new_h - target_h) // 2
                        canvas_img = canvas_img.crop((0, top, target_w, top + target_h))

                # --- 2. Professional Enhancements ---
                canvas_img = ImageEnhance.Color(canvas_img).enhance(1.25)  # More vibrant
                canvas_img = ImageEnhance.Contrast(canvas_img).enhance(1.15)
                canvas_img = self._apply_texture(canvas_img)

                # --- 2.1 Protection Gradient (Hide original pin titles) ---
                overlay = Image.new("RGBA", (target_w, target_h), (0, 0, 0, 0))
                o_draw = ImageDraw.Draw(overlay)
                # Stronger dark gradient at top to cover original text
                for i in range(500):
                    alpha = int((1 - i / 500) * 230)
                    o_draw.line([0, i, target_w, i], fill=(10, 10, 10, alpha))
                canvas_img = Image.alpha_composite(canvas_img, overlay)

                accent_color = self._get_accent_color(img)
                draw = ImageDraw.Draw(canvas_img, "RGBA")

                # --- 3. Font Setup ---
                font_hook = self._get_font("Montserrat", 45, "Bold")
                font_brand = self._get_font("Montserrat", 35, "Regular")
                font_cta = self._get_font("Montserrat", 50, "Bold")
                font_script = self._get_font("GreatVibes", 190, "Regular")
                font_badge = self._get_font("Montserrat", 30, "Bold")

                # --- 4. Layout Implementation ---
                text_color = (255, 255, 255)
                curr_y = 400

                if layout == "editorial":
                    # Glassmorphism Box - Darker and more premium
                    mask = Image.new("L", (target_w, target_h), 0)
                    m_draw = ImageDraw.Draw(mask)
                    # Slightly wider and taller box
                    box_coords = [50, target_h // 2 - 250, target_w - 50, target_h // 2 + 580]
                    m_draw.rounded_rectangle(box_coords, radius=60, fill=255)
                    blurred = canvas_img.filter(ImageFilter.GaussianBlur(radius=50))
                    canvas_img.paste(blurred, (0, 0), mask=mask)

                    overlay = Image.new("RGBA", (target_w, target_h), (0, 0, 0, 0))
                    o_draw = ImageDraw.Draw(overlay)
                    # Glass effect with better contrast
                    o_draw.rounded_rectangle(
                        box_coords, radius=60, fill=(20, 20, 20, 100), outline=(255, 255, 255, 180), width=5
                    )
                    canvas_img = Image.alpha_composite(canvas_img, overlay)
                    draw = ImageDraw.Draw(canvas_img, "RGBA")
                    curr_y = target_h // 2 - 160

                elif layout == "luxury":
                    # Bottom Dark Gradient & Elegant Script Accent
                    overlay = Image.new("RGBA", (target_w, target_h), (0, 0, 0, 0))
                    o_draw = ImageDraw.Draw(overlay)
                    # Very deep gradient at bottom
                    for i in range(target_h - 1100, target_h):
                        alpha = int(((i - (target_h - 1100)) / 1100) * 255)
                        o_draw.line([0, i, target_w, i], fill=(5, 5, 5, alpha))
                    canvas_img = Image.alpha_composite(canvas_img, overlay)
                    draw = ImageDraw.Draw(canvas_img, "RGBA")

                    # Script Brand Signature with outer glow
                    brand_script = brand_name
                    sw_bbox = draw.textbbox((0, 0), brand_script, font=font_script)
                    sww = sw_bbox[2] - sw_bbox[0]
                    tx, ty = (target_w - sww) // 2, target_h - 920
                    # Fake glow
                    draw.text((tx + 2, ty + 2), brand_script, font=font_script, fill=(0, 0, 0, 100))
                    draw.text((tx, ty), brand_script, font=font_script, fill=accent_color)
                    curr_y = target_h - 700

                elif layout == "tutorial":
                    # Solid Top Banner
                    draw.rectangle([0, 0, target_w, 280], fill=(10, 10, 10, 255))
                    draw.text((100, 110), hook, font=font_hook, fill=accent_color)

                    # Larger Text box at bottom with shadow
                    box_coords = [40, target_h - 680, target_w - 40, target_h - 60]
                    draw.rounded_rectangle(
                        [c + 5 for c in box_coords], radius=50, fill=(0, 0, 0, 80)
                    )  # Shadow
                    draw.rounded_rectangle(box_coords, radius=50, fill=(255, 255, 255, 255))
                    draw = ImageDraw.Draw(canvas_img, "RGBA")
                    curr_y = target_h - 630
                    text_color = (15, 15, 15)

                elif layout == "minimalist":
                    # Clean top text with deep shadow for readability
                    overlay = Image.new("RGBA", (target_w, target_h), (0, 0, 0, 0))
                    o_draw = ImageDraw.Draw(overlay)
                    for i in range(900):
                        alpha = int((1 - i / 900) * 240)
                        o_draw.line([0, i, target_w, i], fill=(0, 0, 0, alpha))
                    canvas_img = Image.alpha_composite(canvas_img, overlay)
                    draw = ImageDraw.Draw(canvas_img, "RGBA")
                    curr_y = 180

                elif layout == "split":
                    # Sandwich/Stripe Layout
                    strip_h = 560
                    strip_y = (target_h - strip_h) // 2 + 180

                    draw.rectangle(
                        [0, strip_y, target_w, target_h],
                        fill=(accent_color[0], accent_color[1], accent_color[2], 255),
                    )

                    brand_script = brand_name
                    sw_bbox = draw.textbbox((0, 0), brand_script, font=font_script)
                    sww = sw_bbox[2] - sw_bbox[0]
                    draw.text(
                        ((target_w - sww) // 2, strip_y - 160),
                        brand_script,
                        font=font_script,
                        fill=(255, 255, 255, 255),
                    )

                    curr_y = strip_y + 70
                    text_color = (255, 255, 255)

                # --- 5. Title Rendering (Smart Fitting) ---
                max_h_map = {
                    "editorial": 450,
                    "luxury": 450,
                    "tutorial": 400,
                    "minimalist": 450,
                    "split": 350,
                }

                curr_y = self._draw_text_fitted(
                    draw,
                    title_text,
                    "PlayfairDisplay",
                    130,
                    text_color,
                    target_w,
                    840 if layout in ["editorial", "tutorial"] else 920,
                    curr_y,
                    max_height=max_h_map.get(layout, 400),
                    shadow=(text_color == (255, 255, 255)),
                )

                # --- 6. Aesthetic Badges & Social Proof ---
                def draw_stars(d, x_center, y, count=None, size=45):
                    if not count:
                        count = random.choice([4.8, 4.9, 5.0])
                    full_stars = round(count)
                    star_w = size + 12
                    start_x = x_center - (star_w * 5) // 2
                    for i in range(5):
                        fill = (255, 210, 0) if i < full_stars else (200, 200, 200)
                        center_x = start_x + i * star_w + size // 2
                        center_y = y + size // 2
                        points = []
                        for point_index in range(10):
                            radius = size / 2 if point_index % 2 == 0 else size / 4.5
                            angle = -math.pi / 2 + point_index * math.pi / 5
                            points.append(
                                (
                                    center_x + radius * math.cos(angle),
                                    center_y + radius * math.sin(angle),
                                )
                            )
                        d.polygon(points, fill=fill)
                        continue
                        try:
                            d.text(
                                (start_x + i * star_w, y),
                                "★",
                                font=self._get_font("Lora", size, "Bold"),
                                fill=fill,
                            )
                        except:
                            pass

                    # Add numeric rating
                    font_rating = self._get_font("Montserrat", 32, "Bold")
                    d.text(
                        (start_x + 5 * star_w + 10, y + 5),
                        f"{count}/5",
                        font=font_rating,
                        fill=(255, 255, 255) if layout != "tutorial" else (50, 50, 50),
                    )

                draw_stars(draw, target_w // 2, curr_y + 25)
                curr_y += 90

                # Badge moved to top-right corner safely
                badge_text = f"{random.randint(15, 45)} MIN"
                draw.rounded_rectangle([target_w - 240, 60, target_w - 60, 120], radius=30, fill=accent_color)
                draw.text((target_w - 215, 75), badge_text, font=font_badge, fill="white")

                # --- 7. Call to Action Button REMOVED ---
                # Buttons removed per user request to clean up designs

                # --- 8. Branding ---

                brand_text = f"{brand_name.upper().removesuffix('.COM')}.COM"
                b_bbox = draw.textbbox((0, 0), brand_text, font=font_brand)
                brand_width = b_bbox[2] - b_bbox[0]
                brand_height = b_bbox[3] - b_bbox[1]
                footer_height = max(90, brand_height + 42)
                draw.rectangle(
                    [0, target_h - footer_height, target_w, target_h],
                    fill=(10, 10, 10, 225),
                )
                draw.text(
                    (
                        (target_w - brand_width) // 2,
                        target_h - footer_height + (footer_height - brand_height) // 2 - b_bbox[1],
                    ),
                    brand_text,
                    font=font_brand,
                    fill=(255, 255, 255, 255),
                )

                # --- 9. Final Save & SEO ---
                clean_title = re.sub(r"[^a-z0-9]+", "-", title_text.lower()).strip("-")
                filename = f"remastered_v4_{layout}_{clean_title}_{Path(image_path).name}"
                save_path = REMASTER_DIR / filename
                if save_path.suffix.lower() not in [".jpg", ".jpeg"]:
                    save_path = save_path.with_suffix(".jpg")

                canvas_img.convert("RGB").save(save_path, "JPEG", quality=95, optimize=True)

                inject_seo_metadata(
                    save_path,
                    f"{title_text} | {brand_name} Luxury Edition",
                    f"Aprende a preparar {title_text}. {hook}. Diseño exclusivo 2026.",
                    f"{title_text}, receta fit, lujo, gourmet, pinterest 2026",
                )
                return save_path

        except Exception as e:
            print(f"   [!] Remaster error: {e}")
            return None


def _fallback_slug(keyword: str, index: int) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", _normalize_text(keyword)).strip("-") or "recipe"
    return f"{slug}-native-remaster-source-{index:02d}"


def _augment_native_sources(keyword: str, sources: list[dict], target_count: int) -> list[dict]:
    """Expand a small set of native food photos into controlled source variants."""
    if not sources or len(sources) >= target_count:
        return sources[:target_count]

    generated = list(sources)
    variant_index = 1
    while len(generated) < target_count:
        base = sources[(len(generated) - len(sources)) % len(sources)]
        source_path = Path(base["raw_path"])
        try:
            with Image.open(source_path) as original:
                image = original.convert("RGB")
                width, height = image.size
                zoom = 1.04 + (variant_index % 5) * 0.025
                crop_width = max(1, int(width / zoom))
                crop_height = max(1, int(height / zoom))
                x_room = max(0, width - crop_width)
                y_room = max(0, height - crop_height)
                x_offset = int(x_room * ((variant_index % 4) / 3))
                y_offset = int(y_room * (((variant_index * 3) % 4) / 3))
                image = image.crop(
                    (
                        x_offset,
                        y_offset,
                        x_offset + crop_width,
                        y_offset + crop_height,
                    )
                ).resize((width, height), Image.Resampling.LANCZOS)
                image = ImageEnhance.Contrast(image).enhance(0.96 + (variant_index % 4) * 0.025)
                image = ImageEnhance.Color(image).enhance(0.97 + (variant_index % 3) * 0.03)

                index = len(generated) + 1
                slug = _fallback_slug(keyword, index)
                output_path = source_path.with_name(f"{slug}-hero.jpg")
                image.save(output_path, "JPEG", quality=94, optimize=True)

            generated.append(
                {
                    "pin_id": f"native-{index:02d}",
                    "raw_path": str(output_path),
                    "original_url": "",
                    "original_title": f"Native generated variant for {keyword}",
                    "relevance_score": 99,
                    "source": "native_augmented",
                    "provider": base.get("provider", "native"),
                }
            )
            variant_index += 1
        except Exception as exc:
            print(f"   [!] Native source augmentation failed: {exc}")
            break
    return generated


def _native_source_attempt_budget(count: int) -> int:
    """Bound Codex retries while guaranteeing at least one attempt per source."""

    requested = max(0, int(count))
    if requested == 0:
        return 0

    default_budget = requested * 3
    try:
        configured = int(os.environ.get("RANKSTEIN_NATIVE_SOURCE_MAX_ATTEMPTS", str(default_budget)))
    except (TypeError, ValueError):
        configured = default_budget

    # An operator may tune the budget, but cannot accidentally reinstate a
    # source cap below the requested count or create an unbounded retry loop.
    return max(requested, min(configured, requested * 5))


def _generate_native_fallback_sources(keyword: str, count: int) -> list[dict]:
    """Operator-only image source utility; production remaster runs never call it."""

    if count <= 0:
        return []
    try:
        from backend.scripts.hero_image_pipeline import get_hero_image
        from rankstein.prompts import build_recipe_image_prompt
    except Exception as exc:
        print(f"   [!] Native fallback unavailable: {exc}")
        return []

    attempt_budget = _native_source_attempt_budget(count)
    generated: list[dict] = []
    attempt = 0
    while len(generated) < count and attempt < attempt_budget:
        attempt += 1
        source_index = len(generated) + 1
        slug = _fallback_slug(keyword, attempt)
        prompt = build_recipe_image_prompt(
            keyword,
            asset_type="pinterest_pin",
            overlay_concept="guardar receta",
        )
        try:
            result = get_hero_image(
                keyword=keyword,
                slug=slug,
                image_prompt=(
                    f"{prompt} Native source {source_index} of {count}; "
                    f"generation attempt {attempt}. Use a unique camera angle, crop, and plating."
                ),
            )
        except Exception as exc:
            print(f"   [!] Codex native source attempt {attempt}/{attempt_budget} failed: {exc}")
            continue

        if isinstance(result, dict) and result.get("success") and result.get("output_path"):
            generated.append(
                {
                    "pin_id": f"native-{source_index:02d}",
                    "raw_path": result["output_path"],
                    "original_url": "",
                    "original_title": f"Native fallback image for {keyword}",
                    "relevance_score": 99,
                    "source": "native_fallback",
                    "provider": result.get("source", result.get("provider", "native")),
                    "generation_attempt": attempt,
                }
            )
        else:
            error = result.get("error", "unknown error") if isinstance(result, dict) else "no result"
            print(
                f"   [!] Codex native source attempt {attempt}/{attempt_budget} "
                f"did not produce an image: {error}"
            )

    if len(generated) < count:
        print(
            f"   [!] Codex native source generation exhausted its retry budget: "
            f"{len(generated)}/{count} images after {attempt} attempts"
        )
    return generated[:count]


def validate_production_asset_set(assets: list[dict], *, target_count: int) -> dict:
    """Validate the exact scraped-only set required before queue mutation.

    Production accepts exactly fifteen unique Pinterest pins and exactly two
    deterministic variants per source.  Generated/native sources, incomplete
    pairs, duplicate pin ids, and non-30 targets all fail closed.
    """

    pair_assets: dict[str, list[dict]] = {}
    for asset in assets:
        pair_id = str(asset.get("pair_id") or "").strip()
        if pair_id:
            pair_assets.setdefault(pair_id, []).append(asset)

    pinterest_source_count = 0
    native_source_count = 0
    original_pin_ids: set[str] = set()
    errors: list[str] = []

    if int(target_count) != PRODUCTION_ASSET_TARGET:
        errors.append(f"production target must be {PRODUCTION_ASSET_TARGET} assets")
    if len(assets) != PRODUCTION_ASSET_TARGET:
        errors.append(f"expected {PRODUCTION_ASSET_TARGET} assets, received {len(assets)}")
    if len(pair_assets) != PRODUCTION_SOURCE_TARGET:
        errors.append(f"expected {PRODUCTION_SOURCE_TARGET} source pairs, received {len(pair_assets)}")

    for pair_id, pair in sorted(pair_assets.items()):
        sources = {str(item.get("source") or "").strip().lower() for item in pair}
        if sources == {"pinterest"}:
            pinterest_source_count += 1
        else:
            native_source_count += 1
            errors.append(f"{pair_id} is not backed exclusively by a Pinterest source")

        variants = {str(item.get("variant") or "").strip() for item in pair}
        if len(pair) != 2 or variants != PRODUCTION_VARIANTS:
            errors.append(f"{pair_id} must contain exactly viral_visual and recipe_card")

        pin_ids = {str(item.get("original_pin_id") or "").strip() for item in pair}
        pin_ids.discard("")
        if len(pin_ids) != 1:
            errors.append(f"{pair_id} must reference one verified Pinterest pin id")
        else:
            original_pin_id = next(iter(pin_ids))
            if original_pin_id in original_pin_ids:
                errors.append(f"Pinterest source {original_pin_id} is duplicated across pairs")
            original_pin_ids.add(original_pin_id)

        for item in pair:
            remastered_path = str(item.get("remastered_path") or "").strip()
            path = Path(remastered_path) if remastered_path else None
            if (
                path is None
                or not path.is_file()
                or path.suffix.lower() not in {".jpg", ".jpeg", ".png", ".webp"}
            ):
                errors.append(f"{pair_id} has a missing or invalid remastered asset file")
                break

    if pinterest_source_count != PRODUCTION_SOURCE_TARGET:
        errors.append(
            f"production requires {PRODUCTION_SOURCE_TARGET} unique Pinterest sources; "
            f"received {pinterest_source_count}"
        )
    if len(original_pin_ids) != PRODUCTION_SOURCE_TARGET:
        errors.append(
            f"production requires {PRODUCTION_SOURCE_TARGET} unique Pinterest pin ids; "
            f"received {len(original_pin_ids)}"
        )

    return {
        "success": not errors,
        "error": "; ".join(dict.fromkeys(errors)),
        "target_count": int(target_count),
        "asset_count": len(assets),
        "pair_count": len(pair_assets),
        "pinterest_source_count": pinterest_source_count,
        "native_source_count": native_source_count,
        "unique_pin_id_count": len(original_pin_ids),
    }


def enqueue_validated_production_assets(
    assets: list[dict],
    *,
    target_count: int,
    enqueue_callable,
    **enqueue_kwargs,
) -> dict:
    """Invoke the queue mutator only for an exact scraped-only production set."""

    validation = validate_production_asset_set(assets, target_count=target_count)
    if not validation["success"]:
        return {
            "success": False,
            "error": f"Queue blocked by scraped-only asset contract: {validation['error']}",
            "images": 0,
            "jobs_enqueued": 0,
            "details": [],
            "validation": validation,
        }

    result = enqueue_callable(
        limit=target_count,
        image_paths=[item["remastered_path"] for item in assets],
        asset_metadata=assets,
        **enqueue_kwargs,
    )
    if not isinstance(result, dict):
        return {
            "success": False,
            "error": "Pinterest queue mutator returned an invalid response",
            "images": 0,
            "jobs_enqueued": 0,
            "details": [],
            "validation": validation,
        }
    result.setdefault("validation", validation)
    return result


def _campaign_report_path(
    slug: str,
    *,
    domain_handle: str = "",
    pipeline_run_id: str = "",
) -> Path:
    safe_slug = re.sub(r"[^a-z0-9]+", "-", _normalize_text(slug)).strip("-") or "article"
    safe_domain = re.sub(r"[^a-z0-9]+", "-", _normalize_text(domain_handle)).strip("-") or "domain"
    safe_run = re.sub(r"[^a-z0-9]+", "-", _normalize_text(pipeline_run_id)).strip("-") or "manual"
    stamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S_%f")
    return CAMPAIGN_REPORT_DIR / (f"{safe_slug}_remaster_{safe_domain}_{safe_run}_{stamp}.json")


def write_article_remaster_report(
    *,
    keyword: str,
    title: str,
    slug: str,
    domain_handle: str,
    domain_url: str,
    target_count: int,
    assets: list[dict],
    enqueue_result: dict | None = None,
    scrape_brief: dict | None = None,
    pipeline_run_id: str = "",
) -> dict:
    generated_count = len(assets)
    pair_ids = {str(item.get("pair_id", "")) for item in assets if item.get("pair_id")}
    source_types_by_pair = {
        str(item.get("pair_id")): item.get("source", "pinterest") for item in assets if item.get("pair_id")
    }
    source_target = max(1, math.ceil(target_count / 2))
    enqueue_success = bool(enqueue_result.get("success")) if enqueue_result is not None else None
    production_validation = validate_production_asset_set(assets, target_count=target_count)
    generated_contract_success = (
        production_validation["success"]
        if target_count == PRODUCTION_ASSET_TARGET
        else generated_count >= target_count
    )
    report = {
        "success": generated_contract_success and (enqueue_success is not False),
        "completed_at": datetime.now(UTC).isoformat(),
        "campaign_type": "article_remaster_pairs",
        "variant_contract": {
            "variants_per_source": 2,
            "variants": ["viral_visual", "recipe_card"],
            "description": "One image-led pin and one ingredients/preparation card per accepted source",
        },
        "keyword": keyword,
        "title": title,
        "slug": slug,
        "domain_handle": domain_handle,
        "domain_url": domain_url,
        "pipeline_run_id": pipeline_run_id,
        "target_count": target_count,
        "source_target": source_target,
        "accepted_source_count": len(pair_ids),
        "pair_count": len(pair_ids),
        "generated_count": generated_count,
        "missing_count": max(0, target_count - generated_count),
        "source_counts": {
            "pinterest": sum(1 for source in source_types_by_pair.values() if source == "pinterest"),
            "native": sum(1 for source in source_types_by_pair.values() if source != "pinterest"),
        },
        "source_contract": {
            "scraped_only": True,
            "required_pinterest_sources": PRODUCTION_SOURCE_TARGET,
            "native_fill_allowed": False,
        },
        "production_validation": production_validation,
        "assets": assets,
        "enqueue": enqueue_result,
        "scrape_brief": scrape_brief or {},
    }
    path = _campaign_report_path(
        slug or title or keyword,
        domain_handle=domain_handle,
        pipeline_run_id=pipeline_run_id,
    )
    path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    report["report_path"] = str(path)
    print(f"CAMPAIGN_REPORT: {path}")
    print(f"CAMPAIGN_STATUS: success={report['success']} generated={generated_count}/{target_count}")
    return report


async def _collect_campaign_sources(
    studio,
    keyword: str,
    *,
    source_target: int,
    domain_handle: str,
    pipeline_run_id: str,
    download_dir: Path,
    collection_kwargs: dict,
) -> list[dict]:
    """Bound preflight/start/collection/recheck/stop to at most 680 seconds.

    Phase upper bounds are start 60s, collection plus exact source rechecks
    600s, and stop 20s. The total deadline includes exclusion reads and reserves
    cleanup time. Timed-out cleanup is failed intake, not success. No browser
    other than this studio's own context is cleaned up here.
    """
    total = _bounded_seconds(
        "RANKSTEIN_REMASTER_INTAKE_TIMEOUT_SECONDS",
        SOURCE_INTAKE_TIMEOUT_SECONDS,
        SOURCE_INTAKE_TIMEOUT_SECONDS,
    )
    deadline = time.monotonic() + total
    studio.last_collection_diagnostics = {"phase": "held_source_preflight", "accepted": 0}
    finished = asyncio.Event()
    heartbeat = asyncio.create_task(_source_progress_heartbeat(studio, finished, deadline=deadline))
    collected = []
    failure = ""

    def phase_budget(maximum: float, *, reserve_cleanup: bool = True) -> float:
        remaining = deadline - time.monotonic()
        if reserve_cleanup:
            remaining -= BROWSER_STOP_TIMEOUT_SECONDS
        if remaining <= 0:
            raise TimeoutError
        return min(maximum, remaining)

    try:
        preflight_budget = phase_budget(4.0)
        excluded = await asyncio.wait_for(
            asyncio.to_thread(_held_campaign_source_pin_ids, domain_handle, pipeline_run_id),
            timeout=preflight_budget,
        )
        studio.last_collection_diagnostics.update(
            phase="starting_browser", excluded_source_count=len(excluded)
        )
        start_budget = phase_budget(BROWSER_START_TIMEOUT_SECONDS)
        await asyncio.wait_for(studio.start(), timeout=start_budget)
        studio.last_collection_diagnostics["phase"] = "collecting"
        async with asyncio.timeout(phase_budget(COLLECTION_TIMEOUT_SECONDS)):
            collected = await studio.collect_and_download(
                keyword,
                count=source_target,
                excluded_pin_ids=excluded,
                download_dir=download_dir,
                progress_enabled=False,
                **collection_kwargs,
            )
            # Enforce exclusions independently if a legacy collector ignores
            # the new parameter. Only fresh source pairs can replace held work.
            collected = [item for item in collected if str(item.get("pin_id") or "") not in excluded]
            # Recheck exact selected files even for legacy/mock collectors.
            if len(collected) >= source_target:
                studio.last_collection_diagnostics["phase"] = "validating_source_quality"
                for item in collected[:source_target]:
                    studio.last_collection_diagnostics["ocr_in_progress"] = 1
                    quality = await asyncio.to_thread(assess_source_image, item.get("raw_path", ""))
                    studio.last_collection_diagnostics["ocr_in_progress"] = 0
                    item["source_quality"] = quality
                    item["source_hash"] = quality.get("source_hash", "")
    except TimeoutError:
        failure = f"{studio.last_collection_diagnostics.get('phase', 'source_intake')}_timeout"
    except asyncio.CancelledError:
        failure = "source_intake_cancelled"
        raise
    except Exception as exc:
        failure = "remaster_profile_busy" if str(exc) == "remaster_profile_busy" else "source_intake_failed"
        studio.last_collection_diagnostics["error_type"] = type(exc).__name__
    finally:
        studio.last_collection_diagnostics.update(phase="stopping_browser", ocr_in_progress=0)
        try:
            stop_budget = phase_budget(BROWSER_STOP_TIMEOUT_SECONDS, reserve_cleanup=False)
            await asyncio.wait_for(studio.stop(), timeout=stop_budget)
        except asyncio.CancelledError:
            failure = "source_intake_cancelled"
            raise
        except Exception as exc:
            studio.last_collection_diagnostics["cleanup_error_type"] = type(exc).__name__
            failure = failure or "browser_cleanup_failed"
        finally:
            studio.last_collection_diagnostics["phase"] = (
                "source_intake_complete" if not failure else "incomplete"
            )
            if failure:
                studio.last_collection_diagnostics["blocked_reason"] = failure
                collected = []
            finished.set()
            heartbeat.cancel()
            with suppress(asyncio.CancelledError):
                await heartbeat
            _emit_source_progress(studio, deadline=deadline)
    return collected


async def run_remasterer(
    keyword,
    article_title,
    brand_name="RecetaDolce",
    session_name: str | None = None,
    pins_per_keyword: int = DEFAULT_PINS_PER_KEYWORD,
    search_query: str = "",
    search_queries: str | list[str] | tuple[str, ...] | set[str] | None = None,
    core_terms: str | list[str] | tuple[str, ...] | set[str] | None = None,
    min_core_matches: int | None = None,
    expected_terms: str | list[str] | tuple[str, ...] | set[str] | None = None,
    blocked_terms: str | list[str] | tuple[str, ...] | set[str] | None = None,
    pipeline_run_id: str = "",
    domain_handle: str = "",
    recipe_ingredients: str | list[str] | tuple[str, ...] | set[str] | None = None,
    recipe_steps: str | list[str] | tuple[str, ...] | set[str] | None = None,
    tip_text: str = "",
):
    target_count = _paired_output_target(pins_per_keyword)
    source_target = target_count // 2
    session_name = _resolve_session_name(session_name, domain_handle=domain_handle)
    ingredients = _value_list(recipe_ingredients)
    steps = _value_list(recipe_steps)
    if not ingredients or not steps:
        message = "Paired remastering requires real article ingredients and preparation steps"
        print(f"INCOMPLETE: {message}")
        _pipeline_event(
            pipeline_run_id,
            "remaster",
            "failed",
            message,
            target=target_count,
            pair_target=source_target,
        )
        _pipeline_status(pipeline_run_id, "attention")
        return []

    remasterer = PinRemasterer(headless=True, session_name=session_name)
    raw_output_dir, final_output_dir = _isolated_remaster_directories(domain_handle, pipeline_run_id)

    print("\n--- RankStein Remasterer V5 Paired Studio Active ---")
    print(f"Targeting: {keyword} | Title: {article_title} | Brand: {brand_name} | Session: {session_name}")
    _pipeline_event(
        pipeline_run_id,
        "pinterest_siphon",
        "running",
        "Searching Pinterest with the generated dish brief",
        target=source_target,
        output_target=target_count,
        search_query=search_query,
    )
    collected = await _collect_campaign_sources(
        remasterer,
        keyword,
        source_target=source_target,
        domain_handle=domain_handle,
        pipeline_run_id=pipeline_run_id,
        download_dir=raw_output_dir,
        collection_kwargs={
            "search_query": search_query,
            "search_queries": search_queries,
            "core_terms": core_terms,
            "min_core_matches": min_core_matches,
            "expected_terms": expected_terms,
            "blocked_terms": blocked_terms,
        },
    )
    scraped_count = len(collected)
    diagnostics = getattr(remasterer, "last_collection_diagnostics", {})
    source_intake_complete = scraped_count >= source_target
    _pipeline_event(
        pipeline_run_id,
        "pinterest_siphon",
        "complete" if source_intake_complete else "warning",
        f"Accepted {scraped_count} relevant Pinterest source images",
        accepted=scraped_count,
        target=source_target,
        output_target=target_count,
        diagnostics=diagnostics,
    )
    if not source_intake_complete:
        print(
            f"INCOMPLETE: scrape produced {scraped_count}/{source_target} unique relevant "
            "Pinterest sources; no variants were created and native fill is disabled"
        )
        _pipeline_event(
            pipeline_run_id,
            "remaster",
            "warning",
            "Scraped-only source contract incomplete; no variants created",
            generated=0,
            target=target_count,
            accepted_sources=scraped_count,
            source_target=source_target,
            missing_sources=max(0, source_target - scraped_count),
            diagnostics=diagnostics,
        )
        _pipeline_status(pipeline_run_id, "attention")
        return []

    collected = collected[:source_target]
    source_pin_ids = [str(item.get("pin_id") or "").strip() for item in collected]
    invalid_source_set = (
        any(str(item.get("source") or "").strip().lower() != "pinterest" for item in collected)
        or any(not pin_id for pin_id in source_pin_ids)
        or len(set(source_pin_ids)) != source_target
    )
    if invalid_source_set:
        print(
            "INCOMPLETE: source intake did not contain exactly 15 unique Pinterest pins; "
            "no variants were created"
        )
        _pipeline_event(
            pipeline_run_id,
            "remaster",
            "failed",
            "Pinterest source identity contract failed; no variants created",
            generated=0,
            target=target_count,
            accepted_sources=scraped_count,
            unique_pin_ids=len(set(source_pin_ids)),
        )
        _pipeline_status(pipeline_run_id, "attention")
        return []

    # Bounded intake rechecked the exact selected files independently of
    # collector metadata, before browser cleanup and either composition.
    blocked_sources = []
    for item in collected:
        source_quality = item.get("source_quality") or {}
        if not source_quality.get("accepted"):
            blocked_sources.append(
                {"pin_id": item["pin_id"], "reason": source_quality.get("reason", "ocr_unavailable")}
            )
    if blocked_sources:
        print(
            f"INCOMPLETE: {len(blocked_sources)}/{source_target} source images failed "
            "the text-free quality gate; no variants were created"
        )
        _pipeline_event(
            pipeline_run_id,
            "remaster",
            "failed",
            "Source-image text quality gate failed; no variants created",
            generated=0,
            target=target_count,
            source_target=source_target,
            blocked_sources=blocked_sources,
        )
        _pipeline_status(pipeline_run_id, "attention")
        return []

    final_assets = []
    failed_pairs = []
    _pipeline_event(
        pipeline_run_id,
        "remaster",
        "running",
        f"Generating 0 of {target_count} pins as {source_target} source pairs",
        generated=0,
        target=target_count,
        pair_target=source_target,
        variants=["viral_visual", "recipe_card"],
    )

    for i, item in enumerate(collected):
        pair_id = f"source-{i + 1:02d}"
        print(f"   [{i + 1}/{len(collected)}] Creating pair {pair_id}: visual + recipe card...")
        visual = create_viral_visual_pin(
            source_path=item["raw_path"],
            title=article_title,
            domain_handle=domain_handle,
            pair_id=pair_id,
            output_dir=final_output_dir,
        )
        recipe_card = create_recipe_card_pin(
            source_path=item["raw_path"],
            title=article_title,
            ingredients=ingredients,
            steps=steps,
            tip_text=tip_text,
            domain_handle=domain_handle,
            pair_id=pair_id,
            output_dir=final_output_dir,
        )
        pair_results = (visual, recipe_card)
        if all(result.get("success") for result in pair_results):
            for result in pair_results:
                final_assets.append(
                    {
                        "original_pin_id": item["pin_id"],
                        "original_url": item.get("original_url", ""),
                        "source_path": item.get("raw_path", ""),
                        "source_hash": item["source_hash"],
                        "source_quality": item["source_quality"],
                        "remastered_path": str(result["output_path"]),
                        "source": item.get("source", "pinterest"),
                        "source_batch": (
                            "scrape" if item.get("source", "pinterest") == "pinterest" else "native"
                        ),
                        "relevance_score": item.get("relevance_score", 0),
                        "pair_id": pair_id,
                        "source_index": i + 1,
                        "variant": result["variant"],
                        "variant_label": result["variant_label"],
                        "domain_handle": domain_handle,
                        "width": result.get("width", 1000),
                        "height": result.get("height", 1500),
                        "status": "complete",
                    }
                )
        else:
            errors = {
                result.get("variant", "unknown"): result.get("error", "unknown failure")
                for result in pair_results
                if not result.get("success")
            }
            failed_pairs.append({"pair_id": pair_id, "errors": errors})
            for result in pair_results:
                if result.get("success") and result.get("output_path"):
                    try:
                        Path(result["output_path"]).unlink(missing_ok=True)
                    except OSError:
                        pass
        if (i + 1) == len(collected) or (i + 1) % 5 == 0:
            _pipeline_event(
                pipeline_run_id,
                "remaster",
                "running",
                f"Generated {len(final_assets)} of {target_count} remastered pins",
                generated=len(final_assets),
                target=target_count,
                pairs_complete=len(final_assets) // 2,
                pairs_failed=len(failed_pairs),
            )

    if len(final_assets) < target_count:
        print(f"\nINCOMPLETE: {len(final_assets)}/{target_count} luxury pins generated in {REMASTER_DIR}")
        _pipeline_event(
            pipeline_run_id,
            "remaster",
            "warning",
            f"Generated {len(final_assets)} of {target_count} remastered pins",
            generated=len(final_assets),
            target=target_count,
            pairs_complete=len(final_assets) // 2,
            pairs_failed=failed_pairs[:10],
        )
    else:
        print(f"\nCOMPLETED: {len(final_assets)} luxury pins generated in {REMASTER_DIR}")
        _pipeline_event(
            pipeline_run_id,
            "remaster",
            "complete",
            f"Generated all {len(final_assets)} remastered pins",
            generated=len(final_assets),
            target=target_count,
            pairs_complete=len(final_assets) // 2,
        )
    print(
        f"   Source intake: scraped={scraped_count} native=0 pairs={len(final_assets) // 2}/{source_target}"
    )
    return final_assets


async def run_all_domains(
    limit: int = 0, pins_per_keyword: int = DEFAULT_PINS_PER_KEYWORD, enqueue: bool = True
):
    """Siphon trending pins for ALL domains' Live keywords, remaster, and enqueue."""
    import random
    import subprocess
    import sys as _sys
    from pathlib import Path as _Path

    _project_root = _Path(__file__).parent.parent.parent
    _sys.path.insert(0, str(_project_root))

    from rankstein.domain import get_registry, reload_registry
    from rankstein.prompts import build_recipe_image_scrape_brief

    reload_registry()
    registry = get_registry()

    # Gather Live keywords from all domains
    keywords = []
    seen = set()
    for domain in registry.all():
        kf = domain.keywords_file
        if not kf or not kf.exists():
            continue
        brand = (
            getattr(domain, "brand_name_short", "")
            or getattr(domain, "brand_name", "")
            or domain.handle.replace("-", " ").title()
        )
        for line in kf.read_text(encoding="utf-8").splitlines():
            if "| Live |" not in line or not line.startswith("|"):
                continue
            parts = [p.strip() for p in line.split("|") if p.strip()]
            if len(parts) < 2 or parts[0] in ("Keyword", "---"):
                continue
            kw = parts[0]
            if len(kw) < 6 or kw in seen:
                continue
            seen.add(kw)
            category = parts[1] if len(parts) > 1 else ""
            scrape_brief = build_recipe_image_scrape_brief(kw, domain=domain, category=category)
            keywords.append(
                {
                    "keyword": kw,
                    "brand": brand,
                    "domain": domain.handle,
                    "scrape_brief": scrape_brief,
                }
            )

    random.shuffle(keywords)
    if limit:
        keywords = keywords[:limit]

    print(f"\n=== SOCIAL SIPHON — {len(keywords)} keywords across all domains ===\n")

    total = 0
    for i, item in enumerate(keywords, 1):
        kw = item["keyword"]
        brand = item["brand"]
        scrape_brief = item.get("scrape_brief", {})
        print(f"[{i}/{len(keywords)}] Siphoning: {kw} (brand={brand})")

        try:
            assets = await run_remasterer(
                kw,
                kw.title(),
                brand_name=brand,
                session_name=f"siphon_{item['domain']}",
                pins_per_keyword=pins_per_keyword,
                search_query=scrape_brief.get("search_query", ""),
                search_queries=scrape_brief.get("search_queries", []),
                core_terms=scrape_brief.get("core_terms", []),
                min_core_matches=scrape_brief.get("min_core_matches", 1),
                expected_terms=scrape_brief.get("expected_terms", []),
                blocked_terms=scrape_brief.get("blocked_terms", []),
                domain_handle=item["domain"],
            )
            total += len(assets)
        except Exception as e:
            print(f"  [!] Failed: {e}")

        # Auto-enqueue every 5 keywords
        if enqueue and i % 5 == 0 and total > 0:
            print("  Enqueueing generated pins...")
            try:
                subprocess.run(
                    [_sys.executable, str(_project_root / "run_autonomous.py"), "enqueue-folder"],
                    cwd=str(_project_root),
                    capture_output=True,
                    timeout=60,
                    env={**__import__("os").environ, "GOOGLE_API_KEY": "", "GEMINI_API_KEY": ""},
                )
            except Exception:
                pass

        await asyncio.sleep(random.uniform(5, 15))

    # Final enqueue
    if enqueue and total > 0:
        print("Final enqueue...")
        try:
            subprocess.run(
                [_sys.executable, str(_project_root / "run_autonomous.py"), "enqueue-folder"],
                cwd=str(_project_root),
                capture_output=True,
                timeout=60,
                env={**__import__("os").environ, "GOOGLE_API_KEY": "", "GEMINI_API_KEY": ""},
            )
        except Exception:
            pass

    pin_count = len(list(REMASTER_DIR.glob("*.jpg")) + list(REMASTER_DIR.glob("*.png")))
    print(f"\n=== SIPHON COMPLETE — Generated: {total} pins | Total in folder: {pin_count} ===\n")
    return total


if __name__ == "__main__":
    import argparse
    import time

    parser = argparse.ArgumentParser(description="RankStein Remasterer — Social Siphon Engine")
    parser.add_argument(
        "keyword", nargs="?", default="", help="Single keyword to siphon (ignored with --all-domains)"
    )
    parser.add_argument("title", nargs="?", default="", help="Title text for overlay")
    parser.add_argument("--all-domains", action="store_true", help="Siphon for ALL domains' Live keywords")
    parser.add_argument("--continuous", action="store_true", help="Run continuously (10 min between cycles)")
    parser.add_argument("--limit", type=int, default=0, help="Max keywords per cycle (0=all)")
    parser.add_argument(
        "--pins-per-keyword",
        type=int,
        default=DEFAULT_PINS_PER_KEYWORD,
        help="Relevant pins to produce per keyword",
    )
    parser.add_argument(
        "--session-name",
        default="",
        help=(
            "Isolated Chromium profile name for this remaster worker "
            "(defaults to a domain-specific or unique session)"
        ),
    )
    parser.add_argument(
        "--search-query", default="", help="Generated Pinterest scrape query for single-keyword runs"
    )
    parser.add_argument(
        "--search-queries-json",
        default="",
        help="JSON array of generated Pinterest scrape query variants",
    )
    parser.add_argument(
        "--core-terms",
        default="",
        help="Comma-separated dish-specific terms that every accepted pin must match",
    )
    parser.add_argument(
        "--min-core-matches",
        type=int,
        default=1,
        help="Minimum dish-specific core terms required in accepted pin metadata",
    )
    parser.add_argument(
        "--expected-terms",
        default="",
        help="Comma-separated generated relevance terms for single-keyword runs",
    )
    parser.add_argument(
        "--blocked-terms",
        default="",
        help="Comma-separated generated off-topic terms to reject for single-keyword runs",
    )
    parser.add_argument(
        "--enqueue-after", action="store_true", help="Queue generated article remasters after the run"
    )
    parser.add_argument("--slug", default="", help="Article slug for enqueue-after")
    parser.add_argument("--domain-url", default="", help="Destination domain for enqueue-after")
    parser.add_argument("--domain-handle", default="", help="Domain handle for enqueue-after")
    parser.add_argument(
        "--pipeline-run-id",
        default="",
        help="Telemetry run identifier passed by the article worker",
    )
    parser.add_argument(
        "--recipe-ingredients-json",
        default="",
        help="JSON array of article recipe ingredients for the paired recipe-card variant",
    )
    parser.add_argument(
        "--recipe-steps-json",
        default="",
        help="JSON array of article preparation steps for the paired recipe-card variant",
    )
    parser.add_argument(
        "--tip-text",
        default="",
        help="Optional article chef tip for the paired recipe-card variant",
    )
    parser.add_argument(
        "--enqueue", action="store_true", default=True, help="Auto-enqueue pins to supervisor"
    )
    parser.add_argument("--no-enqueue", action="store_false", dest="enqueue")
    args = parser.parse_args()
    paired_target = _paired_output_target(args.pins_per_keyword)

    if args.continuous and os.environ.get("RANKSTEIN_ENABLE_REMASTER_SIPHON", "").strip().lower() not in {
        "1",
        "true",
        "yes",
        "on",
    }:
        parser.error("--continuous is disabled; set RANKSTEIN_ENABLE_REMASTER_SIPHON=1 to opt in")

    if args.all_domains:
        cycle = 0
        while True:
            cycle += 1
            print(
                f"\n{'=' * 60}\nSOCIAL SIPHON CYCLE {cycle} — {time.strftime('%Y-%m-%d %H:%M:%S')}\n{'=' * 60}"
            )
            asyncio.run(
                run_all_domains(
                    limit=args.limit, pins_per_keyword=args.pins_per_keyword, enqueue=args.enqueue
                )
            )
            if not args.continuous:
                break
            print("Sleeping 10 minutes before next cycle...")
            time.sleep(600)
    else:
        kw = args.keyword or "postres virales 2026"
        title = args.title or kw.title()
        brand_name = "RecetaDolce"
        if args.domain_handle:
            try:
                from rankstein.domain import get_registry

                domain = get_registry().get(args.domain_handle)
                brand_name = domain.display_name
            except KeyError:
                pass
        assets = asyncio.run(
            run_remasterer(
                kw,
                title,
                brand_name=brand_name,
                session_name=args.session_name or None,
                pins_per_keyword=args.pins_per_keyword,
                search_query=args.search_query,
                search_queries=args.search_queries_json,
                core_terms=args.core_terms,
                min_core_matches=args.min_core_matches,
                expected_terms=args.expected_terms,
                blocked_terms=args.blocked_terms,
                pipeline_run_id=args.pipeline_run_id,
                domain_handle=args.domain_handle,
                recipe_ingredients=args.recipe_ingredients_json,
                recipe_steps=args.recipe_steps_json,
                tip_text=args.tip_text,
            )
        )
        enqueue_result = None
        if args.enqueue_after:
            asset_validation = validate_production_asset_set(assets, target_count=paired_target)
            if not asset_validation["success"]:
                enqueue_result = {
                    "success": False,
                    "error": f"Queue blocked by scraped-only asset contract: {asset_validation['error']}",
                    "images": 0,
                    "jobs_enqueued": 0,
                    "details": [],
                    "validation": asset_validation,
                }
                print(f"ENQUEUE_AFTER_BLOCKED: {enqueue_result['error']}")
                _pipeline_event(
                    args.pipeline_run_id,
                    "queue",
                    "failed",
                    "Pinterest enqueue blocked before queue mutation",
                    error=enqueue_result["error"][:240],
                    validation=asset_validation,
                )
                _pipeline_status(args.pipeline_run_id, "attention")
            else:
                from pinterest_automation.campaign import enqueue_article_remasters
                from rankstein.domain import get_registry

                slug = args.slug or re.sub(r"[^a-z0-9]+", "-", _normalize_text(title)).strip("-")
                boards_default = None
                if args.domain_handle:
                    try:
                        boards_default = get_registry().get(args.domain_handle).boards_default
                    except KeyError:
                        pass
                _pipeline_event(
                    args.pipeline_run_id,
                    "queue",
                    "running",
                    "Adding validated scraped-only remasters to the Pinterest queue",
                    images=len(assets),
                )
                enqueue_result = enqueue_validated_production_assets(
                    assets,
                    target_count=paired_target,
                    enqueue_callable=enqueue_article_remasters,
                    slug=slug,
                    title=title,
                    domain_url=args.domain_url or "recetagenial.com",
                    domain_handle=args.domain_handle,
                    boards_default=boards_default,
                    pipeline_run_id=args.pipeline_run_id,
                )
                print(f"ENQUEUE_AFTER: {enqueue_result}")
                if enqueue_result.get("success"):
                    _pipeline_event(
                        args.pipeline_run_id,
                        "queue",
                        "complete",
                        f"Queued {enqueue_result.get('jobs_enqueued', 0)} Pinterest uploads",
                        jobs_enqueued=enqueue_result.get("jobs_enqueued", 0),
                        accounts=enqueue_result.get("accounts", []),
                    )
                    _pipeline_event(
                        args.pipeline_run_id,
                        "distribution",
                        "running",
                        "Pinterest supervisor is distributing queued pins",
                        jobs_total=enqueue_result.get("jobs_enqueued", 0),
                    )
                    _pipeline_status(args.pipeline_run_id, "distributing")
                else:
                    _pipeline_event(
                        args.pipeline_run_id,
                        "queue",
                        "failed",
                        "Pinterest enqueue failed",
                        error=str(enqueue_result.get("error", ""))[:240],
                    )
                    _pipeline_status(args.pipeline_run_id, "attention")
        if args.slug:
            write_article_remaster_report(
                keyword=kw,
                title=title,
                slug=args.slug,
                domain_handle=args.domain_handle,
                domain_url=args.domain_url or "recetagenial.com",
                target_count=paired_target,
                assets=assets,
                enqueue_result=enqueue_result,
                pipeline_run_id=args.pipeline_run_id,
                scrape_brief={
                    "search_query": args.search_query,
                    "search_queries": _value_list(args.search_queries_json),
                    "core_terms": sorted(_term_set(args.core_terms)),
                    "min_core_matches": args.min_core_matches,
                    "expected_terms": args.expected_terms,
                    "blocked_terms": args.blocked_terms,
                },
            )
