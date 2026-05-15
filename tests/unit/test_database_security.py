from __future__ import annotations

import pytest
import pytest_asyncio

from backend.core import database as db
from backend.core.config import get_settings


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
async def test_integration_list_redacts_credentials_and_update_filters_fields(isolated_db) -> None:
    domain = await db.create_domain("Security Test", "https://example.invalid")
    integration = await db.save_integration(
        domain["id"],
        "wordpress",
        {"username": "alice", "password": "secret"},
    )

    await db.update_integration(
        integration["id"],
        status="connected",
        credentials={"username": "bob", "password": "new-secret"},
        **{"status = 'owned' --": "ignored"},
    )

    stored = await db.get_integration(integration["id"])
    assert stored is not None
    assert stored["status"] == "connected"
    assert stored["credentials"]["username"] == "bob"

    listed = await db.list_integrations(domain["id"])
    assert listed[0]["credentials_configured"] is True
    assert "credentials" not in listed[0]
    assert "credentials_json" not in listed[0]


@pytest.mark.asyncio
@pytest.mark.unit
async def test_campaign_update_filters_unknown_fields(isolated_db) -> None:
    domain = await db.create_domain("Campaign Security", "https://campaign.example")
    project = await db.create_project(domain["id"], "Campaign Project")
    campaign = await db.create_campaign(project["id"], "safe keyword")

    await db.update_campaign(
        campaign["id"],
        status="approved",
        **{"status = 'owned' --": "ignored"},
    )

    stored = await db.get_campaign(campaign["id"])
    assert stored is not None
    assert stored["status"] == "approved"


@pytest.mark.asyncio
@pytest.mark.unit
async def test_save_pin_filters_unknown_fields(isolated_db) -> None:
    domain = await db.create_domain("Pin Security", "https://pins.example")
    project = await db.create_project(domain["id"], "Pin Project")
    campaign = await db.create_campaign(project["id"], "pin keyword")

    pin_id = await db.save_pin(
        campaign["id"],
        title="Safe pin",
        status="published",
        **{"status = 'owned' --": "ignored"},
    )

    pins = await db.get_pins(campaign["id"])
    assert pins[0]["id"] == pin_id
    assert pins[0]["title"] == "Safe pin"
    assert pins[0]["status"] == "published"
