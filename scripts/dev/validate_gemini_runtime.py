"""Validate the Gemini CLI + MCP runtime configuration.

This is an offline preflight. It checks local executables, MCP server paths,
and RankStein AI-engine settings without calling Gemini, Supabase, or Pinterest.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import urllib.error
import urllib.request
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SETTINGS_FILE = PROJECT_ROOT / ".gemini" / "settings.json"
sys.path.insert(0, str(PROJECT_ROOT))


def _fail(message: str) -> None:
    print(f"[FAIL] {message}")
    raise SystemExit(1)


def _ok(message: str) -> None:
    print(f"[OK] {message}")


def _warn(message: str) -> None:
    print(f"[WARN] {message}")


def _command_exists(command: str) -> bool:
    if Path(command).is_absolute():
        return Path(command).exists()
    return shutil.which(command) is not None


def _validate_server(name: str, server: dict) -> None:
    if server.get("type") == "http":
        if not server.get("url"):
            _fail(f"MCP server '{name}' is missing url")
        _ok(f"MCP server '{name}' uses HTTP endpoint")
        return

    command = str(server.get("command") or "")
    if not command:
        _fail(f"MCP server '{name}' is missing command")
    if not _command_exists(command):
        _fail(f"MCP server '{name}' command not found: {command}")

    args = [str(arg) for arg in server.get("args", [])]
    path_args: list[str] = []
    for index, arg in enumerate(args):
        previous = args[index - 1] if index else ""
        if previous == "--user-data-dir":
            continue
        if arg.startswith("@"):
            continue
        if arg.endswith((".py", ".js", ".cjs", ".mjs")) or "\\" in arg or "/" in arg:
            path_args.append(arg)

    for arg in path_args:
        path = Path(arg)
        if not path.is_absolute():
            path = PROJECT_ROOT / path
        if not path.exists():
            _fail(f"MCP server '{name}' path does not exist: {path}")

    _ok(f"MCP server '{name}' command and paths are valid")


def main() -> int:
    if not SETTINGS_FILE.exists():
        _fail(f"Missing Gemini settings: {SETTINGS_FILE}")

    data = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
    servers = data.get("mcpServers")
    if not isinstance(servers, dict) or not servers:
        _fail(".gemini/settings.json has no mcpServers")

    required = {"rankstein", "playwright_firefox", "playwright_chromium", "nanobanana", "agentmemory"}
    missing = sorted(required - set(servers))
    if missing:
        _fail(f"Missing required MCP servers: {', '.join(missing)}")

    for name, server in servers.items():
        _validate_server(name, server)

    from backend.core.config import get_settings
    from backend.core.engine import resolve_gemini_cli

    settings = get_settings()
    if settings.ai_engine != "gemini_cli":
        _fail(
            f"RANKSTEIN_AI_ENGINE must be gemini_cli for autonomous subscription mode, got {settings.ai_engine}"
        )

    gemini = resolve_gemini_cli(settings.gemini_cli_path)
    if not gemini:
        _fail("Gemini CLI not found. Install/authenticate Gemini CLI or set GEMINI_CLI_PATH.")
    _ok(f"Gemini CLI resolved: {gemini}")
    _ok(f"Primary model: {settings.adk_model}; fallback: {settings.adk_fallback_model}")
    if settings.adk_model != "auto" and not settings.adk_model.startswith("gemini-3"):
        _fail(f"ADK_MODEL must be auto or a Gemini 3/3.1 variant, got {settings.adk_model}")
    if settings.adk_fallback_model and not settings.adk_fallback_model.startswith("gemini-3"):
        _fail(f"RANKSTEIN_FALLBACK_MODEL must be a Gemini 3/3.1 variant, got {settings.adk_fallback_model}")
    inherited_key_names = [name for name in ("GOOGLE_API_KEY", "GEMINI_API_KEY") if os.environ.get(name)]
    if inherited_key_names:
        _warn(
            "Current shell has Gemini/Google API key env vars set; RankStein launchers strip them "
            f"from Gemini CLI subprocesses: {', '.join(inherited_key_names)}"
        )

    agentmemory_url = servers["agentmemory"].get("env", {}).get("AGENTMEMORY_URL", "http://127.0.0.1:3111")
    try:
        headers = {"User-Agent": "rankstein-validator"}
        secret = os.environ.get("AGENTMEMORY_SECRET")
        if not secret:
            secret_path = Path.home() / ".agentmemory" / "secret"
            if secret_path.exists():
                try:
                    secret = secret_path.read_text(encoding="utf-8").strip()
                except OSError:
                    secret = ""
        if secret:
            headers["Authorization"] = f"Bearer {secret}"
        request = urllib.request.Request(f"{agentmemory_url.rstrip('/')}/agentmemory/health", headers=headers)
        with urllib.request.urlopen(request, timeout=5) as response:
            if response.status != 200:
                _fail(f"AgentMemory health returned HTTP {response.status}")
        _ok(f"AgentMemory REST health reachable: {agentmemory_url}")
    except (urllib.error.URLError, TimeoutError) as exc:
        _fail(f"AgentMemory REST is not reachable at {agentmemory_url}: {exc}")

    print("[OK] Gemini CLI + MCP runtime preflight passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
