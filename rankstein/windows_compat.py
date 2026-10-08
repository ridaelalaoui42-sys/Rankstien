"""Avoid optional, unbounded Windows hardware queries during worker startup."""

from __future__ import annotations

import sys


def disable_optional_wmi_queries() -> bool:
    """Use Python's existing WinAPI/environment fallback for platform metadata.

    Python 3.12's platform module consults native WMI even for platform.system().
    A degraded WMI provider can hang or raise a fatal native allocation error
    while importing aiohttp. RankStein does not need WMI hardware metadata.
    This is process-local; it never changes or restarts any Windows service.
    """
    if sys.platform != "win32":
        return False

    import platform

    if not hasattr(platform, "_wmi_query"):
        return False

    def unavailable(*_args):
        raise OSError("RankStein uses bounded WinAPI/environment platform metadata")

    platform._wmi_query = unavailable
    return True
