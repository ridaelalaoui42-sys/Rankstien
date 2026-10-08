"""Runtime environment hygiene for RankStein entrypoints.

RankStein is often invoked from Hermes/Git-Bash on Windows where uv can leave
Python-home variables pointing at a different CPython install than the `python`
found on PATH.  A Python 3.12 process with PYTHONHOME pointed at uv's 3.11
stdlib fails with errors such as `AssertionError: SRE module mismatch` as soon
as modules like `re` are imported.

The public helpers here are safe to call after Python has started.  Script
entrypoints that need protection before any stdlib imports should keep a small
inline bootstrap at the very top and then call `clean_python_env()` normally.
"""

from __future__ import annotations

import os
from collections.abc import Mapping

UNSAFE_PYTHON_ENV_VARS = ("PYTHONHOME", "UV_INTERNAL__PYTHONHOME")


def clean_python_env(env: Mapping[str, str] | None = None) -> dict[str, str]:
    """Return a copy of *env* with unsafe Python-home variables removed."""

    cleaned = dict(os.environ if env is None else env)
    for name in UNSAFE_PYTHON_ENV_VARS:
        cleaned.pop(name, None)
    return cleaned


def sanitize_current_process_env() -> None:
    """Remove unsafe Python-home variables from the current process env."""

    for name in UNSAFE_PYTHON_ENV_VARS:
        os.environ.pop(name, None)
