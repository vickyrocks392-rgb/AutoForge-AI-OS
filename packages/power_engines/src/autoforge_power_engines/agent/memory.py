"""Customer-owned SQLite State and Memory Persistence (Phase 18-COMMERCIAL-B).

Implements independent local state persistence for sessions, message history,
persistent key-value agent memory, and execution telemetry.
Zero AutoForge proprietary memory engine code or imports.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class ConversationMessage(BaseModel):
    """A single turn in session conversation history."""
    role: str = Field(..., description="user, assistant, system, or tool")
    content: str = Field(default="", description="Textual content or model response")
    name: Optional[str] = Field(default=None, description="Tool name if role is tool")
    tool_calls: Optional[List[Dict[str, Any]]] = Field(default=None, description="Tool calls issued by assistant")
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class AgentMemoryStore:
    """
    Standalone SQLite-backed memory store for customer agents.
    Thread-safe, self-initializing, and fully isolated.
    """

    def __init__(self, db_path: Path | str = "data/state/agent_state.db"):
        self.db_path = Path(db_path).resolve()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=10.0)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        """Initializes relational schema for sessions, messages, memory, and executions."""
        with self._get_connection() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS sessions (
                    session_id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    metadata_json TEXT DEFAULT '{}'
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    name TEXT,
                    tool_calls_json TEXT,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(session_id) REFERENCES sessions(session_id) ON DELETE CASCADE
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id, id)
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS persistent_memory (
                    key TEXT PRIMARY KEY,
                    value_json TEXT NOT NULL,
                    category TEXT DEFAULT 'general',
                    updated_at TEXT NOT NULL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS execution_runs (
                    execution_id TEXT PRIMARY KEY,
                    session_id TEXT,
                    status TEXT NOT NULL,
                    iterations INTEGER DEFAULT 0,
                    tool_calls_count INTEGER DEFAULT 0,
                    started_at TEXT NOT NULL,
                    completed_at TEXT,
                    telemetry_json TEXT DEFAULT '{}'
                )
            """)
            conn.commit()

    # ── Session Management ───────────────────────────────────────────────────

    def get_or_create_session(self, session_id: str, metadata: Optional[Dict[str, Any]] = None) -> str:
        now = datetime.now(timezone.utc).isoformat()
        with self._get_connection() as conn:
            cursor = conn.execute("SELECT session_id FROM sessions WHERE session_id = ?", (session_id,))
            if not cursor.fetchone():
                conn.execute(
                    "INSERT INTO sessions (session_id, created_at, updated_at, metadata_json) VALUES (?, ?, ?, ?)",
                    (session_id, now, now, json.dumps(metadata or {}))
                )
                conn.commit()
        return session_id

    def list_sessions(self, limit: int = 50) -> List[Dict[str, Any]]:
        with self._get_connection() as conn:
            cursor = conn.execute(
                "SELECT session_id, created_at, updated_at, metadata_json FROM sessions ORDER BY updated_at DESC LIMIT ?",
                (limit,)
            )
            rows = cursor.fetchall()
            return [
                {
                    "session_id": r["session_id"],
                    "created_at": r["created_at"],
                    "updated_at": r["updated_at"],
                    "metadata": json.loads(r["metadata_json"] or "{}"),
                }
                for r in rows
            ]

    # ── Conversation History ─────────────────────────────────────────────────

    def append_message(self, session_id: str, message: ConversationMessage) -> None:
        self.get_or_create_session(session_id)
        now = datetime.now(timezone.utc).isoformat()
        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT INTO messages (session_id, role, content, name, tool_calls_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    session_id,
                    message.role,
                    message.content,
                    message.name,
                    json.dumps(message.tool_calls) if message.tool_calls else None,
                    now,
                )
            )
            conn.execute("UPDATE sessions SET updated_at = ? WHERE session_id = ?", (now, session_id))
            conn.commit()

    def get_messages(self, session_id: str, limit: int = 50) -> List[ConversationMessage]:
        with self._get_connection() as conn:
            cursor = conn.execute(
                """
                SELECT role, content, name, tool_calls_json, created_at
                FROM messages
                WHERE session_id = ?
                ORDER BY id ASC
                LIMIT ?
                """,
                (session_id, limit)
            )
            rows = cursor.fetchall()
            return [
                ConversationMessage(
                    role=r["role"],
                    content=r["content"],
                    name=r["name"],
                    tool_calls=json.loads(r["tool_calls_json"]) if r["tool_calls_json"] else None,
                    timestamp=r["created_at"],
                )
                for r in rows
            ]

    # ── Persistent Agent Key-Value Memory ────────────────────────────────────

    def set_memory(self, key: str, value: Any, category: str = "general") -> None:
        now = datetime.now(timezone.utc).isoformat()
        val_json = json.dumps(value)
        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT INTO persistent_memory (key, value_json, category, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET value_json = excluded.value_json, updated_at = excluded.updated_at
                """,
                (key, val_json, category, now)
            )
            conn.commit()

    def get_memory(self, key: str) -> Optional[Any]:
        with self._get_connection() as conn:
            cursor = conn.execute("SELECT value_json FROM persistent_memory WHERE key = ?", (key,))
            row = cursor.fetchone()
            if row:
                return json.loads(row["value_json"])
            return None

    def get_all_memories(self, category: Optional[str] = None) -> Dict[str, Any]:
        with self._get_connection() as conn:
            if category:
                cursor = conn.execute("SELECT key, value_json FROM persistent_memory WHERE category = ?", (category,))
            else:
                cursor = conn.execute("SELECT key, value_json FROM persistent_memory")
            rows = cursor.fetchall()
            return {r["key"]: json.loads(r["value_json"]) for r in rows}

    # ── Execution Telemetry Tracking ─────────────────────────────────────────

    def record_execution(
        self,
        execution_id: str,
        session_id: str,
        status: str,
        iterations: int,
        tool_calls_count: int,
        telemetry: Dict[str, Any],
        completed: bool = False,
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT INTO execution_runs (execution_id, session_id, status, iterations, tool_calls_count, started_at, completed_at, telemetry_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(execution_id) DO UPDATE SET
                    status = excluded.status,
                    iterations = excluded.iterations,
                    tool_calls_count = excluded.tool_calls_count,
                    completed_at = CASE WHEN excluded.completed_at IS NOT NULL THEN excluded.completed_at ELSE execution_runs.completed_at END,
                    telemetry_json = excluded.telemetry_json
                """,
                (
                    execution_id,
                    session_id,
                    status,
                    iterations,
                    tool_calls_count,
                    now,
                    now if completed else None,
                    json.dumps(telemetry),
                )
            )
            conn.commit()

    def validate_state_integrity(self, session_id: Optional[str] = None) -> bool:
        """Validates that persisted state is intact, parseable, and uncorrupted.

        Raises ValueError if corrupted or incomplete state is detected.
        """
        try:
            with self._get_connection() as conn:
                # 1. Verify schema tables exist
                tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
                table_names = {r["name"] for r in tables}
                required_tables = {"sessions", "messages", "persistent_memory", "execution_runs"}
                if not required_tables.issubset(table_names):
                    raise ValueError(f"Missing required state tables: {required_tables - table_names}")

                # 2. Verify persistent_memory JSON validity
                mem_rows = conn.execute("SELECT key, value_json FROM persistent_memory").fetchall()
                for r in mem_rows:
                    try:
                        json.loads(r["value_json"])
                    except Exception as e:
                        raise ValueError(f"Corrupted memory entry for key '{r['key']}': {e}") from e

                # 3. Verify messages JSON validity
                msg_query = "SELECT id, session_id, role, content, tool_calls_json FROM messages"
                params = ()
                if session_id:
                    msg_query += " WHERE session_id = ?"
                    params = (session_id,)
                msg_rows = conn.execute(msg_query, params).fetchall()
                for r in msg_rows:
                    if not r["role"] or r["content"] is None:
                        raise ValueError(f"Corrupted message record id={r['id']}: missing role or content")
                    if r["tool_calls_json"]:
                        try:
                            json.loads(r["tool_calls_json"])
                        except Exception as e:
                            raise ValueError(f"Corrupted tool calls in message id={r['id']}: {e}") from e

                # 4. Verify execution runs JSON validity
                exec_rows = conn.execute("SELECT execution_id, telemetry_json FROM execution_runs").fetchall()
                for r in exec_rows:
                    if r["telemetry_json"]:
                        try:
                            json.loads(r["telemetry_json"])
                        except Exception as e:
                            raise ValueError(f"Corrupted telemetry in execution '{r['execution_id']}': {e}") from e

            return True
        except Exception as ex:
            if isinstance(ex, ValueError):
                raise
            raise ValueError(f"State integrity verification failure: {ex}") from ex
