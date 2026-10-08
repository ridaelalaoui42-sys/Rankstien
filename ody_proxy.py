#!/usr/bin/env python3
"""
Odysseus Proxy — lightweight OpenAI-compatible proxy for Gemini via CLI OAuth.
Listens on 127.0.0.1:8000/gemini/v1/chat/completions.

Uses Gemini CLI with OAuth credentials (~/.gemini/oauth_creds.json and
account_*.json files) — NO API keys required.

This is a standalone fallback proxy for when the full Odysseus server
(port 7000) is not running.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

# ─── Account pool (round-robin rotation with cooldowns) ───────────────────

GEMINI_DIR = Path.home() / ".gemini"

# Models we advertise — Gemini 3-family OAuth models only.
KNOWN_MODELS = {
    "gemini-3.5-flash",
    "gemini-3.1-pro-preview",
    "gemini-3.1-flash-lite",
    "gemini-3.1-flash-lite-preview",
    "gemini-3-pro-preview",
    "gemini-3-flash-preview",
}


class AccountPool:
    def __init__(self):
        self._lock = threading.Lock()
        self._robin_idx = 0
        self._cooldowns: dict[str, float] = {}
        self._cooldown_seconds = 60

    def discover(self) -> list[tuple[str, Path]]:
        accounts = []
        p0 = GEMINI_DIR / "oauth_creds.json"
        if p0.exists():
            accounts.append(("account_0", p0))
        for f in sorted(GEMINI_DIR.glob("account_*.json")):
            key = f.stem
            if key == "account_0":
                continue
            accounts.append((key, f))
        return accounts

    def mark_rate_limited(self, key: str) -> None:
        with self._lock:
            self._cooldowns[key] = time.time() + self._cooldown_seconds
            print(f"[COOLDOWN] Account '{key}' rate-limited for {self._cooldown_seconds}s")

    def get_next(self) -> tuple[str, Path] | None:
        accounts = self.discover()
        if not accounts:
            return None
        n = len(accounts)
        with self._lock:
            start = self._robin_idx
            self._robin_idx = (self._robin_idx + 1) % n
        for offset in range(n):
            idx = (start + offset) % n
            key, path = accounts[idx]
            if self._cooldowns.get(key, 0) < time.time():
                return key, path
        # All in cooldown — clear and use first
        with self._lock:
            self._cooldowns.clear()
        return accounts[0]


_pool = AccountPool()


# ─── Gemini CLI invocation ────────────────────────────────────────────────


def _find_gemini_cmd() -> str:
    """Find the gemini CLI executable."""
    for name in ("gemini.cmd", "gemini"):
        path = shutil.which(name)
        if path:
            return path
    # Fallback: try npx
    npx = shutil.which("npx")
    if npx:
        return f"{npx} -y @anthropic-ai/gemini-cli"
    return "gemini"


GEMINI_CMD = _find_gemini_cmd()
print(f"Gemini CLI: {GEMINI_CMD}")


def _run_gemini_cli(model: str, prompt: str, account_key: str, account_path: Path) -> dict:
    """Invoke Gemini CLI with OAuth credentials in a temp home dir."""
    tmp_dir = os.path.join(tempfile.gettempdir(), f"ody_proxy_{uuid.uuid4().hex[:8]}")
    try:
        gem_dir = os.path.join(tmp_dir, ".gemini")
        os.makedirs(gem_dir, exist_ok=True)

        # Copy settings if they exist
        settings_src = GEMINI_DIR / "settings.json"
        if settings_src.exists():
            shutil.copy(settings_src, os.path.join(gem_dir, "settings.json"))

        # Copy the target account's OAuth credentials
        shutil.copy(account_path, os.path.join(gem_dir, "oauth_creds.json"))

        env = os.environ.copy()
        env["USERPROFILE"] = tmp_dir
        env["HOME"] = tmp_dir
        env["GEMINI_CLI_TRUST_WORKSPACE"] = "true"
        # Remove any API keys — force OAuth only
        for key in ("GOOGLE_API_KEY", "GEMINI_API_KEY", "MCP_GEMINI_API_KEY", "MCP_GOOGLE_API_KEY"):
            env.pop(key, None)

        cmd = [GEMINI_CMD, "--yolo", "--skip-trust", "-o", "stream-json", "-p", ""]
        if model.lower() != "auto":
            cmd.extend(["-m", model])

        proc = subprocess.run(
            cmd,
            input=prompt.encode("utf-8"),
            capture_output=True,
            timeout=600,
            env=env,
            cwd=tmp_dir,
        )

        # Parse stream-json output
        full_content = ""
        error_msg = None
        for line in proc.stdout.decode("utf-8", errors="replace").splitlines():
            if not line.strip():
                continue
            try:
                data = json.loads(line)
                if data.get("type") == "message" and data.get("role") == "assistant":
                    content = data.get("content", "")
                    reasoning = data.get("reasoning_content", "")
                    if reasoning:
                        full_content += f"<think>\n{reasoning}\n</think>\n\n"
                    if content:
                        full_content += content
                elif data.get("type") == "result":
                    if data.get("status") == "error":
                        error_msg = data.get("error", {}).get("message", "Unknown CLI error")
                        if "exhausted" in error_msg.lower() or "429" in error_msg:
                            _pool.mark_rate_limited(account_key)
            except json.JSONDecodeError:
                continue

        if error_msg and not full_content:
            return {"success": False, "error": error_msg, "rate_limited": "exhausted" in error_msg.lower()}
        if full_content:
            return {"success": True, "content": full_content, "account": account_key}

        # Fallback: check raw stdout (non-JSON mode)
        raw = proc.stdout.decode("utf-8", errors="replace").strip()
        if raw and len(raw) > 50:
            return {"success": True, "content": raw, "account": account_key}

        stderr_text = proc.stderr.decode("utf-8", errors="replace").strip()
        if "exhausted" in stderr_text.lower() or "429" in stderr_text:
            _pool.mark_rate_limited(account_key)
            return {"success": False, "error": "Rate limited", "rate_limited": True}

        return {"success": False, "error": stderr_text or "Empty output from Gemini CLI"}

    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


# ─── HTTP handler ─────────────────────────────────────────────────────────


class ProxyHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        ts = time.strftime("%H:%M:%S")
        # args is (request_line, status_code, size) — protect against missing
        parts = [str(a) for a in args]
        print(f"[{ts}] {' '.join(parts)}")

    def do_GET(self):
        if self.path == "/health":
            accounts = _pool.discover()
            self._json_response(
                {
                    "status": "ok",
                    "auth": "oauth",
                    "accounts": len(accounts),
                    "gemini_cmd": GEMINI_CMD,
                }
            )
        elif self.path == "/gemini/v1/models":
            now = int(time.time())
            models = [
                {"id": m, "object": "model", "created": now, "owned_by": "google"}
                for m in sorted(KNOWN_MODELS)
                if m != "auto"
            ]
            self._json_response({"object": "list", "data": models})
        else:
            self._json_response({"error": "not found"}, 404)

    def do_POST(self):
        if self.path != "/gemini/v1/chat/completions":
            return self._json_response({"error": "not found"}, 404)

        body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            return self._json_response({"error": "invalid json"}, 400)

        model = data.get("model", "gemini-3.1-flash-lite-preview")
        messages = data.get("messages", [])
        stream = data.get("stream", False)

        # Build prompt from messages
        prompt_parts = []
        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            prompt_parts.append(f"{role.capitalize()}: {content}")
        prompt_text = "\n\n".join(prompt_parts)

        # Try each available account
        accounts = _pool.discover()
        max_attempts = max(len(accounts), 1)
        last_error = "No OAuth accounts found"

        for attempt in range(max_attempts):
            result = _pool.get_next()
            if not result:
                break
            account_key, account_path = result

            print(f"[{time.strftime('%H:%M:%S')}] model={model} account={account_key} attempt={attempt + 1}")
            cli_result = _run_gemini_cli(model, prompt_text, account_key, account_path)

            if cli_result.get("success"):
                text = cli_result["content"]
                openai_response = {
                    "id": f"chatcmpl-{uuid.uuid4().hex[:12]}",
                    "object": "chat.completion",
                    "created": int(time.time()),
                    "model": model,
                    "choices": [
                        {
                            "index": 0,
                            "message": {"role": "assistant", "content": text},
                            "finish_reason": "stop",
                        }
                    ],
                }

                if stream:
                    self.send_response(200)
                    self.send_header("Content-Type", "text/event-stream")
                    self.send_header("Cache-Control", "no-cache")
                    self.end_headers()
                    chunk = json.dumps({"choices": [{"delta": {"content": text}}]})
                    self.wfile.write(f"data: {chunk}\n\n".encode())
                    self.wfile.write(b"data: [DONE]\n\n")
                else:
                    self._json_response(openai_response)
                return

            last_error = cli_result.get("error", "Unknown error")
            if cli_result.get("rate_limited"):
                continue  # try next account
            break  # non-retryable error

        self._json_response(
            {
                "error": {"message": last_error, "type": "proxy_error"},
                "choices": [{"message": {"content": ""}}],
            },
            502,
        )

    def _json_response(self, data, status=200):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())


# ─── Main ─────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    accounts = _pool.discover()
    if not accounts:
        print("ERROR: No OAuth credential files found in ~/.gemini/")
        print("  Expected: ~/.gemini/oauth_creds.json or ~/.gemini/account_*.json")
        print("  Run 'gemini' once to authenticate, then copy oauth_creds.json to account_1.json etc.")
        sys.exit(1)

    print("Odysseus Proxy starting on 127.0.0.1:8000 (OAuth mode)")
    print(f"  Accounts found: {len(accounts)} ({', '.join(k for k, _ in accounts)})")
    print(f"  Gemini CLI: {GEMINI_CMD}")
    print("  Endpoint: POST /gemini/v1/chat/completions")
    print()

    server = ThreadingHTTPServer(("127.0.0.1", 8000), ProxyHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down...")
        server.server_close()
