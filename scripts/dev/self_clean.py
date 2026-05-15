"""Remove local Rankstein runtime clutter without touching source by default.

The command is intentionally conservative:
- dry-run by default
- skips protected source-like files unless --include-tracked is passed
- refuses to delete anything outside the project root
- works in the current local-only project layout without requiring Git

Typical use:
    python scripts/dev/self_clean.py
    python scripts/dev/self_clean.py --apply
    python scripts/dev/self_clean.py --check
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

CLEAN_FILE_GLOBS = [
    "article*.json",
    "*_article.json",
    "*_*.json",
    "guia_reposteria_2026*.json",
    "payload*.json",
    "payload*.txt",
    "bucket_data.json",
    "audit_report.json",
    "local_audit_report.json",
    "category_id.txt",
    "temp_json.txt",
    "article_*.md",
    "guia_reposteria_*.md",
    "memory/top_10_trends*.md",
    "memory/project_recipe_agency.md",
    "*_fail.png",
    "*_test.png",
    "*_hero.jpg",
    "*_hero.png",
    "*_hero.jpeg",
    "*_hero.webp",
    "r1_*.png",
    "churros_hero.png",
    "audit_*.py",
    "build_*.py",
    "check_*.py",
    "clean_env_json.py",
    "create_article_*.py",
    "debug_*.py",
    "dump_*.py",
    "expand_article.py",
    "fetch_*.py",
    "find_*.py",
    "fix_*.py",
    "isolate_*.py",
    "log_*.py",
    "manual_*.py",
    "minify_*.py",
    "orchestrate_*.py",
    "publish_*.py",
    "revert_to_*.py",
    "set_workers.py",
    "setup_*.py",
    "show_*.py",
    "switch_to_*.py",
    "target_*.py",
    "test_*.py",
    "update_email.py",
    "upload_*.py",
    "scripts/emergency_workflow.py",
    "scripts/debug/download_image_for_pin.py",
    "scripts/debug/job_*.bat",
]

CLEAN_DIR_GLOBS = [
    ".pytest_cache",
    ".playwright-mcp",
    "htmlcov",
    "nanobanana-output",
    "data/domains/*/data/.cache",
    "data/domains/*/data/tmp",
    "data/recetadolce_backup_final",
    "data/recetagenial/data",
    "data/sessions_backup",
    "frontend/scratch",
    "scratch",
    "temp_heros",
    "tmp",
    "**/__pycache__",
]

PROTECTED_NAMES = {".git", ".env", ".env.local", ".env.production"}


@dataclass(frozen=True)
class Candidate:
    path: Path
    kind: str
    tracked: bool
    reason: str

    def as_dict(self) -> dict[str, str | bool]:
        return {
            "path": str(self.path.relative_to(ROOT)),
            "kind": self.kind,
            "tracked": self.tracked,
            "reason": self.reason,
        }


def _git_tracked_paths() -> set[Path]:
    if not (ROOT / ".git").exists():
        return set()
    result = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT, check=True, capture_output=True)
    names = result.stdout.decode("utf-8", errors="ignore").split("\0")
    return {ROOT / name for name in names if name}


def _is_safe(path: Path) -> bool:
    resolved = path.resolve()
    try:
        resolved.relative_to(ROOT.resolve())
    except ValueError:
        return False
    return not any(part in PROTECTED_NAMES for part in resolved.parts)


def _collect(include_tracked: bool) -> list[Candidate]:
    tracked_paths = _git_tracked_paths()
    candidates: dict[Path, Candidate] = {}

    for pattern in CLEAN_FILE_GLOBS:
        for path in ROOT.glob(pattern):
            if not path.is_file() or not _is_safe(path):
                continue
            tracked = path in tracked_paths
            if tracked and not include_tracked:
                continue
            candidates[path] = Candidate(path, "file", tracked, pattern)

    for pattern in CLEAN_DIR_GLOBS:
        for path in ROOT.glob(pattern):
            if not path.is_dir() or not _is_safe(path):
                continue
            tracked = any(
                tracked_path == path or path in tracked_path.parents for tracked_path in tracked_paths
            )
            if tracked and not include_tracked:
                continue
            candidates[path] = Candidate(path, "dir", tracked, pattern)

    return sorted(candidates.values(), key=lambda item: str(item.path.relative_to(ROOT)).lower())


def _delete(candidate: Candidate) -> None:
    if candidate.kind == "dir":
        shutil.rmtree(candidate.path)
    else:
        candidate.path.unlink()


def main() -> int:
    parser = argparse.ArgumentParser(description="Clean generated Rankstein local artifacts.")
    parser.add_argument(
        "--apply", action="store_true", help="Delete candidates instead of printing a dry run."
    )
    parser.add_argument(
        "--check", action="store_true", help="Fail with exit code 1 if cleanup candidates exist."
    )
    parser.add_argument(
        "--include-tracked", action="store_true", help="Also include tracked files/directories."
    )
    parser.add_argument("--json", action="store_true", help="Print machine-readable candidate details.")
    args = parser.parse_args()

    candidates = _collect(include_tracked=args.include_tracked)

    if args.json:
        print(json.dumps([candidate.as_dict() for candidate in candidates], indent=2))
    else:
        verb = "Would remove" if not args.apply else "Removing"
        for candidate in candidates:
            tracked = " tracked" if candidate.tracked else ""
            print(f"{verb}{tracked} {candidate.kind}: {candidate.path.relative_to(ROOT)}")
        print(f"{len(candidates)} cleanup candidate(s).")

    if args.check and candidates:
        return 1

    if args.apply:
        for candidate in candidates:
            _delete(candidate)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
