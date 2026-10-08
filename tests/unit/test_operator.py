from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from backend.api import operator_routes as routes
from backend.operator import app
from rankstein import suite_controller


@pytest.fixture
def client():
    return TestClient(app, base_url="http://127.0.0.1:7000", client=("127.0.0.1", 1234))


def test_owned_dashboard_and_health(client):
    assert client.get("/health").json()["service"] == "rankstein-operator"
    assert client.get("/").url.path == "/operator"
    response = client.get("/operator")
    assert response.status_code == 200
    assert "RankStein | Operator" in response.text
    assert "Odysseus Hub" not in response.text
    assert "unsafe-eval" not in response.headers["Content-Security-Policy"]
    assert client.get("/operator-assets/operator.js").status_code == 200
    assert client.get("/operator-assets/lucide.min.js").status_code == 200


@pytest.mark.parametrize(
    "headers",
    [{"Host": "evil.example"}, {"Origin": "https://evil.example"}, {"Sec-Fetch-Site": "cross-site"}],
)
def test_blocks_cross_site_reads(client, headers):
    assert client.get("/api/operator/session", headers=headers).status_code == 403


def test_blocks_remote_clients():
    remote = TestClient(app, base_url="http://127.0.0.1:7000", client=("192.0.2.1", 1234))
    assert remote.get("/health").status_code == 403


def test_mutations_require_session(client, monkeypatch):
    monkeypatch.setattr(routes, "_requeue_dlq_jobs", lambda: {"ok": True, "requeued": 2})
    url = "/api/rankstein/control/requeue-dlq"
    assert client.post(url).status_code == 403
    token = client.get("/api/operator/session").json()["csrf_token"]
    assert client.post(url, headers={"X-RankStein-CSRF": token}).json()["requeued"] == 2


def test_domain_bound_start(client, monkeypatch):
    monkeypatch.setattr(routes, "_domains", lambda: [{"handle": "recetagenial"}])
    calls = []
    monkeypatch.setattr(
        routes, "_start_background", lambda mode, command: calls.append(command) or SimpleNamespace(pid=123)
    )
    token = client.get("/api/operator/session").json()["csrf_token"]
    headers = {"X-RankStein-CSRF": token}
    path = "/api/rankstein/control/start/rankstein/production"
    response = client.post(path + "?domain=recetagenial&target_per_domain=2", headers=headers)
    assert response.status_code == 200
    assert "--all-domains" not in calls[0]
    assert calls[0][-2:] == ["--domain", "recetagenial"]
    assert client.post(path + "?domain=unknown", headers=headers).status_code == 400
    assert len(calls) == 1


def test_status_warming_is_truthful(client, monkeypatch):
    monkeypatch.setattr(routes, "_STATUS_CACHE", None)
    monkeypatch.setattr(routes, "_schedule_status_refresh", lambda: False)
    data = client.get("/api/rankstein/status").json()
    assert data["status_refresh"]["state"] == "warming"
    assert data["queue"] == {}
    assert data["pipeline"]["ongoing_campaigns"] == []


def test_suite_uses_owned_operator():
    services = {s.name: s for s in suite_controller.SERVICES}
    assert "frontend" not in services
    assert "odysseus_server" not in services
    assert "backend.operator:app" in services["operator"].cmd
    assert services["operator"].port == 7000


def test_operator_probe_rejects_odysseus(monkeypatch):
    spec = next(s for s in suite_controller.SERVICES if s.name == "operator")
    monkeypatch.setattr(
        suite_controller, "_http_probe", lambda url: {"ok": True, "body": '{"service":"odysseus"}'}
    )
    assert suite_controller._service_probe(spec)["ok"] is False


def test_port_conflict_never_kills(monkeypatch, tmp_path):
    spec = next(s for s in suite_controller.SERVICES if s.name == "operator")
    monkeypatch.setattr(suite_controller, "SERVICES", [spec])
    monkeypatch.setattr(suite_controller, "SERVICES_STATE_FILE", tmp_path / "services.json")
    monkeypatch.setattr(suite_controller, "CAMPAIGN_LEASE_FILE", tmp_path / "lease.json")
    monkeypatch.setattr(suite_controller, "RUNTIME_DIR", tmp_path)
    monkeypatch.setattr(suite_controller, "preflight", lambda: {"ok": True})
    monkeypatch.setattr(suite_controller.log_manager, "maintain", lambda: None)
    monkeypatch.setattr(suite_controller, "_port_open", lambda port: True)
    monkeypatch.setattr(suite_controller, "_service_probe", lambda s: {"ok": False})
    monkeypatch.setattr(
        suite_controller, "_kill_port", lambda port: pytest.fail("Must never kill port owner")
    )
    result = suite_controller.start_services()
    assert result["ok"] is False
    assert "occupied" in result["services"]["operator"]["error"]


def test_logs_tail_and_secret_redaction(monkeypatch, tmp_path):
    monkeypatch.setattr(routes, "LOG_DIR", tmp_path)
    monkeypatch.setenv("TEST_API_KEY", "secret-value-not-for-client")
    (tmp_path / "production.log").write_text(
        "START test\nTEST_API_KEY=secret-value-not-for-client\nBearer abc.def.ghi", encoding="utf-8"
    )
    text, updated = routes._read_action_log("production")
    assert updated > 0
    redacted = routes._redact_log(text)
    assert "secret-value-not-for-client" not in redacted
    assert "abc.def.ghi" not in redacted
    assert "[redacted]" in redacted
