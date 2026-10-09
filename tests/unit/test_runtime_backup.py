import json
import sqlite3
from pathlib import Path

import pytest

from scripts.dev.runtime_backup import checked_path, snapshot, verify_restore


def test_online_backup_and_isolated_restore_include_wal(tmp_path):
    database = tmp_path / "data/queue/jobs.db"
    database.parent.mkdir(parents=True)
    with sqlite3.connect(database) as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("CREATE TABLE jobs (id INTEGER)")
        conn.execute("INSERT INTO jobs VALUES (42)")
        conn.commit()
        report = snapshot(tmp_path)
        backup = Path(report["snapshot"])
        with sqlite3.connect(backup / "data/queue/jobs.db") as restored:
            assert restored.execute("SELECT id FROM jobs").fetchone() == (42,)
        assert verify_restore(backup)["isolated_restore"]
        assert conn.execute("SELECT id FROM jobs").fetchone() == (42,)


def test_tampered_snapshot_is_rejected(tmp_path):
    path = tmp_path / "data/app.db"
    path.parent.mkdir(parents=True)
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE example (id INTEGER)")
    backup = Path(snapshot(tmp_path)["snapshot"])
    (backup / "data/app.db").write_bytes(b"tampered")
    with pytest.raises(ValueError, match="checksum"):
        verify_restore(backup)


def test_no_credentials_or_profiles_in_snapshot(tmp_path):
    (tmp_path / "data").mkdir()
    (tmp_path / ".env").write_text("SECRET=private")
    report = snapshot(tmp_path)
    manifest = json.loads((Path(report["snapshot"]) / "manifest.json").read_text())
    assert manifest["credentials_included"] is False
    assert manifest["profiles_included"] is False
    assert not (Path(report["snapshot"]) / ".env").exists()


def test_restore_paths_cannot_escape(tmp_path):
    with pytest.raises(ValueError, match="outside"):
        checked_path(tmp_path, "../outside.db")
