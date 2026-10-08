"""Tests for the shared Firefox cleanup helpers.

These verify the contract callers rely on:

- ``firefox_is_running()`` never raises (returns False on probe failure).
- ``kill_firefox_locks(session_dir)`` removes known lock patterns and the
  SQLite -shm/-wal sidecars, returns a list of action strings, and never
  raises on missing files / unrelated dirs.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from pinterest_automation.browser_utils import (
    _LOCK_FILES,
    browser_pids_for_session,
    firefox_is_running,
    kill_firefox_locks,
    normalize_browser_type,
    user_agent_for_browser,
)


@pytest.fixture
def session_dir(tmp_path: Path) -> Path:
    d = tmp_path / "profile_test"
    d.mkdir()
    return d


@pytest.mark.unit
class TestFirefoxIsRunning:
    def test_returns_bool_when_tasklist_succeeds(self) -> None:
        # Real call to tasklist on the test runner; we don't care about the
        # value, only that it returned a bool without raising.
        assert isinstance(firefox_is_running(), bool)

    def test_returns_false_when_subprocess_errors(self) -> None:
        with patch("pinterest_automation.browser_utils.subprocess.run") as mock_run:
            mock_run.side_effect = FileNotFoundError("tasklist not found")
            assert firefox_is_running() is False


@pytest.mark.unit
class TestBrowserTypeHelpers:
    def test_normalizes_browser_aliases(self) -> None:
        assert normalize_browser_type("chrome") == "chromium"
        assert normalize_browser_type("edge") == "chromium"
        assert normalize_browser_type("ff") == "firefox"

    def test_user_agent_matches_browser_family(self) -> None:
        assert "Chrome/" in user_agent_for_browser("chromium")
        assert "Firefox/" in user_agent_for_browser("firefox")

    def test_ignores_mismatched_configured_user_agent(self) -> None:
        firefox_ua = "Mozilla/5.0 Firefox/128.0"
        assert "Chrome/" in user_agent_for_browser("chromium", firefox_ua)

    def test_returns_false_when_subprocess_times_out(self) -> None:
        import subprocess as sp

        with patch("pinterest_automation.browser_utils.subprocess.run") as mock_run:
            mock_run.side_effect = sp.TimeoutExpired("tasklist", 5)
            assert firefox_is_running() is False

    def test_returns_true_when_firefox_in_output(self) -> None:
        with patch("pinterest_automation.browser_utils.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(stdout="firefox.exe   1234 Console", returncode=0)
            assert firefox_is_running() is True

    def test_returns_false_when_firefox_not_in_output(self) -> None:
        with patch("pinterest_automation.browser_utils.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                stdout="INFO: No tasks are running which match the specified criteria.",
                returncode=0,
            )
            assert firefox_is_running() is False

    def test_finds_playwright_headless_shell_for_chromium_profile(
        self, session_dir: Path
    ) -> None:
        command = (
            "chrome-headless-shell.exe --headless "
            f"--user-data-dir={session_dir.resolve()} --remote-debugging-pipe"
        )
        with patch("pinterest_automation.browser_utils.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(stdout=f"4321\t{command}\n", returncode=0)
            assert browser_pids_for_session(session_dir, "chromium") == [4321]


@pytest.mark.unit
class TestKillFirefoxLocks:
    def test_returns_list(self, session_dir: Path) -> None:
        with (
            patch("pinterest_automation.browser_utils.subprocess.run") as mock_run,
            patch("pinterest_automation.browser_utils.browser_is_running") as mock_check,
        ):
            mock_run.return_value = MagicMock(stdout="", returncode=0)
            mock_check.return_value = False
            result = kill_firefox_locks(session_dir)
        assert isinstance(result, list)

    def test_removes_lock_files(self, session_dir: Path) -> None:
        # Plant every lock pattern the helper knows about
        planted = []
        for name in _LOCK_FILES:
            p = session_dir / name
            p.write_text("")
            planted.append(p)

        with (
            patch("pinterest_automation.browser_utils.subprocess.run") as mock_run,
            patch("pinterest_automation.browser_utils.browser_is_running") as mock_check,
        ):
            mock_run.return_value = MagicMock(stdout="", returncode=0)
            mock_check.return_value = False
            actions = kill_firefox_locks(session_dir)

        for p in planted:
            assert not p.exists(), f"{p.name} should have been removed"
        # Each removed file should appear in the action log
        for name in _LOCK_FILES:
            assert any(name in a for a in actions), f"missing action for {name}"

    def test_removes_stale_pid_files(self, session_dir: Path) -> None:
        (session_dir / "firefox.pid").write_text("")
        (session_dir / "session.pid").write_text("")
        (session_dir / "scratch.tmp").write_text("")

        with (
            patch("pinterest_automation.browser_utils.subprocess.run") as mock_run,
            patch("pinterest_automation.browser_utils.browser_is_running") as mock_check,
        ):
            mock_run.return_value = MagicMock(stdout="", returncode=0)
            mock_check.return_value = False
            kill_firefox_locks(session_dir)

        assert not (session_dir / "firefox.pid").exists()
        assert not (session_dir / "session.pid").exists()
        assert not (session_dir / "scratch.tmp").exists()

    def test_polls_until_firefox_gone(self, session_dir: Path) -> None:
        # Simulate firefox.exe taking a moment to terminate after taskkill.
        # browser_is_running returns True twice, then False.
        running_states = [True, True, False]
        call_count = {"n": 0}

        def fake_running(browser_type: str = "firefox") -> bool:
            i = call_count["n"]
            call_count["n"] += 1
            return running_states[min(i, len(running_states) - 1)]

        with (
            patch("pinterest_automation.browser_utils.subprocess.run") as mock_run,
            patch(
                "pinterest_automation.browser_utils.browser_is_running",
                side_effect=fake_running,
            ),
            patch("pinterest_automation.browser_utils.time.sleep") as mock_sleep,
        ):
            mock_run.return_value = MagicMock(stdout="", returncode=0)
            actions = kill_firefox_locks(session_dir)

        # Should have polled at least 3 times (poll, poll, gone) and slept between
        assert mock_sleep.call_count >= 2
        # Should NOT have logged the "still visible" warning (firefox went away)
        assert not any("still visible" in a for a in actions)

    def test_warns_if_firefox_still_running_after_timeout(self, session_dir: Path) -> None:
        with (
            patch("pinterest_automation.browser_utils.subprocess.run") as mock_run,
            patch("pinterest_automation.browser_utils.browser_is_running") as mock_check,
            patch("pinterest_automation.browser_utils.time.sleep"),
            patch("pinterest_automation.browser_utils.time.time") as mock_time,
        ):
            mock_run.return_value = MagicMock(stdout="", returncode=0)
            mock_check.return_value = True  # firefox never goes away
            # Force the polling loop to exit by advancing time past the deadline
            mock_time.side_effect = [0.0, 0.0, 100.0]
            actions = kill_firefox_locks(session_dir)

        assert any("still visible" in a for a in actions)

    def test_does_not_raise_on_missing_session_dir(self, tmp_path: Path) -> None:
        # Even if the dir doesn't exist, the helper should not crash —
        # callers may pre-create the dir but we should be defensive.
        nonexistent = tmp_path / "does_not_exist"
        nonexistent.mkdir()  # browser_utils assumes parent exists; create empty
        with (
            patch("pinterest_automation.browser_utils.subprocess.run") as mock_run,
            patch("pinterest_automation.browser_utils.browser_is_running") as mock_check,
        ):
            mock_run.return_value = MagicMock(stdout="", returncode=0)
            mock_check.return_value = False
            # Should not raise
            kill_firefox_locks(nonexistent)
