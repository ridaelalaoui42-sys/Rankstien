import gzip
import os
import time

from scripts.dev import runtime_maintenance as maintenance


def test_maintenance_never_removes_active_profile_cache(tmp_path, monkeypatch):
    profile = tmp_path / "data/sessions/account"
    cache = profile / "Default/Cache"
    cache.mkdir(parents=True)
    (cache / "data").write_bytes(b"cache")
    monkeypatch.setattr(maintenance, "active_profiles", lambda: ([profile.resolve()], False))
    assert maintenance.plan(tmp_path) == []


def test_inactive_cache_cleanup_preserves_cookies(tmp_path, monkeypatch):
    profile = tmp_path / "data/sessions/account/Default"
    cache = profile / "Cache"
    cache.mkdir(parents=True)
    (cache / "data").write_bytes(b"rebuildable")
    cookies = profile / "Cookies"
    cookies.write_bytes(b"preserved")
    monkeypatch.setattr(maintenance, "active_profiles", lambda: ([], False))
    result = maintenance.apply(maintenance.plan(tmp_path), tmp_path)
    assert all(item["ok"] for item in result)
    assert not cache.exists()
    assert cookies.read_bytes() == b"preserved"


def test_unknown_browser_ownership_blocks_cache_cleanup(tmp_path, monkeypatch):
    cache = tmp_path / "data/sessions/account/Cache"
    cache.mkdir(parents=True)
    monkeypatch.setattr(maintenance, "active_profiles", lambda: ([], True))
    assert maintenance.plan(tmp_path) == []


def test_rotated_log_compression_is_lossless(tmp_path, monkeypatch):
    log = tmp_path / "data/logs/operator/worker.20200101.log"
    log.parent.mkdir(parents=True)
    content = b"useful diagnostic\n" * 100
    log.write_bytes(content)
    os.utime(log, (time.time() - 7200,) * 2)
    monkeypatch.setattr(maintenance, "active_profiles", lambda: ([], False))
    result = maintenance.apply(maintenance.plan(tmp_path), tmp_path)
    assert result[0]["ok"]
    assert not log.exists()
    assert gzip.open(log.with_name(log.name + ".gz"), "rb").read() == content


def test_apply_rechecks_active_profiles(tmp_path, monkeypatch):
    cache = tmp_path / "data/sessions/account/Cache"
    cache.mkdir(parents=True)
    monkeypatch.setattr(maintenance, "active_profiles", lambda: ([], False))
    items = maintenance.plan(tmp_path)
    monkeypatch.setattr(maintenance, "active_profiles", lambda: ([cache.parent.resolve()], False))
    assert not maintenance.apply(items, tmp_path)[0]["ok"]
    assert cache.exists()


def test_outside_target_is_rejected(tmp_path):
    result = maintenance.apply([{"path": str(tmp_path.parent / "Cache"), "kind": "browser_cache"}], tmp_path)
    assert not result[0]["ok"]
