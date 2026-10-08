"""Root shim for the ``rankstein`` CLI.

Usage:
    python rankstein.py add-domain <domain>
    python rankstein.py list-domains
    python rankstein.py show-domain <handle>
    python rankstein.py run --domain <handle>

This file exists so the project can be invoked as a single command from
the project root without users needing to remember ``python -m
rankstein.cli``. Real logic lives in ``rankstein/cli.py``.
"""

from __future__ import annotations

import os
import sys

# Re-exec with a clean Python environment before importing project modules.
# Hermes/Git-Bash can inherit PYTHONHOME/UV_INTERNAL__PYTHONHOME from uv's
# CPython 3.11 while PATH resolves Python 3.12, which later causes stdlib
# imports to fail with "SRE module mismatch". Once Python has initialized with
# a bad PYTHONHOME, simply popping the variable is too late because sys.path has
# already been derived from it, so restart this entrypoint with the bad vars gone.
_clean_env = dict(os.environ)
_reexec_needed = False
for _name in ("PYTHONHOME",):
    if _clean_env.pop(_name, None):
        _reexec_needed = True
_clean_env.pop("UV_INTERNAL__PYTHONHOME", None)
if _reexec_needed:
    _exe = sys.executable.replace("\\", "/")
    os.execve(_exe, [_exe, *sys.argv], _clean_env)  # noqa: S606

from rankstein.cli import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
