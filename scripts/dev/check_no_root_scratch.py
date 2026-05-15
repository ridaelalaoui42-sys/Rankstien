#!/usr/bin/env python3
"""Pre-commit hook: enforce workspace hygiene.

Two rules:

1. **No scratch at repo root.** Files matching scratch patterns
   (``temp_*.py``, ``test_*.py``, ``fix_*.py``, ``patch_*.py``,
   ``debug_*.py``) are blocked at the repo root. They belong under
   ``scripts/debug/`` (timestamped, ad-hoc) or a canonical module
   (permanent, with tests).

2. **Timestamp prefix in scripts/debug/.** Files committed under
   ``scripts/debug/`` must follow the convention
   ``<UTC-timestamp>_<short-purpose>.py`` so the directory stays
   chronologically navigable. Format: ``YYYY-MM-DDTHH-MM-SS_*.py``.
   Allow-listed exceptions: ``README.md``, ``.gitkeep``.

Exits non-zero with an actionable message on any violation.

See the workspace-hygiene rule in ``GEMINI.md``.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEBUG_PREFIX = "scripts/debug/"
TIMESTAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2}_.+\.py$")
DEBUG_ALLOWLIST: frozenset[str] = frozenset({"README.md", ".gitkeep"})


def offending_root_paths(staged: list[str]) -> list[str]:
    """Files staged at the repo root (no parent dir) violate rule 1."""
    return [raw for raw in staged if "/" not in raw and "\\" not in raw]


def offending_debug_paths(staged: list[str]) -> list[str]:
    """Files in scripts/debug/ that don't follow the timestamp convention."""
    bad: list[str] = []
    for raw in staged:
        norm = raw.replace("\\", "/")
        if not norm.startswith(DEBUG_PREFIX):
            continue
        rest = norm[len(DEBUG_PREFIX) :]
        # Skip nested subdirs and allow-listed scaffolding files
        if "/" in rest or rest in DEBUG_ALLOWLIST:
            continue
        if not TIMESTAMP_RE.match(rest):
            bad.append(raw)
    return bad


def main(argv: list[str]) -> int:
    root_bad = offending_root_paths(argv)
    debug_bad = offending_debug_paths(argv)

    if not root_bad and not debug_bad:
        return 0

    if root_bad:
        print("\n[workspace-hygiene] Refusing to commit scratch files at the repo root:\n")
        for path in root_bad:
            print(f"  - {path}")
        print(
            "\nMove them under scripts/debug/ with a UTC timestamp prefix, e.g.:\n"
            "    git mv temp_login_repro.py "
            "scripts/debug/2026-05-02T08-15-00_login_repro.py\n"
            "\nIf the script is permanent, promote it into a module under "
            "pinterest_automation/ or the canonical package and add a test in tests/.\n"
        )

    if debug_bad:
        print("\n[workspace-hygiene] Files in scripts/debug/ must use the timestamp convention:\n")
        for path in debug_bad:
            print(f"  - {path}")
        print(
            "\nRename to <YYYY-MM-DDTHH-MM-SS>_<short-purpose>.py, e.g.:\n"
            "    git mv scripts/debug/test_pinterest.py "
            "scripts/debug/2026-05-02T10-00-00_test_pinterest.py\n"
        )
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
