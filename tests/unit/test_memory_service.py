from backend.services.memory_service import MemoryService


class DummyResponse:
    def __init__(self, status_code=200, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload or {}
        self.text = text
        self.content = b"{}"

    def json(self):
        return self._payload


def test_memory_service_uses_agentmemory_paths(monkeypatch):
    calls = []

    def fake_post(url, json, headers, timeout):
        calls.append((url, json, headers, timeout))
        return DummyResponse(201, {"id": "mem_1"})

    monkeypatch.setattr("backend.services.memory_service.requests.post", fake_post)

    service = MemoryService(base_url="http://127.0.0.1:3111", project="rankstein", cwd="C:/repo")
    result = service.remember("Pinterest upload retries need fresh Firefox state", ["pinterest"], "semantic")

    assert result["success"] is True
    assert calls[0][0] == "http://127.0.0.1:3111/agentmemory/remember"
    assert calls[0][1]["concepts"] == ["pinterest"]


def test_observe_wraps_rankstein_events_for_agentmemory(monkeypatch):
    payloads = []

    def fake_post(url, json, headers, timeout):
        payloads.append(json)
        return DummyResponse(201, {"stored": True})

    monkeypatch.setattr("backend.services.memory_service.requests.post", fake_post)

    service = MemoryService(base_url="http://127.0.0.1:3111", project="rankstein", cwd="C:/repo")
    result = service.observe("quality gate failed", ["quality"], "episodic")

    assert result["success"] is True
    payload = payloads[0]
    assert payload["project"] == "rankstein"
    assert payload["cwd"] == "C:/repo"
    assert payload["data"]["content"] == "quality gate failed"


def test_search_handles_agentmemory_result_shapes(monkeypatch):
    def fake_post(url, json, headers, timeout):
        return DummyResponse(200, {"results": [{"content": "remember this"}]})

    monkeypatch.setattr("backend.services.memory_service.requests.post", fake_post)

    service = MemoryService(base_url="http://127.0.0.1:3111")

    assert service.search("pinning", 3) == [{"content": "remember this"}]
