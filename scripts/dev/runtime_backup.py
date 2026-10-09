"""Private online SQLite snapshots with integrity-checked isolated restore."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sqlite3
import tempfile
import time
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATABASES = (
    "data/queue/jobs.db",
    "data/queue/rate_limiter.db",
    "data/runtime/pipeline_events.db",
    "data/app.db",
    "data/rankstein.db",
)


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def checked_path(root: Path, relative: str) -> Path:
    path = (root / relative).resolve()
    if not path.is_relative_to(root.resolve()) or path == root.resolve():
        raise ValueError("Snapshot path is outside its root")
    return path


def snapshot(root: Path = ROOT, *, include_media: bool = False) -> dict:
    root = root.resolve()
    target = root / "data" / "backups" / datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    target.mkdir(parents=True, exist_ok=False)
    files = []
    for relative in DATABASES:
        source = checked_path(root, relative)
        if not source.is_file():
            continue
        destination = checked_path(target, relative)
        destination.parent.mkdir(parents=True, exist_ok=True)
        started = time.monotonic()

        def progress(_status, _remaining, _total, started=started):
            if time.monotonic() - started > 120:
                raise TimeoutError("Online database backup deadline exceeded")

        with closing(sqlite3.connect(source.as_uri() + "?mode=ro", uri=True, timeout=5)) as connection:
            with closing(sqlite3.connect(destination)) as backup:
                connection.backup(backup, pages=500, progress=progress)
                if backup.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    raise ValueError("Database snapshot integrity check failed")
        files.append({"path": relative, "kind": "sqlite", "sha256": digest(destination)})

    # Domain manifests refer to environment variable names, not their values.
    # Browser sessions and credential files are never exported by this tool.
    metadata = list((root / "data" / "domains").glob("*/keywords.md"))
    for source in metadata:
        relative = source.relative_to(root).as_posix()
        destination = checked_path(target, relative)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        files.append({"path": relative, "kind": "roadmap", "sha256": digest(destination)})

    media_missing = []
    if include_media and (target / "data/queue/jobs.db").exists():
        with closing(sqlite3.connect(target / "data/queue/jobs.db")) as conn:
            rows = conn.execute(
                "SELECT payload_json FROM jobs WHERE status IN ('pending','retry','processing','held')"
            ).fetchall()
        seen = set()
        for (raw,) in rows:
            payload = json.loads(raw)
            image = payload.get("image_path")
            if not image:
                continue
            source = Path(image)
            source = (source if source.is_absolute() else root / source).resolve()
            if not source.is_relative_to(root):
                raise ValueError("Queued media is outside the project; explicit migration is required")
            relative = source.relative_to(root).as_posix()
            if relative in seen:
                continue
            seen.add(relative)
            if not source.is_file():
                media_missing.append(relative)
                continue
            destination = checked_path(target, relative)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
            files.append({"path": relative, "kind": "media", "sha256": digest(destination)})
    manifest = {
        "version": 1,
        "created_at": datetime.now(UTC).isoformat(),
        "files": files,
        "media_included": include_media,
        "missing_media": media_missing,
        "credentials_included": False,
        "profiles_included": False,
    }
    (target / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return {
        "ok": not media_missing,
        "snapshot": str(target),
        "file_count": len(files),
        "missing_media_count": len(media_missing),
        "media_included": include_media,
    }


def verify_restore(snapshot_dir: Path) -> dict:
    source = snapshot_dir.resolve()
    manifest = json.loads((source / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("version") != 1 or not manifest.get("files"):
        raise ValueError("Unsupported or empty snapshot")
    with tempfile.TemporaryDirectory(prefix="rankstein-restore-") as temporary:
        destination = Path(temporary)
        for item in manifest["files"]:
            path = checked_path(source, item["path"])
            if digest(path) != item["sha256"]:
                raise ValueError("Snapshot checksum mismatch")
            restored = checked_path(destination, item["path"])
            restored.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, restored)
            if item["kind"] == "sqlite":
                with closing(sqlite3.connect(restored.as_uri() + "?mode=ro", uri=True)) as conn:
                    if conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                        raise ValueError("Restored database integrity check failed")
    return {
        "ok": not manifest.get("missing_media"),
        "files_verified": len(manifest["files"]),
        "isolated_restore": True,
        "media_included": manifest.get("media_included", False),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    create = commands.add_parser("create")
    create.add_argument("--include-media", action="store_true")
    verify = commands.add_parser("verify")
    verify.add_argument("snapshot", type=Path)
    args = parser.parse_args()
    report = (
        snapshot(include_media=args.include_media)
        if args.command == "create"
        else verify_restore(args.snapshot)
    )
    print(json.dumps(report, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
