import asyncio
import json
import logging
import os
import subprocess
from pathlib import Path
from typing import Any

logger = logging.getLogger("rankstein.mcp_client")


class MCPClient:
    """
    Robust MCP Client for RankStein.
    Manages a persistent connection to an MCP server (like playwright-mcp).
    """

    def __init__(self, command: list[str]):
        self.command = command
        self.process: asyncio.subprocess.Process | None = None
        self._request_id = 1
        self._initialized = False

    async def connect(self):
        """Connect to the MCP server and perform initialization."""
        if self.process:
            return

        logger.info(f"Connecting to MCP server: {' '.join(self.command)}")
        self.process = await asyncio.create_subprocess_exec(
            *self.command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        # 1. Initialize
        init_res = await self._send_request(
            "initialize",
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "RankStein-Client", "version": "1.0.0"},
            },
        )

        if not init_res:
            raise RuntimeError("Failed to initialize MCP server")

        # 2. Notifications/initialized
        await self._send_notification("notifications/initialized")

        self._initialized = True
        logger.info("MCP server connected and initialized")

    async def disconnect(self):
        """Disconnect from the MCP server."""
        if self.process:
            try:
                self.process.terminate()
                await self.process.wait()
            except:
                pass
            self.process = None
            self._initialized = False

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Call a tool on the MCP server."""
        if not self._initialized:
            await self.connect()

        res = await self._send_request("tools/call", {"name": name, "arguments": arguments})
        return res if res else {}

    async def _send_request(self, method: str, params: dict[str, Any]) -> dict[str, Any] | None:
        if not self.process or not self.process.stdin:
            return None

        req_id = self._request_id
        self._request_id += 1

        request = {"jsonrpc": "2.0", "id": req_id, "method": method, "params": params}

        data = json.dumps(request) + "\n"
        self.process.stdin.write(data.encode())
        await self.process.stdin.drain()

        # Buffer-and-decode loop:
        # MCP servers may emit notification frames (no "id") before the actual reply,
        # and long JSON payloads may be split across multiple readline() calls.
        # We accumulate bytes until json.JSONDecoder.raw_decode succeeds, then check
        # that the decoded frame belongs to our request.  We skip notification frames
        # and keep reading until we find our id or the stream closes.
        decoder = json.JSONDecoder()
        buf = ""
        while True:
            try:
                chunk = await asyncio.wait_for(self.process.stdout.readline(), timeout=120)
            except TimeoutError:
                logger.error(f"MCP response timeout for request {req_id} ({method})")
                return None
            if not chunk:
                logger.error(f"MCP stdout closed while waiting for request {req_id}")
                return None

            buf += chunk.decode(errors="replace")
            # Try to extract complete JSON objects from the buffer
            buf = buf.lstrip()
            while buf:
                try:
                    obj, end_idx = decoder.raw_decode(buf)
                    buf = buf[end_idx:].lstrip()
                except json.JSONDecodeError:
                    # Incomplete - need more data
                    break

                frame_id = obj.get("id")
                if frame_id is None:
                    # Server notification (no id) - log and skip
                    logger.debug(f"MCP notification: {obj.get('method', '?')}")
                    continue
                if frame_id != req_id:
                    # Response for a different request (shouldn't happen with single-threaded use)
                    logger.warning(f"MCP: got response for id={frame_id}, expected {req_id}")
                    continue
                # This is our response
                if "error" in obj:
                    logger.error(f"MCP Error for {method}: {obj['error']}")
                    return None
                return obj.get("result")

    async def _send_notification(self, method: str, params: dict[str, Any] | None = None):
        if not self.process or not self.process.stdin:
            return

        request = {
            "jsonrpc": "2.0",
            "method": method,
        }
        if params:
            request["params"] = params

        data = json.dumps(request) + "\n"
        self.process.stdin.write(data.encode())
        await self.process.stdin.drain()


# Singleton-ish factory keyed by browser/session.
_clients: dict[tuple[str, str], MCPClient] = {}


def get_mcp_client(session="pinterest_rida_v7", browser: str | None = None) -> MCPClient:
    browser_name = (browser or os.environ.get("PINTEREST_BROWSER") or "firefox").lower().strip()
    key = (browser_name, session)
    if key not in _clients:
        project_root = Path(__file__).resolve().parent.parent
        session_dir = project_root / "data" / "sessions" / session

        # Use npx to run playwright-mcp directly from global or cached installation
        cmd = [
            "npx.cmd",
            "-y",
            "@playwright/mcp",
            "--browser",
            browser_name,
            "--user-data-dir",
            str(session_dir),
            "--allow-unrestricted-file-access",
        ]
        _clients[key] = MCPClient(cmd)
    return _clients[key]
