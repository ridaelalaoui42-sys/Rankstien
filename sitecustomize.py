"""RankStein-wide Python startup environment hygiene.

When commands are launched from this workspace, Python imports this file during
site initialization.  It removes uv/Hermes Python-home variables that can point a
PATH-resolved Python 3.12 interpreter at a Python 3.11 stdlib and produce errors
like `AssertionError: SRE module mismatch`.
"""

from __future__ import annotations

import os
import sys

_clean_env = dict(os.environ)
_reexec_needed = False
for _name in ("PYTHONHOME",):
    if _clean_env.pop(_name, None):
        _reexec_needed = True
_clean_env.pop("UV_INTERNAL__PYTHONHOME", None)

if _reexec_needed:
    _exe = sys.executable.replace("\\", "/")
    os.execve(_exe, [_exe, *sys.argv], _clean_env)  # noqa: S606
