"""Retired daily article engine.

The historical implementation generated recipe articles with an unapproved
provider and could fall back to deterministic template text. Those callable
paths are intentionally fail-closed. Running this file directly delegates to
the maintained RankStein campaign command, whose production worker enforces
the Codex-only article policy.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import NoReturn

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
CODEX_ARTICLE_PROVIDER = "hermes-codex-only"
LEGACY_DAILY_ENGINE_DISABLED = (
    "backend/scripts/daily_engine.py no longer generates articles or hero images. "
    "Use the RankStein dashboard Production Batch or `python rankstein.py run`; "
    "article creation is Codex-only and fails closed when Codex is unavailable."
)


class LegacyDailyEngineDisabled(RuntimeError):
    """Raised when retired programmatic daily-engine code is invoked."""


def _disabled() -> NoReturn:
    raise LegacyDailyEngineDisabled(LEGACY_DAILY_ENGINE_DISABLED)


async def generate_article_content(keyword: str) -> NoReturn:
    """Reject the retired article generator without contacting any provider."""
    del keyword
    _disabled()


async def generate_ai_hero_image(keyword: str, slug: str) -> NoReturn:
    """Reject the retired image generator without contacting any provider."""
    del keyword, slug
    _disabled()


async def daily_growth_loop() -> NoReturn:
    """Reject programmatic execution of the retired single-domain workflow."""
    _disabled()


async def run_forever() -> NoReturn:
    """Reject programmatic execution of the retired scheduler."""
    _disabled()


def main(argv: Sequence[str] | None = None) -> int:
    """Delegate CLI use to the maintained, Codex-only RankStein runner."""
    parser = argparse.ArgumentParser(
        description="Compatibility wrapper for the maintained RankStein campaign runner"
    )
    parser.add_argument(
        "--run-once",
        action="store_true",
        help="Run the campaign audit/seed pass once without launching article workers.",
    )
    args = parser.parse_args(argv)

    command = [sys.executable, str(PROJECT_ROOT / "rankstein.py"), "run", "--all"]
    if args.run_once:
        command.append("--no-launch")

    child_env = os.environ.copy()
    child_env["RANKSTEIN_ARTICLE_PROVIDER"] = CODEX_ARTICLE_PROVIDER
    return subprocess.call(command, cwd=PROJECT_ROOT, env=child_env)


if __name__ == "__main__":
    raise SystemExit(main())
