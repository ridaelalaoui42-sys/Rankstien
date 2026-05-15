import pytest
from httpx import AsyncClient, ASGITransport
from backend.main import app
from backend.core.config import get_settings

@pytest.mark.asyncio
async def test_health():
    """Simple health check to verify the app can start."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.get("/api/health")
    assert response.status_code == 200
    assert response.json()["status"] == "healthy"

@pytest.mark.asyncio
async def test_domain_isolation():
    """Verify domain creation and listing."""
    settings = get_settings()
    headers = {"X-RankStein-Key": settings.rankstein_secret}
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        # 1. Create
        domain_data = {
            "name": "Integration Test Domain",
            "url": "https://test.com",
            "niche": "Testing",
            "schedule": ""
        }
        resp = await ac.post("/api/domains", json=domain_data, headers=headers)
        assert resp.status_code in [200, 409]

        # 2. List
        resp = await ac.get("/api/domains", headers=headers)
        assert resp.status_code == 200
        domains = resp.json()
        assert any(d["name"] == "Integration Test Domain" for d in domains)
