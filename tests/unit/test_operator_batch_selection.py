import json
import threading

import pytest
from fastapi.testclient import TestClient

from backend.api import operator_routes as routes
from backend.operator import app

SELECTED = "production-20261008-174143"
NEWER = "production-20261015-161812"
ENDPOINT = "/api/rankstein/control/production-batch/select"


@pytest.fixture
def selection(tmp_path, monkeypatch):
    reports = tmp_path / "data/reports/production_batches"
    reports.mkdir(parents=True)
    for batch_id, target in ((SELECTED, 10), (NEWER, 2)):
        (reports / f"{batch_id}.json").write_text(
            json.dumps({"batch_id": batch_id, "target_per_domain": target, "state": "running"}),
            encoding="utf-8",
        )
    registry = tmp_path / "data/runtime/operator_processes.json"
    registry.parent.mkdir(parents=True)
    registry.write_text(
        json.dumps({"production": {"pid": 123, "command": ["python", "worker.py", "--batch-id", NEWER]}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(routes, "RANKSTEIN_ROOT", tmp_path)
    monkeypatch.setattr(routes, "PROCESS_FILE", registry)
    monkeypatch.setattr(routes, "PREFERENCES_LOCK", threading.Lock())
    monkeypatch.setattr(routes, "STATUS_CACHE_LOCK", threading.Lock())
    monkeypatch.setattr(routes, "STREAM_REFRESH_LOCK", threading.Lock())
    monkeypatch.setattr(routes, "_STATUS_CACHE", (0, {"old": True}))
    monkeypatch.setattr(routes, "_STREAM_CACHE", (0, {"old": True}))
    monkeypatch.setattr(routes, "_DISPLAY_CACHE_GENERATION", 0)
    monkeypatch.setattr(routes, "_pid_alive", lambda *args: False)

    def forbidden(*args, **kwargs):
        pytest.fail("Display selection must not launch or save production processes")

    monkeypatch.setattr(routes, "_start_background", forbidden)
    monkeypatch.setattr(routes, "_save_processes", forbidden)
    monkeypatch.setattr(routes.subprocess, "Popen", forbidden)
    monkeypatch.setattr(routes.subprocess, "run", forbidden)
    with TestClient(app, base_url="http://127.0.0.1:7000", client=("127.0.0.1", 1234)) as client:
        token = client.get("/api/operator/session").json()["csrf_token"]
        yield client, {"X-RankStein-CSRF": token}, reports, registry


def test_selection_is_authenticated_display_only_and_preserves_existing_files(selection):
    client, headers, reports, registry = selection
    paths = [registry, *reports.glob("*.json")]
    original = {path: path.read_bytes() for path in paths}
    preference = routes._operator_preferences_path()
    preference.write_text(json.dumps({"other_preference": "preserved"}), encoding="utf-8")
    assert client.post(ENDPOINT, params={"batch_id": SELECTED}).status_code == 403
    assert "production_batch_id" not in json.loads(preference.read_text(encoding="utf-8"))

    response = client.post(ENDPOINT, params={"batch_id": SELECTED}, headers=headers)
    assert response.status_code == 200
    assert response.json() == {"ok": True, "selected_batch_id": SELECTED, "target_per_domain": 10}
    assert json.loads(preference.read_text(encoding="utf-8")) == {
        "other_preference": "preserved",
        "production_batch_id": SELECTED,
    }
    assert {path: path.read_bytes() for path in paths} == original
    assert routes._STATUS_CACHE is None
    assert routes._STREAM_CACHE is None
    assert not list(preference.parent.glob("operator_preferences-*.tmp"))
    assert routes._latest_production_batch()["batch_id"] == SELECTED


@pytest.mark.parametrize(
    ("batch_id", "report", "expected_status"),
    [
        ("../../outside", None, 400),
        ("", None, 400),
        ("production-20260101-000000", None, 404),
        (SELECTED, {"batch_id": NEWER, "target_per_domain": 10}, 409),
        (SELECTED, {"batch_id": SELECTED, "target_per_domain": True}, 409),
        (SELECTED, {"batch_id": SELECTED, "target_per_domain": 21}, 409),
        (SELECTED, {"batch_id": SELECTED, "target_per_domain": "10"}, 409),
        (SELECTED, {"batch_id": SELECTED}, 409),
        (SELECTED, [], 409),
        (SELECTED, "malformed JSON", 409),
    ],
)
def test_invalid_selection_does_not_write_preferences(selection, batch_id, report, expected_status):
    client, headers, reports, registry = selection
    if report is not None:
        raw = report if isinstance(report, str) else json.dumps(report)
        (reports / f"{SELECTED}.json").write_text(raw, encoding="utf-8")
    original_registry = registry.read_bytes()
    response = client.post(ENDPOINT, params={"batch_id": batch_id}, headers=headers)
    assert response.status_code == expected_status
    assert not routes._operator_preferences_path().exists()
    assert registry.read_bytes() == original_registry


def test_persisted_selection_survives_cache_reset_and_active_production_takes_precedence(
    selection, monkeypatch
):
    client, headers, _reports, _registry = selection
    client.post(ENDPOINT, params={"batch_id": SELECTED}, headers=headers).raise_for_status()
    assert routes._latest_production_batch()["batch_id"] == SELECTED
    monkeypatch.setattr(routes, "_STATUS_CACHE", None)
    monkeypatch.setattr(routes, "_STREAM_CACHE", None)
    assert routes._latest_production_batch()["batch_id"] == SELECTED
    monkeypatch.setattr(routes, "_pid_alive", lambda *args: True)
    assert routes._latest_production_batch()["batch_id"] == NEWER
    assert routes._load_operator_preferences()["production_batch_id"] == SELECTED
    monkeypatch.setattr(routes, "_pid_alive", lambda *args: False)
    assert routes._latest_production_batch()["batch_id"] == SELECTED


@pytest.mark.parametrize("preference", ["../../outside", "production-20260101-000000", None])
def test_invalid_persisted_preference_falls_back_to_tracked_batch(selection, preference):
    routes._operator_preferences_path().write_text(
        json.dumps({"production_batch_id": preference}), encoding="utf-8"
    )
    assert routes._latest_production_batch()["batch_id"] == NEWER


@pytest.mark.parametrize("collector", ["status", "stream"])
def test_inflight_old_snapshot_cannot_replace_selection_cache(selection, monkeypatch, collector):
    def change_selection():
        routes._select_production_batch(SELECTED)
        return {"production_batch": {"batch_id": NEWER}}

    if collector == "status":
        monkeypatch.setattr(routes, "_status_payload", change_selection)
        routes.STATUS_CACHE_LOCK.acquire()
        routes._refresh_status_cache()
        assert routes._STATUS_CACHE is None
        assert not routes.STATUS_CACHE_LOCK.locked()
    else:
        monkeypatch.setattr(routes, "_cached_status_payload", change_selection)
        monkeypatch.setattr(routes, "_collect_telemetry_gauges", lambda: {})
        monkeypatch.setattr(routes, "_collect_workers_snapshots", lambda: [])
        routes.STREAM_REFRESH_LOCK.acquire()
        routes._refresh_stream_snapshot()
        assert routes._STREAM_CACHE is None
        assert not routes.STREAM_REFRESH_LOCK.locked()
    assert routes._latest_production_batch()["batch_id"] == SELECTED


def test_atomic_preference_write_failure_preserves_previous_selection(selection, monkeypatch):
    client, headers, _reports, _registry = selection
    path = routes._operator_preferences_path()
    previous = json.dumps({"production_batch_id": NEWER})
    path.write_text(previous, encoding="utf-8")
    original_replace = type(path).replace

    def fail_preference_replace(self, target):
        if target == path:
            raise OSError("disk unavailable")
        return original_replace(self, target)

    monkeypatch.setattr(type(path), "replace", fail_preference_replace)
    response = client.post(ENDPOINT, params={"batch_id": SELECTED}, headers=headers)
    assert response.status_code == 409
    assert path.read_text(encoding="utf-8") == previous
    assert not list(path.parent.glob("operator_preferences-*.tmp"))
