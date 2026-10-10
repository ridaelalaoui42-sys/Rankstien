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
    monkeypatch.setattr(routes, "_latest_production_batch", lambda: None)
    monkeypatch.setattr(routes, "_load_processes", lambda: {})
    monkeypatch.setattr(routes, "_action_snapshots", lambda _: {})
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


@pytest.mark.parametrize("killed", [True, False])
def test_stop_records_only_confirmed_owned_processes(client, monkeypatch, killed):
    registry = {"production": {"pid": 123, "command": ["python", "production"], "started_at": 10}}
    saved = []
    monkeypatch.setattr(routes, "_load_processes", lambda: registry)
    monkeypatch.setattr(routes, "_pid_alive", lambda *args: True)
    monkeypatch.setattr(routes, "_kill_pid_tree", lambda pid: killed)
    monkeypatch.setattr(routes, "_save_processes", saved.append)
    token = client.get("/api/operator/session").json()["csrf_token"]
    response = client.post("/api/rankstein/control/stop/production", headers={"X-RankStein-CSRF": token})
    if killed:
        assert response.status_code == 200
        assert response.json()["stopped"] is True
        assert saved[0]["production"]["stop_requested"] is True
    else:
        assert response.status_code == 503
        assert saved == []
        assert "stop_requested" not in registry["production"]


def test_stopping_finished_or_reused_pid_does_not_erase_outcome(client, monkeypatch):
    registry = {"production": {"pid": 123, "returncode": 0, "finished_at": 20}}
    monkeypatch.setattr(routes, "_load_processes", lambda: registry)
    monkeypatch.setattr(routes, "_pid_alive", lambda *args: False)
    monkeypatch.setattr(routes, "_kill_pid_tree", lambda pid: pytest.fail("Must not kill an unowned PID"))
    monkeypatch.setattr(routes, "_save_processes", lambda data: pytest.fail("Must preserve terminal history"))
    token = client.get("/api/operator/session").json()["csrf_token"]
    response = client.post("/api/rankstein/control/stop/production", headers={"X-RankStein-CSRF": token})
    assert response.json()["stopped"] is False
    assert registry["production"]["returncode"] == 0


def test_stop_rejects_unknown_modes(client):
    token = client.get("/api/operator/session").json()["csrf_token"]
    response = client.post("/api/rankstein/control/stop/unknown", headers={"X-RankStein-CSRF": token})
    assert response.status_code == 404


def test_accounts_cohorts_endpoint(client):
    response = client.get("/api/rankstein/accounts/cohorts")
    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    assert isinstance(data["accounts"], list)
    assert isinstance(data["domains"], list)


def test_save_and_connect_pinterest_account(client, tmp_path, monkeypatch):
    test_file = tmp_path / "pinterest_accounts.json"
    monkeypatch.setattr(routes, "_get_accounts_file_path", lambda: test_file)

    token = client.get("/api/operator/session").json()["csrf_token"]
    save_resp = client.post(
        "/api/rankstein/control/accounts/save",
        headers={"X-RankStein-CSRF": token},
        json={
            "handle": "unit_acc_1",
            "email": "test1@domain.com",
            "browser": "chromium",
            "connected_domains": ["recetadolce"],
        },
    )
    assert save_resp.status_code == 200
    assert save_resp.json()["ok"] is True

    # Connect to another blog
    conn_resp = client.post(
        "/api/rankstein/control/accounts/connect-blog",
        headers={"X-RankStein-CSRF": token},
        json={
            "account_handle": "unit_acc_1",
            "domain_handle": "recetagenial",
            "connected": True,
        },
    )
    assert conn_resp.status_code == 200
    assert "unit_acc_1" in conn_resp.json()["domain_account_map"]["recetagenial"]

    # Delete account
    del_resp = client.post(
        "/api/rankstein/control/accounts/delete",
        headers={"X-RankStein-CSRF": token},
        json={"handle": "unit_acc_1"},
    )
    assert del_resp.status_code == 200
    assert del_resp.json()["ok"] is True


def test_service_action_supervisor_scaling(client, monkeypatch):
    captured_cmd = []

    class DummyProc:
        pid = 7788

    monkeypatch.setattr(routes, "_stop_process", lambda svc: None)
    monkeypatch.setattr(routes, "_start_background", lambda svc, cmd: (captured_cmd.extend(cmd), DummyProc())[1])

    token = client.get("/api/operator/session").json()["csrf_token"]
    resp = client.post(
        "/api/rankstein/services/supervisor/action",
        headers={"X-RankStein-CSRF": token},
        json={"action": "restart", "workers": 6},
    )
    assert resp.status_code == 200
    assert resp.json()["ok"] is True
    assert "--workers" in captured_cmd
    assert "6" in captured_cmd


def test_clear_drafts_endpoint(client, monkeypatch):
    called = []

    def fake_run(cmd, **kwargs):
        called.append(cmd)
        from subprocess import CompletedProcess
        return CompletedProcess(cmd, 0, stdout="Finished clearing drafts for 2 accounts: [{'account': 'rida', 'deleted': 5}]", stderr="")

    import subprocess
    monkeypatch.setattr(subprocess, "run", fake_run)

    token = client.get("/api/operator/session").json()["csrf_token"]
    resp = client.post(
        "/api/rankstein/control/clear-drafts",
        headers={"X-RankStein-CSRF": token},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert "Pinterest drafts cleared successfully" in data["message"]
    assert len(called) == 1
    assert "clear_pinterest_drafts.py" in str(called[0][1])


