"""Dry-run-first cache cleanup and lossless rotated-log compression."""

from __future__ import annotations

import argparse
import gzip
import json
import re
import shutil
import sys
import time
from pathlib import Path

import psutil

ROOT = Path(__file__).resolve().parents[2]
CACHE_NAMES = {"Cache", "Code Cache", "GPUCache", "ShaderCache", "GrShaderCache", "DawnCache"}
ROTATED_LOG = re.compile(r"(?:\.\d{8}(?:\.\d+)?\.log|\.log\.\d+)$")


def active_profiles() -> tuple[list[Path], bool]:
    profiles = []
    unknown = False
    for process in psutil.process_iter(["name", "cmdline"]):
        try:
            if process.info["name"].lower() not in {
                "chrome.exe",
                "chromium.exe",
                "msedge.exe",
                "firefox.exe",
            }:
                continue
            args = process.info["cmdline"]
            if args is None:
                unknown = True
                continue
            for index, arg in enumerate(args):
                if arg.startswith("--user-data-dir="):
                    profiles.append(Path(arg.split("=", 1)[1]).resolve())
                elif arg in {"--user-data-dir", "-profile"} and index + 1 < len(args):
                    profiles.append(Path(args[index + 1]).resolve())
        except (psutil.Error, OSError, AttributeError):
            unknown = True
    return profiles, unknown


def safe_cache(path: Path, root: Path, profiles: list[Path]) -> bool:
    resolved = path.resolve()
    return (
        not path.is_symlink()
        and resolved.is_relative_to(root.resolve())
        and path.name in CACHE_NAMES
        and not any(
            resolved.is_relative_to(profile) or profile.is_relative_to(resolved) for profile in profiles
        )
    )


def plan(root: Path = ROOT) -> list[dict]:
    profiles, unknown = active_profiles()
    items = []
    if not unknown:
        session_roots = [root / "data/sessions", *root.glob("data/domains/*/data/sessions")]
        for session_root in session_roots:
            if not session_root.exists():
                continue
            for path in session_root.rglob("*"):
                if path.is_dir() and safe_cache(path, root, profiles):
                    size = sum(p.stat().st_size for p in path.rglob("*") if p.is_file())
                    items.append({"path": str(path), "kind": "browser_cache", "bytes": size})
    for path in (root / "data/logs").rglob("*"):
        if path.is_file() and ROTATED_LOG.search(path.name) and time.time() - path.stat().st_mtime > 3600:
            if path.resolve().is_relative_to(root.resolve()) and not path.is_symlink():
                items.append({"path": str(path), "kind": "compress_log", "bytes": path.stat().st_size})
    return items


def apply(items: list[dict], root: Path = ROOT) -> list[dict]:
    results = []
    for item in items:
        path = Path(item["path"])
        try:
            if not path.resolve().is_relative_to(root.resolve()):
                raise ValueError("Target outside workspace")
            if item["kind"] == "browser_cache":
                profiles, unknown = active_profiles()
                if unknown or not safe_cache(path, root, profiles):
                    raise ValueError("Profile became active or ownership is unknown")
                shutil.rmtree(path)
            elif item["kind"] == "compress_log":
                if not ROTATED_LOG.search(path.name) or time.time() - path.stat().st_mtime <= 3600:
                    raise ValueError("Log is not closed and stable")
                before = path.stat()
                target = path.with_name(path.name + ".gz")
                if target.exists():
                    raise ValueError("Compressed archive already exists")
                with path.open("rb") as source, target.open("xb") as output:
                    with gzip.GzipFile(fileobj=output, mode="wb", compresslevel=1) as archive:
                        shutil.copyfileobj(source, archive)
                after = path.stat()
                if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                    target.unlink()
                    raise ValueError("Log changed during compression")
                with gzip.open(target, "rb") as archive:
                    read_bytes = 0
                    for chunk in iter(lambda: archive.read(1024 * 1024), b""):
                        read_bytes += len(chunk)
                if read_bytes != before.st_size:
                    target.unlink()
                    raise ValueError("Compressed archive validation failed")
                path.unlink()
            else:
                raise ValueError("Unknown operation")
            results.append({**item, "ok": True})
        except (OSError, ValueError) as exc:
            results.append({**item, "ok": False, "error": str(exc)})
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    items = plan()
    report = {
        "applied": args.apply,
        "candidate_count": len(items),
        "candidate_bytes": sum(i["bytes"] for i in items),
    }
    report["items"] = apply(items) if args.apply else items
    report["disk_free_gb"] = round(shutil.disk_usage(ROOT).free / (1024**3), 2)
    print(json.dumps(report, indent=2))
    return 1 if args.apply and any(not i["ok"] for i in report["items"]) else 0


if __name__ == "__main__":
    sys.exit(main())
