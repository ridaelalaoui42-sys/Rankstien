import json
import logging
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import requests

logger = logging.getLogger("rankstein.memory")


class MemoryService:
    """Small REST client for the AgentMemory runtime."""

    def __init__(
        self,
        base_url: str | None = None,
        project: str = "rankstein",
        cwd: str | None = None,
        timeout: float = 8,
    ):
        self.base_url = (base_url or os.environ.get("AGENTMEMORY_URL") or "http://127.0.0.1:3111").rstrip("/")
        self.secret = os.environ.get("AGENTMEMORY_SECRET", "")
        self.project = project
        self.cwd = cwd or str(Path(__file__).resolve().parents[2])
        self.timeout = timeout

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.secret:
            headers["Authorization"] = f"Bearer {self.secret}"
        return headers

    def _url(self, path: str) -> str:
        return f"{self.base_url}/agentmemory/{path.lstrip('/')}"

    def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        resp = requests.post(self._url(path), json=payload, headers=self._headers(), timeout=self.timeout)
        if resp.status_code not in {200, 201}:
            raise RuntimeError(f"AgentMemory {path} returned {resp.status_code}: {resp.text[:300]}")
        return resp.json() if resp.content else {}

    def health(self) -> dict[str, Any]:
        """Return AgentMemory health information, or a structured error."""
        try:
            resp = requests.get(self._url("health"), headers=self._headers(), timeout=self.timeout)
            body = resp.json() if resp.content else {}
            body.setdefault("ok", resp.status_code == 200)
            body.setdefault("status_code", resp.status_code)
            return body
        except Exception as e:
            logger.error("AgentMemory health check failed: %s", e)
            return {"ok": False, "error": str(e), "base_url": self.base_url}

    def remember(
        self,
        content: str,
        concepts: list[str] | None = None,
        type: str = "semantic",
        files: list[str] | None = None,
    ) -> dict[str, Any]:
        """
        Persist a durable memory.
        Types:
        - working: Transient, short-term state.
        - episodic: Successes, failures, specific events.
        - semantic: General facts, rules, patterns.
        - procedural: Step-by-step instructions or workflows.
        """
        payload = {"content": content, "concepts": concepts or [], "type": type, "files": files or []}
        try:
            result = self._post("remember", payload)
            result.setdefault("success", True)
            return result
        except Exception as e:
            logger.error("Failed to persist AgentMemory memory: %s", e)
            return {"success": False, "error": str(e)}

    def observe(
        self,
        content: str,
        concepts: list[str] | None = None,
        type: str = "semantic",
        files: list[str] | None = None,
        hook_type: str = "rankstein_memory",
    ) -> dict[str, Any]:
        """Record a session observation in AgentMemory."""
        payload = {
            "hookType": hook_type,
            "sessionId": f"rankstein-{datetime.now(UTC).strftime('%Y%m%d')}",
            "project": self.project,
            "cwd": self.cwd,
            "timestamp": datetime.now(UTC).isoformat(),
            "data": {
                "content": content,
                "concepts": concepts or [],
                "type": type,
                "files": files or [],
            },
        }
        try:
            result = self._post("observe", payload)
            result.setdefault("success", True)
            return result
        except Exception as e:
            logger.error("Failed to record AgentMemory observation: %s", e)
            return {"success": False, "error": str(e)}

    def relate(self, source_id: str, target_id: str, relation: str) -> bool:
        """Create a Knowledge Graph relationship between two memories."""
        payload = {"source": source_id, "target": target_id, "relation": relation}
        try:
            resp = requests.post(
                self._url("relate"), json=payload, headers=self._headers(), timeout=self.timeout
            )
            return resp.status_code == 200
        except Exception:
            return False

    def search(self, query: str, limit: int = 5) -> list[dict[str, Any]]:
        """Search for relevant memories using hybrid retrieval."""
        payload = {"query": query, "limit": limit}
        try:
            data = self._post("smart-search", payload)
            if isinstance(data, list):
                return data
            results = data.get("results") or data.get("memories") or data.get("items") or []
            return results if isinstance(results, list) else []
        except Exception as e:
            logger.error("AgentMemory search failed: %s", e)
            return []

    def log_event(
        self, event_type: str, message: str, metadata: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Helper to log episodic events (success/failure)."""
        content = f"[{event_type.upper()}] {message}"
        if metadata:
            content += f" | Metadata: {json.dumps(metadata)}"

        concepts = ["event", event_type]
        if metadata:
            concepts.extend(metadata.keys())

        return self.observe(content=content, concepts=sorted(set(concepts)), type="episodic")


# Singleton instance
memory = MemoryService()
