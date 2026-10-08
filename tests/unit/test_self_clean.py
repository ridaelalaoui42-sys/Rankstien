from __future__ import annotations

import pytest

from scripts.dev import self_clean


@pytest.mark.unit
@pytest.mark.parametrize(
    "relative_path",
    [
        ".venv/Lib/site-packages/example/__pycache__",
        "frontend/node_modules/example/__pycache__",
        "data/sessions/pinterest_rida_v7/Default/Cache",
        "data/queue/jobs.db",
    ],
)
def test_runtime_and_dependency_paths_are_protected(relative_path: str) -> None:
    assert self_clean._is_safe(self_clean.ROOT / relative_path) is False


@pytest.mark.unit
def test_project_cache_path_remains_cleanable() -> None:
    assert self_clean._is_safe(self_clean.ROOT / "backend" / "__pycache__") is True
