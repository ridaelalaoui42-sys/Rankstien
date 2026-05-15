from __future__ import annotations

from pathlib import Path

import pytest
import pytest_asyncio
from pydantic import SecretStr

from backend.core import database as db
from backend.core.config import get_settings
from rankstein.domain import Domain
from rankstein.keyword_roadmap import KeywordRow, read_keyword_rows, write_keyword_rows
from rankstein.startup import StartupOptions, build_startup_plan


@pytest_asyncio.fixture
async def isolated_db(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "rankstein.db"))
    get_settings.cache_clear()
    await db.close_db()
    try:
        yield
    finally:
        await db.close_db()
        get_settings.cache_clear()


@pytest.mark.asyncio
@pytest.mark.unit
async def test_startup_creates_domain_project_and_seeds_campaign(
    tmp_path: Path, monkeypatch, isolated_db
) -> None:
    keywords_file = tmp_path / "keywords.md"
    write_keyword_rows(keywords_file, "Test Site Keyword Roadmap", [KeywordRow("one keyword")])
    domain = Domain(
        handle="testsite",
        domain="test.example",
        display_name="Test Site",
        language="en",
        niche="testing",
        root=tmp_path,
        keywords_file=keywords_file,
        sessions_dir=tmp_path / "sessions",
        output_dir=tmp_path / "output",
        branding_dir=tmp_path / "branding",
        pinterest_email="user@example.com",
        pinterest_password=SecretStr("secret"),
        supabase_url="https://supabase.example",
        supabase_service_role_key=SecretStr("service-role"),
    )

    class FakeMemory:
        def health(self):
            return {"ok": True}

        def search(self, query, limit=5):
            return [{"content": query, "limit": limit}]

        def log_event(self, event_type, message, metadata=None):
            return {"success": True, "event_type": event_type, "message": message, "metadata": metadata}

    class FakeQueue:
        def get_stats(self):
            return {"total": 0}

    monkeypatch.setattr("rankstein.startup.reload_registry", lambda: None)
    monkeypatch.setattr("rankstein.startup._resolve_domains", lambda handles: [domain])
    monkeypatch.setattr("rankstein.startup.agent_memory", FakeMemory())
    monkeypatch.setattr("rankstein.startup.get_job_queue", lambda domain_handle: FakeQueue())

    report = await build_startup_plan(StartupOptions(launch=False, keywords_per_domain=1))

    assert report["brief"]["campaigns_seeded"] == 1
    assert report["brief"]["agentmemory_ok"] is True
    assert report["domains"][0]["db_domain_id"]
    assert report["domains"][0]["project_id"]
    campaigns = await db.list_campaigns(limit=10)
    assert campaigns[0]["project_id"] == report["domains"][0]["project_id"]
    assert campaigns[0]["keyword"] == "one keyword"


@pytest.mark.asyncio
@pytest.mark.unit
async def test_startup_cleans_roadmap_before_trend_append(tmp_path: Path, monkeypatch, isolated_db) -> None:
    keywords_file = tmp_path / "keywords.md"
    write_keyword_rows(
        keywords_file,
        "Test Site Keyword Roadmap",
        [
            KeywordRow("one keyword", status="In Progress"),
            KeywordRow("one keyword", status="Pending"),
        ],
    )
    domain = Domain(
        handle="testsite",
        domain="test.example",
        display_name="Test Site",
        language="en",
        niche="testing",
        root=tmp_path,
        keywords_file=keywords_file,
        sessions_dir=tmp_path / "sessions",
        output_dir=tmp_path / "output",
        branding_dir=tmp_path / "branding",
        pinterest_email="user@example.com",
        pinterest_password=SecretStr("secret"),
        supabase_url="https://supabase.example",
        supabase_service_role_key=SecretStr("service-role"),
    )

    class FakeMemory:
        def health(self):
            return {"ok": True}

        def search(self, query, limit=5):
            return []

        def log_event(self, event_type, message, metadata=None):
            return {"success": True}

    class FakeQueue:
        def get_stats(self):
            return {"total": 0}

    def fake_refresh(domains, **kwargs):
        rows = read_keyword_rows(domains[0].keywords_file)
        assert [row.keyword for row in rows] == ["one keyword"]
        assert rows[0].status == "Pending"
        return {"domains": {"testsite": {"roadmap_added": 0}}}

    monkeypatch.setattr("rankstein.startup.reload_registry", lambda: None)
    monkeypatch.setattr("rankstein.startup._resolve_domains", lambda handles: [domain])
    monkeypatch.setattr("rankstein.startup.agent_memory", FakeMemory())
    monkeypatch.setattr("rankstein.startup.get_job_queue", lambda domain_handle: FakeQueue())
    monkeypatch.setattr("rankstein.startup.refresh_domain_trend_lists", fake_refresh)

    report = await build_startup_plan(StartupOptions(launch=False, keywords_per_domain=1, refresh_trends=True))

    assert report["brief"]["trends_refreshed"] is True
    assert report["pre_trend_cleanup"][0]["cleanup"]["duplicates_removed"] == 1
    assert report["pre_trend_cleanup"][0]["cleanup"]["reset_in_progress"] == 1
