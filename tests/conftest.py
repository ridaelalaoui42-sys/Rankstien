"""Shared pytest fixtures for RankStein.

Keeps tests hermetic: no network calls, no real filesystem mutation outside
``tmp_path``, no real Supabase / Pinterest. Anything that needs those belongs
under ``tests/integration/`` or ``tests/e2e/`` and is opt-in.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))


@pytest.fixture(autouse=True)
def _isolated_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[None]:
    """Run every test with a clean, fake environment so secrets never leak in."""
    safe_env = {
        "RANKSTEIN_SECRET": "test-secret-min-16-chars-long-padding",
        "NEXT_PUBLIC_SUPABASE_URL": "https://example.invalid",
        "SUPABASE_SERVICE_ROLE_KEY": "test-key",
        "PINTEREST_EMAIL": "test@example.invalid",
        "PINTEREST_PASSWORD": "not-a-real-password",
        "GOOGLE_API_KEY": "test-key",
    }
    for k in list(os.environ):
        # Drop production env vars so tests can't accidentally hit real services
        if k in safe_env or k.startswith(("SUPABASE_", "PINTEREST_", "CLOUDINARY_", "RANKSTEIN_")):
            monkeypatch.delenv(k, raising=False)
    for k, v in safe_env.items():
        monkeypatch.setenv(k, v)
    yield


@pytest.fixture
def project_root() -> Path:
    return PROJECT_ROOT
