from __future__ import annotations

import platform

import pytest

from rankstein import windows_compat


def test_windows_platform_metadata_does_not_call_native_wmi(monkeypatch):
    monkeypatch.setattr(windows_compat.sys, "platform", "win32")

    def forbidden(*_args):
        raise AssertionError("Native WMI must not be queried")

    monkeypatch.setattr(platform, "_wmi_query", forbidden, raising=False)
    assert windows_compat.disable_optional_wmi_queries() is True
    with pytest.raises(OSError, match="bounded"):
        platform._wmi_query("CPU", "Architecture")


def test_non_windows_platform_is_unchanged(monkeypatch):
    monkeypatch.setattr(windows_compat.sys, "platform", "linux")
    marker = object()
    monkeypatch.setattr(platform, "_wmi_query", marker, raising=False)
    assert windows_compat.disable_optional_wmi_queries() is False
    assert platform._wmi_query is marker
