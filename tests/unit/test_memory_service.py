from pathlib import Path
from backend.services.memory_service import MemoryService


def test_native_memory_service_remember_and_search(tmp_path: Path):
    db_file = tmp_path / "test_memory.db"
    service = MemoryService(db_path=db_file, project="rankstein", cwd=str(tmp_path))

    # Remember a memory
    res = service.remember("Pinterest upload retries need fresh Chromium state", ["pinterest", "chromium"], "semantic")
    assert res["success"] is True
    assert isinstance(res["id"], int)

    # Search for it
    hits = service.search("Chromium state", limit=5)
    assert len(hits) >= 1
    assert "Pinterest upload" in hits[0]["content"]
    assert "pinterest" in hits[0]["concepts"]


def test_native_memory_service_observe_event(tmp_path: Path):
    db_file = tmp_path / "test_memory.db"
    service = MemoryService(db_path=db_file, project="rankstein", cwd=str(tmp_path))

    # Observe an event
    res = service.observe("quality gate passed with score 100", ["quality"], "episodic")
    assert res["success"] is True
    assert isinstance(res["id"], int)

    # Search event
    hits = service.search("quality gate passed", limit=5)
    assert len(hits) >= 1
    assert "quality gate passed" in hits[0]["content"]


def test_native_memory_service_stats_and_health(tmp_path: Path):
    db_file = tmp_path / "test_memory.db"
    service = MemoryService(db_path=db_file, project="rankstein", cwd=str(tmp_path))

    service.remember("Sample memory", ["sample"])
    stats = service.stats()

    assert stats["ok"] is True
    assert stats["engine"] == "native_sqlite_fts5"
    assert stats["total"] >= 1
    health = service.health()
    assert health["ok"] is True
    assert health["total_memories"] >= 1
