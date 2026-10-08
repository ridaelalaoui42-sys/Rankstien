"""Markdown keyword roadmap helpers for RankStein domains."""

import logging
import shutil
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

logger = logging.getLogger("keyword_roadmap")

HEADER_COLUMNS = ["Keyword", "Cluster", "Source", "Target Blog", "Priority", "Status"]
EXPECTED_HEADER = "| " + " | ".join(HEADER_COLUMNS) + " |"

# Known valid Markdown header patterns for keyword roadmaps
_VALID_HEADERS = {
    "| Keyword",
    "| keyword",
}


@dataclass
class KeywordRow:
    keyword: str
    cluster: str = "General"
    source: str = "Startup"
    target_blog: str = ""
    priority: str = "Medium"
    status: str = "Pending"

    @classmethod
    def from_markdown(cls, line: str) -> "KeywordRow | None":
        if not line.strip().startswith("|"):
            return None
        parts = [part.strip() for part in line.strip().strip("|").split("|")]
        if len(parts) < 6 or parts[0].lower() in {"keyword", "---"}:
            return None
        keyword = parts[0].strip()
        if not keyword or set(keyword) == {"-"}:
            return None
        return cls(
            keyword=keyword,
            cluster=parts[1].strip() or "General",
            source=parts[2].strip() or "Startup",
            target_blog=parts[3].strip(),
            priority=parts[4].strip() or "Medium",
            status=parts[5].strip() or "Pending",
        )

    def to_markdown(self) -> str:
        return (
            f"| {self.keyword} | {self.cluster} | {self.source} | "
            f"{self.target_blog} | {self.priority} | {self.status} |"
        )


def is_valid_roadmap_format(path: Path) -> bool:
    """Check if a file has the expected Markdown table header for keyword roadmaps."""
    if not path.exists():
        return True
    content = path.read_text(encoding="utf-8")
    for line in content.splitlines():
        stripped = line.strip()
        if any(stripped.startswith(h) for h in _VALID_HEADERS):
            return True
    return False


def assert_roadmap_format(path: Path) -> None:
    """Raise if file exists but doesn't look like a Markdown roadmap table."""
    if not is_valid_roadmap_format(path):
        expected = EXPECTED_HEADER
        actual_lines = path.read_text(encoding="utf-8").splitlines()[:5]
        logger.error(
            "File %s does not contain a valid Markdown roadmap header.\n"
            "  Expected line starting with: %s\n"
            "  First lines of file:\n    %s",
            path,
            expected,
            "\n    ".join(actual_lines),
        )
        raise ValueError(
            f"Invalid keyword roadmap format in {path.name}. "
            f"Expected Markdown table with header: '{expected}'. "
            f"First line: '{actual_lines[0] if actual_lines else '(empty)'}'. "
            "This file may have been manually edited in a non-Markdown format. "
            "Restore from a .bak backup or re-run the recovery script."
        )


def read_keyword_rows(path: Path) -> list[KeywordRow]:
    if not path.exists():
        return []
    assert_roadmap_format(path)
    rows: list[KeywordRow] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        row = KeywordRow.from_markdown(line)
        if row:
            rows.append(row)
    return rows


def _backup_file(path: Path) -> None:
    """Create a timestamped backup before overwriting."""
    if not path.exists():
        return
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    bak_path = path.with_name(f"{path.name}.{timestamp}.bak")
    try:
        shutil.copy2(path, bak_path)
        logger.info("Backed up %s -> %s", path.name, bak_path.name)
    except (PermissionError, OSError) as exc:
        logger.warning("Skipped roadmap backup for %s (%s)", path.name, exc)


def validate_rows(rows: list[KeywordRow]) -> None:
    """Sanity-check rows before writing — raises on obvious problems."""
    if not rows:
        logger.warning("Writing empty keyword roadmap — file will be cleared")
        return
    empty_keywords = sum(1 for r in rows if not r.keyword.strip())
    if empty_keywords:
        raise ValueError(f"{empty_keywords} row(s) have empty keyword — refusing to write")
    if len(rows) > 10000:
        logger.warning("Writing %d rows — double-check this is intentional", len(rows))


