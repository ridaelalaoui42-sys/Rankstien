"""Retired article-rewrite utility.

This script previously rewrote already-published articles through a legacy
provider. It is deliberately disabled until a maintained Codex-only rewrite
workflow exists, because silently using another model would violate the
production content policy.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from typing import NoReturn

LEGACY_POST_FIXER_DISABLED = (
    "backend/scripts/fix_post.py is retired and will not rewrite or publish an "
    "article. Use a maintained Codex-only article workflow instead."
)


class LegacyPostFixerDisabled(RuntimeError):
    """Raised when the retired article rewriter is invoked."""


def fix_post(slug: str, domain_handle: str) -> NoReturn:
    """Fail closed before reading or mutating a published article."""
    del slug, domain_handle
    raise LegacyPostFixerDisabled(LEGACY_POST_FIXER_DISABLED)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Retired RankStein article-rewrite utility")
    parser.add_argument("slug")
    parser.add_argument("domain")
    args = parser.parse_args(argv)

    try:
        fix_post(args.slug, args.domain)
    except LegacyPostFixerDisabled as exc:
        print(str(exc), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
