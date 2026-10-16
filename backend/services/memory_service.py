"""Native SQLite-backed Memory Manager for RankStein.

Replaces external agentmemory/iii service with zero-dependency, local, durable,
and thread-safe SQLite storage with FTS5 full-text search.
"""

from __future__ import annotations

import json
import logging
import re
import sqlite3
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger("rankstein.memory")

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data"
DEFAULT_DB_PATH = DATA_DIR / "memory" / "rankstein_memory.db"


class MemoryService:
    """Native Memory Manager storing operational knowledge in SQLite with FTS5."""

    def __init__(self, db_path: Path | str | None = None, project: str = "rankstein"):
        self.db_path = Path(db_path) if db_path else DEFAULT_DB_PATH
        self.project = project
        self._lock = threading.Lock()
        self._ensure_db()

    def _get_connection(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.db_path), timeout=15.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = NORMAL")
        return conn

    def _ensure_db(self) -> None:
        """Create tables and FTS5 indexes if they do not exist."""
        with self._lock:
            conn = self._get_connection()
            try:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS memories (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        content TEXT NOT NULL,
                        type TEXT NOT NULL DEFAULT 'semantic',
                        concepts TEXT NOT NULL DEFAULT '[]',
                        files TEXT NOT NULL DEFAULT '[]',
                        metadata TEXT NOT NULL DEFAULT '{}',
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    )
                    """
                )
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS memory_relations (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        source_id TEXT NOT NULL,
                        target_id TEXT NOT NULL,
                        relation TEXT NOT NULL,
                        created_at TEXT NOT NULL
                    )
                    """
                )
                # Full text search index
                conn.execute(
                    """
                    CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(
                        content,
                        concepts,
                        type,
                        content='memories',
                        content_rowid='id'
                    )
                    """
                )
                # Triggers to keep FTS5 synchronized
                conn.execute(
                    """
                    CREATE TRIGGER IF NOT EXISTS memories_ai AFTER INSERT ON memories BEGIN
                        INSERT INTO memories_fts(rowid, content, concepts, type)
                        VALUES (new.id, new.content, new.concepts, new.type);
                    END;
                    """
                )
                conn.execute(
                    """
                    CREATE TRIGGER IF NOT EXISTS memories_ad AFTER DELETE ON memories BEGIN
                        INSERT INTO memories_fts(memories_fts, rowid, content, concepts, type)
                        VALUES('delete', old.id, old.content, old.concepts, old.type);
                    END;
                    """
                )
                conn.execute(
                    """
                    CREATE TRIGGER IF NOT EXISTS memories_au AFTER UPDATE ON memories BEGIN
                        INSERT INTO memories_fts(memories_fts, rowid, content, concepts, type)
                        VALUES('delete', old.id, old.content, old.concepts, old.type);
                        INSERT INTO memories_fts(rowid, content, concepts, type)
                        VALUES (new.id, new.content, new.concepts, new.type);
                    END;
                    """
                )
                conn.commit()

                # Seed initial foundational lessons if brand new
                cur = conn.execute("SELECT COUNT(*) FROM memories")
                count = cur.fetchone()[0]
                if count == 0:
                    self._seed_foundational_memories(conn)
            finally:
                conn.close()

    def _seed_foundational_memories(self, conn: sqlite3.Connection) -> None:
        """Seed foundational lessons from system operating contracts."""
        now = datetime.now(UTC).isoformat()
        seeds = [
            (
                "Browser engine: Always force Chromium for unattended automation. Firefox profile locks are systemic blockers.",
                "pattern",
                json.dumps(["browser", "chromium", "firefox", "automation"]),
                json.dumps([]),
                json.dumps({"source": "system_contract"}),
                now,
                now,
            ),
            (
                "Pinterest Board Selection: Always use Simplified Pick First logic. Live boards for r1 include Aperitivos, Arroces, Carnes, Chocolate, ENSALADES, Fresas, Pescados. The old recetas board is obsolete.",
                "pattern",
                json.dumps(["pinterest", "boards", "r1", "pick_first"]),
                json.dumps([]),
                json.dumps({"source": "system_contract"}),
                now,
                now,
            ),
            (
                "Publishing to Pinterest: Prioritize Publish Now button. Fallback to Control+Enter after 5s. Success requires a verified pin_id or pin_url.",
                "procedure",
                json.dumps(["pinterest", "publish", "pin_id"]),
                json.dumps([]),
                json.dumps({"source": "system_contract"}),
                now,
                now,
            ),
            (
                "OmniRoute TokenHarbor Wiring: OmniRoute only honors custom URLs via provider nodes (POST /api/provider-nodes). Model must use tokenharbor/deepseek-v4-flash:free.",
                "architecture",
                json.dumps(["omniroute", "tokenharbor", "llm", "deepseek"]),
                json.dumps([]),
                json.dumps({"source": "system_contract"}),
                now,
                now,
            ),
            (
                "Hero Image Hierarchy: Scraped from researched culinary sources first -> Codex native generation second -> Pollinations third. Step images are strictly scraped from research sources.",
                "pattern",
                json.dumps(["hero_image", "codex", "pollinations", "step_images"]),
                json.dumps([]),
                json.dumps({"source": "system_contract"}),
                now,
                now,
            ),
            (
                "Article Remaster Campaigns: Scraped-only target of 15 unique Pinterest sources creating 30 queued assets (1 viral_visual + 1 recipe_card per source).",
                "workflow",
                json.dumps(["remaster", "viral_visual", "recipe_card", "pinterest"]),
                json.dumps([]),
                json.dumps({"source": "system_contract"}),
                now,
                now,
            ),
        ]
        conn.executemany(
            """
            INSERT INTO memories (content, type, concepts, files, metadata, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            seeds,
        )
        conn.commit()

    def health(self) -> dict[str, Any]:
        """Return native memory engine health information."""
        try:
            with self._lock:
                conn = self._get_connection()
                try:
                    cur = conn.execute("SELECT COUNT(*) FROM memories")
                    count = cur.fetchone()[0]
                    cur = conn.execute("SELECT COUNT(*) FROM memories WHERE type = 'episodic'")
                    events = cur.fetchone()[0]
                    return {
                        "ok": True,
                        "status": "healthy",
                        "status_code": 200,
                        "engine": "native_sqlite_fts5",
                        "db_path": str(self.db_path),
                        "total_memories": count,
                        "total_events": events,
                    }
                finally:
                    conn.close()
        except Exception as e:
            logger.error("Native memory health check failed: %s", e)
            return {"ok": False, "status": "error", "error": str(e), "engine": "native_sqlite_fts5"}

    def remember(
        self,
        content: str,
        concepts: list[str] | None = None,
        type: str = "semantic",
        files: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Persist a durable memory into SQLite."""
        if not content:
            return {"success": False, "error": "Empty content"}

        now = datetime.now(UTC).isoformat()
        concept_list = concepts or []
        file_list = files or []
        meta_dict = metadata or {}

        try:
            with self._lock:
                conn = self._get_connection()
                try:
                    cur = conn.execute(
                        """
                        INSERT INTO memories (content, type, concepts, files, metadata, created_at, updated_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            content,
                            type,
                            json.dumps(concept_list, ensure_ascii=False),
                            json.dumps(file_list, ensure_ascii=False),
                            json.dumps(meta_dict, ensure_ascii=False),
                            now,
                            now,
                        ),
                    )
                    conn.commit()
                    rowid = cur.lastrowid
                    return {
                        "success": True,
                        "id": rowid,
                        "type": type,
                        "concepts": concept_list,
                        "created_at": now,
                    }
                finally:
                    conn.close()
        except Exception as e:
            logger.error("Failed to persist native memory: %s", e)
            return {"success": False, "error": str(e)}

    def observe(
        self,
        content: str,
        concepts: list[str] | None = None,
        type: str = "semantic",
        files: list[str] | None = None,
        hook_type: str = "rankstein_memory",
    ) -> dict[str, Any]:
        """Record a session observation in native memory."""
        meta = {
            "hook_type": hook_type,
            "session_id": f"rankstein-{datetime.now(UTC).strftime('%Y%m%d')}",
            "project": self.project,
        }
        return self.remember(content=content, concepts=concepts, type=type, files=files, metadata=meta)

    def relate(self, source_id: str, target_id: str, relation: str) -> bool:
        """Create a relationship between two memories."""
        now = datetime.now(UTC).isoformat()
        try:
            with self._lock:
                conn = self._get_connection()
                try:
                    conn.execute(
                        """
                        INSERT INTO memory_relations (source_id, target_id, relation, created_at)
                        VALUES (?, ?, ?, ?)
                        """,
                        (str(source_id), str(target_id), relation, now),
                    )
                    conn.commit()
                    return True
                finally:
                    conn.close()
        except Exception as e:
            logger.error("Failed to record memory relation: %s", e)
            return False

    def search(self, query: str, limit: int = 5) -> list[dict[str, Any]]:
        """Search memories using full-text search (FTS5) with LIKE fallback."""
        if not query or not query.strip():
            return []

        limit = max(1, min(int(limit), 50))
        cleaned_query = query.strip()

        # Sanitize query for FTS5: extract alphanumeric tokens
        tokens = re.findall(r"[\w]+", cleaned_query)
        fts_query = " OR ".join(f'"{t}"' for t in tokens if len(t) >= 2) if tokens else f'"{cleaned_query}"'

        results: list[dict[str, Any]] = []
        try:
            with self._lock:
                conn = self._get_connection()
                try:
                    if fts_query:
                        cur = conn.execute(
                            """
                            SELECT m.id, m.content, m.type, m.concepts, m.files, m.metadata, m.created_at,
                                   rank
                            FROM memories_fts f
                            JOIN memories m ON f.rowid = m.id
                            WHERE memories_fts MATCH ?
                            ORDER BY rank
                            LIMIT ?
                            """,
                            (fts_query, limit),
                        )
                        for row in cur.fetchall():
                            results.append(
                                {
                                    "id": row["id"],
                                    "content": row["content"],
                                    "type": row["type"],
                                    "concepts": json.loads(row["concepts"] or "[]"),
                                    "files": json.loads(row["files"] or "[]"),
                                    "metadata": json.loads(row["metadata"] or "{}"),
                                    "created_at": row["created_at"],
                                    "score": float(row["rank"]) if "rank" in row.keys() else 1.0,
                                }
                            )

                    # If FTS5 yielded fewer than requested, fall back to LIKE
                    if len(results) < limit:
                        seen_ids = {r["id"] for r in results}
                        like_param = f"%{cleaned_query}%"
                        cur = conn.execute(
                            """
                            SELECT id, content, type, concepts, files, metadata, created_at
                            FROM memories
                            WHERE (content LIKE ? OR concepts LIKE ?)
                            ORDER BY id DESC
                            LIMIT ?
                            """,
                            (like_param, like_param, limit - len(results)),
                        )
                        for row in cur.fetchall():
                            if row["id"] not in seen_ids:
                                results.append(
                                    {
                                        "id": row["id"],
                                        "content": row["content"],
                                        "type": row["type"],
                                        "concepts": json.loads(row["concepts"] or "[]"),
                                        "files": json.loads(row["files"] or "[]"),
                                        "metadata": json.loads(row["metadata"] or "{}"),
                                        "created_at": row["created_at"],
                                        "score": 0.5,
                                    }
                                )
                finally:
                    conn.close()
        except Exception as e:
            logger.error("Native memory search error: %s", e)

        return results[:limit]

    def log_event(
        self, event_type: str, message: str, metadata: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Record an episodic pipeline event (success/failure/startup/milestone)."""
        content = f"[{event_type.upper()}] {message}"
        if metadata:
            content += f" | Metadata: {json.dumps(metadata, ensure_ascii=False)}"

        concepts = ["event", event_type]
        if metadata:
            concepts.extend(str(k) for k in metadata.keys())

        return self.observe(
            content=content,
            concepts=sorted(set(concepts)),
            type="episodic",
        )

    def stats(self) -> dict[str, Any]:
        """Return breakdown of stored memories."""
        try:
            with self._lock:
                conn = self._get_connection()
                try:
                    cur = conn.execute("SELECT type, COUNT(*) as count FROM memories GROUP BY type")
                    by_type = {row["type"]: row["count"] for row in cur.fetchall()}
                    cur = conn.execute("SELECT COUNT(*) FROM memories")
                    total = cur.fetchone()[0]
                    cur = conn.execute("SELECT COUNT(*) FROM memory_relations")
                    relations = cur.fetchone()[0]
                    return {
                        "ok": True,
                        "total": total,
                        "by_type": by_type,
                        "relations": relations,
                        "db_path": str(self.db_path),
                    }
                finally:
                    conn.close()
        except Exception as e:
            return {"ok": False, "error": str(e)}


# Global singleton instance
memory = MemoryService()
