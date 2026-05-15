"""Tests for the pre-commit workspace-hygiene hook.

Covers both rules:
  1. No scratch files at repo root
  2. Timestamp-prefix convention enforced inside scripts/debug/
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "scripts" / "dev"))

from check_no_root_scratch import (  # noqa: E402
    offending_debug_paths,
    offending_root_paths,
)


@pytest.mark.unit
class TestOffendingRootPaths:
    def test_root_temp_script_is_flagged(self) -> None:
        assert offending_root_paths(["temp_upload.py"]) == ["temp_upload.py"]

    def test_root_test_script_is_flagged(self) -> None:
        assert offending_root_paths(["test_upload.py"]) == ["test_upload.py"]

    def test_root_debug_script_is_flagged(self) -> None:
        assert offending_root_paths(["debug_login.py"]) == ["debug_login.py"]

    def test_subdirectory_path_is_allowed(self) -> None:
        assert offending_root_paths(["scripts/debug/2026-05-02T08-15-00_login.py"]) == []

    def test_tests_subdirectory_is_allowed(self) -> None:
        assert offending_root_paths(["tests/unit/test_circuit_breaker.py"]) == []

    def test_pinterest_automation_module_is_allowed(self) -> None:
        assert offending_root_paths(["pinterest_automation/new_module.py"]) == []

    def test_windows_backslash_path_is_recognized_as_subdir(self) -> None:
        # Pre-commit normally normalizes, but be defensive on Windows
        assert offending_root_paths(["scripts\\debug\\foo.py"]) == []

    def test_multiple_paths_only_root_flagged(self) -> None:
        result = offending_root_paths(
            [
                "temp_upload.py",
                "scripts/debug/repro.py",
                "fix_thing.py",
                "backend/agents/foo.py",
            ]
        )
        assert result == ["temp_upload.py", "fix_thing.py"]

    def test_empty_input(self) -> None:
        assert offending_root_paths([]) == []


@pytest.mark.unit
class TestOffendingDebugPaths:
    def test_timestamped_name_is_allowed(self) -> None:
        assert offending_debug_paths(["scripts/debug/2026-05-02T08-15-00_login_repro.py"]) == []

    def test_non_timestamped_name_is_flagged(self) -> None:
        assert offending_debug_paths(["scripts/debug/test_pinterest.py"]) == [
            "scripts/debug/test_pinterest.py"
        ]

    def test_readme_is_allowed(self) -> None:
        assert offending_debug_paths(["scripts/debug/README.md"]) == []

    def test_gitkeep_is_allowed(self) -> None:
        assert offending_debug_paths(["scripts/debug/.gitkeep"]) == []

    def test_nested_subdir_is_allowed(self) -> None:
        # Files in scripts/debug/<subdir>/ are not flagged — subdir owners
        # may have their own conventions
        assert offending_debug_paths(["scripts/debug/feature_x/raw.py"]) == []

    def test_files_outside_debug_dir_ignored(self) -> None:
        assert offending_debug_paths(["pinterest_automation/foo.py", "tests/x.py"]) == []

    def test_partial_timestamp_rejected(self) -> None:
        # Missing seconds component
        assert offending_debug_paths(["scripts/debug/2026-05-02T08-15_login.py"]) == [
            "scripts/debug/2026-05-02T08-15_login.py"
        ]

    def test_no_short_purpose_after_timestamp_rejected(self) -> None:
        # Timestamp without the underscore-separated purpose suffix
        assert offending_debug_paths(["scripts/debug/2026-05-02T08-15-00.py"]) == [
            "scripts/debug/2026-05-02T08-15-00.py"
        ]
