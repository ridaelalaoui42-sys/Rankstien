"""Markdown keyword roadmap helpers for RankStein domains."""

from dataclasses import dataclass
from pathlib import Path

HEADER_COLUMNS = ["Keyword", "Cluster", "Source", "Target Blog", "Priority", "Status"]


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


def read_keyword_rows(path: Path) -> list[KeywordRow]:
    if not path.exists():
        return []
    rows: list[KeywordRow] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        row = KeywordRow.from_markdown(line)
        if row:
            rows.append(row)
    return rows


def write_keyword_rows(path: Path, title: str, rows: list[KeywordRow]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        f"# {title}",
        "",
        "| " + " | ".join(HEADER_COLUMNS) + " |",
        "|---|---|---|---|---|---|",
    ]
    lines.extend(row.to_markdown() for row in rows)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


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


def reserve_pending_keywords(path: Path, title: str, limit: int) -> list[KeywordRow]:
    rows = read_keyword_rows(path)
    selected: list[KeywordRow] = []
    for row in rows:
        if len(selected) >= limit:
            break
        if row.status.lower() == "pending":
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
    """Append unique keyword rows while preserving existing roadmap state."""
    rows = read_keyword_rows(path)
    existing = {row.keyword.casefold() for row in rows}
    added = 0
    for row in new_rows:
        key = row.keyword.casefold()
        if not row.keyword.strip() or key in existing:
            continue
        rows.append(row)
        existing.add(key)
        added += 1
    if added:
        write_keyword_rows(path, title, rows)
    return added
