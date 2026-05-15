"""Generate a maintainable file-by-file RankStein audit report.

The audit is local-only and intentionally avoids Git. It inspects project-owned
source, config, test, script, and canonical documentation files, while skipping
dependency folders, browser sessions, caches, generated media, and report output.
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import re
import tomllib
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REPORT_DIR = ROOT / "data" / "reports"

EXCLUDED_DIR_NAMES = {
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "htmlcov",
    "node_modules",
    "venv",
}

EXCLUDED_PREFIXES = (
    ".playwright-mcp",
    "data/reports",
    "data/sessions",
    "data/sessions_backup",
    "data/recetadolce_backup_final",
    "frontend/.next",
    "frontend/out",
    "frontend/dist",
    "nanobanana-output",
)

SOURCE_SUFFIXES = {
    ".bat",
    ".cjs",
    ".css",
    ".env.example",
    ".html",
    ".js",
    ".json",
    ".jsx",
    ".md",
    ".mjs",
    ".ps1",
    ".py",
    ".sql",
    ".toml",
    ".ts",
    ".tsx",
    ".txt",
    ".yaml",
    ".yml",
}

CANONICAL_ROOT_FILES = {
    "README.md",
    "package.json",
    "package-lock.json",
    "pyproject.toml",
    "requirements.txt",
    "rankstein.py",
    "rankstein_mcp_server.py",
}


@dataclass(frozen=True)
class FileAudit:
    path: str
    kind: str
    status: str
    bytes: int
    lines: int
    findings: list[str]


def _is_excluded(path: Path) -> bool:
    rel = path.relative_to(ROOT).as_posix()
    if any(part in EXCLUDED_DIR_NAMES for part in path.relative_to(ROOT).parts):
        return True
    return any(rel == prefix or rel.startswith(f"{prefix}/") for prefix in EXCLUDED_PREFIXES)


def _is_owned_file(path: Path) -> bool:
    rel = path.relative_to(ROOT).as_posix()
    if _is_excluded(path):
        return False
    if rel in CANONICAL_ROOT_FILES:
        return True
    if rel.startswith(("backend/", "cli-harness/", "docs/", "memory/", "pinterest_automation/")):
        return path.suffix.lower() in SOURCE_SUFFIXES
    if rel.startswith(("rankstein/", "scripts/", "tests/", ".gemini/", ".playwright-mcp/")):
        return path.suffix.lower() in SOURCE_SUFFIXES
    if rel.startswith("frontend/"):
        return path.suffix.lower() in SOURCE_SUFFIXES
    if rel.startswith("data/domains/"):
        return path.name in {
            "domain.json",
            "keywords.md",
            "daily_best_keywords.md",
            "daily_best_keywords.json",
        }
    return False


def _kind(path: Path) -> str:
    rel = path.relative_to(ROOT).as_posix()
    if rel.startswith("docs/") or path.suffix.lower() == ".md":
        return "docs"
    if rel.startswith("tests/"):
        return "tests"
    if rel.startswith("scripts/"):
        return "scripts"
    if rel.startswith("frontend/"):
        return "frontend"
    if rel.startswith("backend/"):
        return "backend"
    if rel.startswith(("rankstein/", "pinterest_automation/")):
        return "core"
    if rel.startswith((".gemini/", ".playwright-mcp/")):
        return "agent-config"
    if rel.startswith("data/domains/"):
        return "domain-data"
    return "project"


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return path.read_text(encoding="utf-8", errors="replace")


def _audit_file(path: Path) -> FileAudit:
    rel = path.relative_to(ROOT).as_posix()
    findings: list[str] = []
    status = "ok"
    text = _read_text(path)
    suffix = path.suffix.lower()

    if suffix == ".py":
        try:
            ast.parse(text, filename=rel)
        except SyntaxError as exc:
            status = "fail"
            findings.append(f"python syntax error: line {exc.lineno}: {exc.msg}")
    elif suffix == ".json":
        try:
            json.loads(text)
        except json.JSONDecodeError as exc:
            status = "fail"
            findings.append(f"json parse error: line {exc.lineno}: {exc.msg}")
    elif suffix == ".toml":
        try:
            tomllib.loads(text)
        except tomllib.TOMLDecodeError as exc:
            status = "fail"
            findings.append(f"toml parse error: {exc}")

    md_probe = re.sub(r"^\s*<!--.*?-->\s*", "", text, flags=re.DOTALL)
    if suffix == ".md" and md_probe.strip() and not md_probe.lstrip().startswith("#"):
        findings.append("markdown has no leading title")
    if "\t" in text and suffix in {".py", ".ts", ".tsx", ".js", ".jsx"}:
        findings.append("contains tabs in source file")
    if suffix in {".py", ".ts", ".tsx", ".js", ".jsx"} and re.search(
        r"(?m)^\s*(#|//|/\*|\*)\s*(TODO|FIXME)\b", text
    ):
        findings.append("contains TODO/FIXME marker")
    if re.search(r"AIza[0-9A-Za-z_-]{20,}", text) or re.search(
        r"(?m)^\s*(GEMINI_API_KEY|GOOGLE_API_KEY)\s*=\s*[^ \r\n#]+", text
    ):
        status = "fail"
        findings.append("possible API key or API-key workflow reference")
    if rel.startswith(("scripts/debug/", "scripts/oneoff/")):
        findings.append("non-production helper retained under scripts/debug or scripts/oneoff")

    if findings and status == "ok":
        status = "review"

    return FileAudit(
        path=rel,
        kind=_kind(path),
        status=status,
        bytes=path.stat().st_size,
        lines=text.count("\n") + (1 if text else 0),
        findings=findings,
    )


def collect() -> list[FileAudit]:
    files: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(ROOT):
        current = Path(dirpath)
        dirnames[:] = [
            name for name in dirnames if name not in EXCLUDED_DIR_NAMES and not _is_excluded(current / name)
        ]
        for filename in filenames:
            path = current / filename
            if _is_owned_file(path):
                files.append(path)
    return [_audit_file(path) for path in sorted(files, key=lambda item: item.relative_to(ROOT).as_posix())]


def write_reports(audits: list[FileAudit]) -> tuple[Path, Path]:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    generated_at = datetime.now(UTC).isoformat()
    summary = {
        "generated_at": generated_at,
        "root": str(ROOT),
        "files_audited": len(audits),
        "status_counts": {
            status: sum(1 for item in audits if item.status == status) for status in ["ok", "review", "fail"]
        },
        "kind_counts": {
            kind: sum(1 for item in audits if item.kind == kind)
            for kind in sorted({item.kind for item in audits})
        },
        "files": [asdict(item) for item in audits],
    }

    json_path = REPORT_DIR / "file-by-file-audit.json"
    md_path = REPORT_DIR / "file-by-file-audit.md"
    json_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")

    lines = [
        "# File-by-file Project Audit",
        "",
        f"Generated: {generated_at}",
        f"Root: `{ROOT}`",
        "",
        "## Summary",
        "",
        f"- Files audited: {summary['files_audited']}",
        f"- OK: {summary['status_counts']['ok']}",
        f"- Review: {summary['status_counts']['review']}",
        f"- Fail: {summary['status_counts']['fail']}",
        "",
        "## Scope",
        "",
        "Included: project-owned source, tests, scripts, config, canonical docs, memory prompts, and domain manifests/roadmaps.",
        "Excluded: dependencies, caches, browser sessions, generated media, local reports, and runtime output folders.",
        "",
        "## Files",
        "",
        "| Status | Kind | Lines | Bytes | File | Findings |",
        "|---|---|---:|---:|---|---|",
    ]
    for item in audits:
        findings = "<br>".join(item.findings) if item.findings else ""
        lines.append(
            f"| {item.status} | {item.kind} | {item.lines} | {item.bytes} | `{item.path}` | {findings} |"
        )
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return json_path, md_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate RankStein file-by-file audit reports.")
    parser.add_argument("--fail-on-issues", action="store_true", help="Exit nonzero when fail items exist.")
    parser.add_argument("--json", action="store_true", help="Print summary JSON to stdout.")
    args = parser.parse_args()

    audits = collect()
    json_path, md_path = write_reports(audits)
    failed = [item for item in audits if item.status == "fail"]
    summary = {
        "files_audited": len(audits),
        "fail": len(failed),
        "review": sum(1 for item in audits if item.status == "review"),
        "json": str(json_path),
        "markdown": str(md_path),
    }
    if args.json:
        print(json.dumps(summary, indent=2))
    else:
        print(f"Audited {summary['files_audited']} files. fail={summary['fail']} review={summary['review']}")
        print(f"JSON: {json_path}")
        print(f"Markdown: {md_path}")
    return 1 if args.fail_on_issues and failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
