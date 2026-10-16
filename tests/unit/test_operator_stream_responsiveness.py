import asyncio
import json
import threading

import httpx
import pytest

from backend.api import operator_routes as routes
from backend.operator import app


class ConnectedRequest:
    async def is_disconnected(self):
        return False


@pytest.fixture
def stream_state(monkeypatch):
    lock = threading.Lock()
    monkeypatch.setattr(routes, "STREAM_REFRESH_LOCK", lock)
    monkeypatch.setattr(routes, "_STREAM_CACHE", None)
    monkeypatch.setattr(routes, "_STREAM_REFRESH_STARTED_AT", 0.0)
    monkeypatch.setattr(routes, "_STREAM_REFRESH_ERROR", "")
    monkeypatch.setattr(routes, "STREAM_REFRESH_INTERVAL_SECONDS", 0.01)
    monkeypatch.setattr(routes, "STREAM_REFRESH_TIMEOUT_SECONDS", 0.02)
    monkeypatch.setattr(routes, "_cached_status_payload", lambda: {"observed": True})
    monkeypatch.setattr(routes, "_collect_telemetry_gauges", lambda: {"cpu": 12})
    monkeypatch.setattr(routes, "_collect_workers_snapshots", lambda: [{"job_id": "exact-job"}])
    return lock


async def wait_until(predicate):
    async def poll():
        while not predicate():  # noqa: ASYNC110 - observe the owned thread's lock without blocking ASGI
            await asyncio.sleep(0.001)

    await asyncio.wait_for(poll(), timeout=2)


@pytest.mark.parametrize(
    "collector",
    ["_cached_status_payload", "_collect_telemetry_gauges", "_collect_workers_snapshots"],
)
@pytest.mark.parametrize("has_previous", [False, True])
def test_blocked_stream_collection_preserves_health_and_single_flight(
    monkeypatch, stream_state, collector, has_previous
):
    entered = threading.Event()
    release = threading.Event()
    calls = []
    original = getattr(routes, collector)
    previous = {
        "timestamp": 123,
        "status": {"old_observation": True},
        "telemetry": {"cpu": 7},
        "workers": [{"job_id": "previous-job"}],
    }
    if has_previous:
        monkeypatch.setattr(routes, "_STREAM_CACHE", (0.0, previous))

    def blocked():
        calls.append(threading.get_ident())
        entered.set()
        assert release.wait(timeout=5), "test collector was not released"
        return original()

    monkeypatch.setattr(routes, collector, blocked)

    async def scenario():
        stream = routes._event_stream_generator(ConnectedRequest())
        try:
            frame = await asyncio.wait_for(anext(stream), timeout=1)
            data = json.loads(frame.removeprefix("data: "))
            assert data["stream_refresh"]["stale"] is True
            await wait_until(entered.is_set)
            monkeypatch.setattr(routes, "_STREAM_REFRESH_STARTED_AT", 0.0)
            for _ in range(10):
                payload = routes._stream_snapshot_payload()
                assert payload["stream_refresh"]["state"] == "timeout"
                if has_previous:
                    assert payload["timestamp"] == 123
                    assert payload["workers"] == previous["workers"]
                else:
                    assert payload["timestamp"] is None
                    assert payload["telemetry"] == {}
                    assert payload["workers"] == []
            assert len(calls) == 1
            transport = httpx.ASGITransport(app=app, client=("127.0.0.1", 1234))
            async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:7000") as client:
                response = await asyncio.wait_for(client.get("/health"), timeout=1)
            assert response.status_code == 200
            assert response.json()["service"] == "rankstein-operator"
        finally:
            release.set()
            await wait_until(lambda: not stream_state.locked())
            await stream.aclose()
        assert routes._STREAM_CACHE[1]["workers"] == [{"job_id": "exact-job"}]

    asyncio.run(scenario())


def test_failed_stream_collection_releases_single_flight_for_retry(monkeypatch, stream_state):
    def failed():
        raise RuntimeError("private diagnostic must not reach the stream")

    monkeypatch.setattr(routes, "_collect_telemetry_gauges", failed)

    async def scenario():
        routes._stream_snapshot_payload()
        await wait_until(lambda: not stream_state.locked())
        assert routes._STREAM_REFRESH_ERROR == "Snapshot collection failed"
        monkeypatch.setattr(routes, "_collect_telemetry_gauges", lambda: {"cpu": 9})
        routes._stream_snapshot_payload()
        await wait_until(lambda: not stream_state.locked())
        assert routes._STREAM_CACHE[1]["telemetry"] == {"cpu": 9}
        assert routes._STREAM_REFRESH_ERROR == ""

    asyncio.run(scenario())