def write_keyword_rows(path: Path, title: str, rows: list[KeywordRow]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        assert_roadmap_format(path)
    _backup_file(path)
    validate_rows(rows)
    lines = [
        f"# {title}",
        "",
        EXPECTED_HEADER,
        "|---|---|---|---|---|---|",
    ]
    lines.extend(row.to_markdown() for row in rows)
    content_str = "\n".join(lines) + "\n"
    for attempt in range(4):
        try:
            path.write_text(content_str, encoding="utf-8")
            break
        except (PermissionError, OSError) as exc:
            if attempt == 3:
                logger.error("Failed to write keyword roadmap %s: %s", path.name, exc)
                raise
            time.sleep(0.25)


def keyword_counts(rows: list[KeywordRow]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        counts[row.status] = counts.get(row.status, 0) + 1
    return counts


def clean_keyword_roadmap(
    path: Path,
    title: str,
    completed_keywords: set[str] | None = None,
) -> dict[str, object]:
    """Normalize one roadmap before article generation starts.

    Cleanup is intentionally conservative: it deduplicates exact keyword
    repeats, resets abandoned ``In Progress`` rows to ``Pending``, and marks
    rows already completed in the DB as ``Live``.
    """
    completed = {kw.casefold() for kw in completed_keywords or set()}
    original_rows = read_keyword_rows(path)
    seen: set[str] = set()
    cleaned: list[KeywordRow] = []
    duplicates_removed = 0
    reset_count = 0
    db_live_count = 0

    for row in original_rows:
        key = row.keyword.casefold()
        if key in seen:
            duplicates_removed += 1
            continue
        seen.add(key)

        if row.status.lower() == "in progress":
            row.status = "Pending"
            reset_count += 1
        if key in completed and row.status.lower() not in {"live", "complete", "completed"}:
            row.status = "Live"
            db_live_count += 1
        cleaned.append(row)

    write_keyword_rows(path, title, cleaned)
    return {
        "path": str(path),
        "total_before": len(original_rows),
        "total_after": len(cleaned),
        "duplicates_removed": duplicates_removed,
        "reset_in_progress": reset_count,
        "marked_live_from_db": db_live_count,
        "counts": keyword_counts(cleaned),
    }


def reserve_pending_keywords(
    path: Path,
    title: str,
    limit: int,
    *,
    eligible_keywords: set[str] | None = None,
) -> list[KeywordRow]:
    """Reserve Pending rows, optionally restricted to researched keywords."""

    rows = read_keyword_rows(path)
    eligible = (
        {keyword.strip().casefold() for keyword in eligible_keywords}
        if eligible_keywords is not None
        else None
    )
    selected: list[KeywordRow] = []
    for row in rows:
        if len(selected) >= limit:
            break
        if row.status.lower() == "pending" and (
            eligible is None or row.keyword.strip().casefold() in eligible
        ):
            row.status = "In Progress"
            selected.append(row)
    if selected:
        write_keyword_rows(path, title, rows)
    return selected


def mark_keyword_status(path: Path, title: str, keyword: str, status: str) -> bool:
    rows = read_keyword_rows(path)
    changed = False
    for row in rows:
        if row.keyword.casefold() == keyword.casefold():
            row.status = status
            changed = True
            break
    if changed:
        write_keyword_rows(path, title, rows)
    return changed


def append_keyword_rows(path: Path, title: str, new_rows: list[KeywordRow]) -> int:
    """Append unique keyword rows while preserving existing roadmap state.

    Trend refreshes often rediscover keywords that are already present in the
    roadmap. If the old row is ``Failed``/``Needs Verification``/``Staged``,
    treating that rediscovery as a plain duplicate leaves the roadmap with zero
    Pending keywords forever. Re-activate retryable duplicate rows instead of
    ignoring them so a fresh trend signal can refill the worker queue.
    """
    rows = read_keyword_rows(path)
    existing_by_key = {row.keyword.casefold(): row for row in rows}
    added_or_reactivated = 0
    metadata_refreshed = False
    retryable_duplicate_statuses = {"failed", "needs verification", "staged"}
    for row in new_rows:
        key = row.keyword.casefold()
        if not row.keyword.strip():
            continue
        existing = existing_by_key.get(key)
        if existing:
            if existing.status.strip().casefold() in retryable_duplicate_statuses:
                existing.cluster = row.cluster or existing.cluster
                existing.source = row.source or existing.source
                existing.target_blog = row.target_blog or existing.target_blog
                existing.priority = row.priority or existing.priority
                existing.status = "Pending"
                added_or_reactivated += 1
            elif existing.status.strip().casefold() == "pending":
                refreshed_values = (
                    row.cluster or existing.cluster,
                    row.source or existing.source,
                    row.target_blog or existing.target_blog,
                    row.priority or existing.priority,
                )
                old_values = (
                    existing.cluster,
                    existing.source,
                    existing.target_blog,
                    existing.priority,
                )
                if refreshed_values != old_values:
                    (
                        existing.cluster,
                        existing.source,
                        existing.target_blog,
                        existing.priority,
                    ) = refreshed_values
                    metadata_refreshed = True
            continue
        rows.append(row)
        existing_by_key[key] = row
        added_or_reactivated += 1
    if added_or_reactivated or metadata_refreshed:
        write_keyword_rows(path, title, rows)
    return added_or_reactivated
