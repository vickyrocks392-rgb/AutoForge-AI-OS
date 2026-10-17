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
    """A single turn or tool observation in session conversation history."""
    role: str = Field(..., description="user, assistant, system, or tool")
    content: str = Field(default="", description="Textual content or model response")
    name: Optional[str] = Field(default=None, description="Tool name if role is tool")
    tool_call_id: Optional[str] = Field(default=None, description="Tool call ID if role is tool")
    tool_calls: Optional[List[Dict[str, Any]]] = Field(default=None, description="Tool calls issued by assistant")
    execution_id: Optional[str] = Field(default=None, description="Execution run identifier")
    metadata: Optional[Dict[str, Any]] = Field(default_factory=dict, description="Arbitrary message metadata")
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


def validate_session_id(session_id: str) -> str:
    """Validates session identifier against security and format policies.

    Enforces non-empty strings, bounded length, and path traversal defense.
    SQL syntax characters are safely handled as literal strings by SQLite parameter binding.
    """
    if not isinstance(session_id, str):
        raise ValueError(f"Session ID must be a string, got {type(session_id).__name__}")
    s = session_id.strip()
    if not s:
        raise ValueError("Session ID cannot be empty or blank")
    if len(s) > 256:
        raise ValueError(f"Session ID exceeds maximum length of 256 characters (got {len(s)})")
    if ".." in s or "/" in s or "\\" in s or "\0" in s:
        raise ValueError(f"Session ID contains forbidden path traversal characters: {session_id!r}")
    return s


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
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA busy_timeout = 10000")
        conn.execute("PRAGMA synchronous = NORMAL")
        conn.execute("PRAGMA foreign_keys = ON")
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
                    tool_call_id TEXT,
                    tool_calls_json TEXT,
                    created_at TEXT NOT NULL,
                    execution_id TEXT,
                    metadata_json TEXT DEFAULT '{}',
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
            # Schema migration compatibility for existing databases
            cursor = conn.execute("PRAGMA table_info(messages)")
            cols = {row["name"] for row in cursor.fetchall()}
            if "tool_call_id" not in cols:
                conn.execute("ALTER TABLE messages ADD COLUMN tool_call_id TEXT")
            if "execution_id" not in cols:
                conn.execute("ALTER TABLE messages ADD COLUMN execution_id TEXT")
            if "metadata_json" not in cols:
                conn.execute("ALTER TABLE messages ADD COLUMN metadata_json TEXT DEFAULT '{}'")
            conn.commit()

    # ── Session Management ───────────────────────────────────────────────────

    def get_or_create_session(self, session_id: str, metadata: Optional[Dict[str, Any]] = None) -> str:
        session_id = validate_session_id(session_id)
        now = datetime.now(timezone.utc).isoformat()
        with self._get_connection() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO sessions (session_id, created_at, updated_at, metadata_json) VALUES (?, ?, ?, ?)",
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

    def session_exists(self, session_id: str) -> bool:
        session_id = validate_session_id(session_id)
        with self._get_connection() as conn:
            cursor = conn.execute("SELECT 1 FROM sessions WHERE session_id = ?", (session_id,))
            return cursor.fetchone() is not None

    def delete_session(self, session_id: str) -> bool:
        session_id = validate_session_id(session_id)
        with self._get_connection() as conn:
            cursor = conn.execute("DELETE FROM sessions WHERE session_id = ?", (session_id,))
            conn.commit()
            return cursor.rowcount > 0

    # ── Conversation History ─────────────────────────────────────────────────

    def append_messages(self, session_id: str, messages: List[ConversationMessage]) -> None:
        """Atomically appends multiple conversation messages within a single transaction."""
        session_id = validate_session_id(session_id)
        if not messages:
            return
        self.get_or_create_session(session_id)
        now = datetime.now(timezone.utc).isoformat()
        with self._get_connection() as conn:
            for message in messages:
                if message.role not in {"system", "user", "assistant", "tool"}:
                    raise ValueError(f"Invalid message role '{message.role}'")
                conn.execute(
                    """
                    INSERT INTO messages (
                        session_id, role, content, name, tool_call_id,
                        tool_calls_json, created_at, execution_id, metadata_json
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        session_id,
                        message.role,
                        message.content,
                        message.name,
                        message.tool_call_id,
                        json.dumps(message.tool_calls) if message.tool_calls else None,
                        message.timestamp or now,
                        message.execution_id,
                        json.dumps(message.metadata or {}),
                    )
                )
            conn.execute("UPDATE sessions SET updated_at = ? WHERE session_id = ?", (now, session_id))
            conn.commit()

    def append_message(self, session_id: str, message: ConversationMessage) -> None:
        self.append_messages(session_id, [message])

    def get_messages(self, session_id: str, limit: int = 50) -> List[ConversationMessage]:
        session_id = validate_session_id(session_id)
        with self._get_connection() as conn:
            cursor = conn.execute(
                """
                SELECT role, content, name, tool_call_id, tool_calls_json, created_at, execution_id, metadata_json
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
                    tool_call_id=r["tool_call_id"] if "tool_call_id" in r.keys() else None,
                    tool_calls=json.loads(r["tool_calls_json"]) if r["tool_calls_json"] else None,
                    timestamp=r["created_at"],
                    execution_id=r["execution_id"] if "execution_id" in r.keys() else None,
                    metadata=json.loads(r["metadata_json"]) if "metadata_json" in r.keys() and r["metadata_json"] else {},
                )
                for r in rows
            ]

    def get_message_count(self, session_id: str) -> int:
        session_id = validate_session_id(session_id)
        with self._get_connection() as conn:
            cursor = conn.execute("SELECT COUNT(*) FROM messages WHERE session_id = ?", (session_id,))
            return cursor.fetchone()[0]

    def sanitize_incomplete_tool_calls(self, session_id: str) -> int:
        """Detects any orphaned assistant tool calls (e.g. from an interrupted or crashed turn)
        and inserts synthesized incomplete tool observations with side_effect_uncertain=True.

        Returns the count of sanitized tool calls.
        """
        session_id = validate_session_id(session_id)
        messages = self.get_messages(session_id, limit=200)
        tool_responses = {m.tool_call_id for m in messages if m.role == "tool" and m.tool_call_id}
        orphaned: List[Dict[str, Any]] = []
        for m in messages:
            if m.role == "assistant" and m.tool_calls:
                for tc in m.tool_calls:
                    call_id = tc.get("id") or (tc.get("function") or {}).get("name")
                    if call_id and call_id not in tool_responses:
                        tool_name = (tc.get("function") or {}).get("name") or "unknown"
                        orphaned.append({"call_id": call_id, "name": tool_name})

        if orphaned:
            sanitized_messages = []
            for o in orphaned:
                sanitized_messages.append(
                    ConversationMessage(
                        role="tool",
                        name=o["name"],
                        tool_call_id=o["call_id"],
                        content=json.dumps({
                            "error": "Execution interrupted before tool completion",
                            "status": "incomplete",
                            "side_effect_uncertain": True,
                        }),
                        metadata={"sanitized_incomplete": True},
                    )
                )
            self.append_messages(session_id, sanitized_messages)
            return len(orphaned)
        return 0

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
        session_id = validate_session_id(session_id)
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

    def get_execution(self, execution_id: str) -> Optional[Dict[str, Any]]:
        with self._get_connection() as conn:
            cursor = conn.execute(
                """
                SELECT execution_id, session_id, status, iterations, tool_calls_count, started_at, completed_at, telemetry_json
                FROM execution_runs
                WHERE execution_id = ?
                """,
                (execution_id,)
            )
            row = cursor.fetchone()
            if not row:
                return None
            return {
                "execution_id": row["execution_id"],
                "session_id": row["session_id"],
                "status": row["status"],
                "iterations": row["iterations"],
                "tool_calls_count": row["tool_calls_count"],
                "started_at": row["started_at"],
                "completed_at": row["completed_at"],
                "telemetry": json.loads(row["telemetry_json"] or "{}"),
            }

    def get_session_executions(self, session_id: str) -> List[Dict[str, Any]]:
        session_id = validate_session_id(session_id)
        with self._get_connection() as conn:
            cursor = conn.execute(
                """
                SELECT execution_id, session_id, status, iterations, tool_calls_count, started_at, completed_at, telemetry_json
                FROM execution_runs
                WHERE session_id = ?
                ORDER BY started_at ASC
                """,
                (session_id,)
            )
            return [
                {
                    "execution_id": row["execution_id"],
                    "session_id": row["session_id"],
                    "status": row["status"],
                    "iterations": row["iterations"],
                    "tool_calls_count": row["tool_calls_count"],
                    "started_at": row["started_at"],
                    "completed_at": row["completed_at"],
                    "telemetry": json.loads(row["telemetry_json"] or "{}"),
                }
                for row in cursor.fetchall()
            ]

    def validate_state_integrity(self, session_id: Optional[str] = None) -> bool:
        """Validates that persisted state is intact, parseable, and uncorrupted.

        Raises ValueError if corrupted or incomplete state is detected.
        """
        if session_id:
            session_id = validate_session_id(session_id)
        try:
            with self._get_connection() as conn:
                # 0. Check SQLite low-level integrity
                integrity_row = conn.execute("PRAGMA integrity_check").fetchone()
                if not integrity_row or integrity_row[0] != "ok":
                    raise ValueError(f"SQLite low-level database corruption detected: {integrity_row[0] if integrity_row else 'unknown'}")

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

                # 3. Verify messages JSON validity and constraints
                msg_query = "SELECT id, session_id, role, content, name, tool_call_id, tool_calls_json, metadata_json FROM messages"
                params = ()
                if session_id:
                    msg_query += " WHERE session_id = ?"
                    params = (session_id,)
                msg_rows = conn.execute(msg_query, params).fetchall()
                for r in msg_rows:
                    if not r["role"] or r["content"] is None:
                        raise ValueError(f"Corrupted message record id={r['id']}: missing role or content")
                    if r["role"] not in {"system", "user", "assistant", "tool"}:
                        raise ValueError(f"Corrupted message record id={r['id']}: invalid role '{r['role']}'")
                    if r["role"] == "tool" and not r["name"]:
                        raise ValueError(f"Corrupted tool message id={r['id']}: tool message missing tool name")
                    if r["tool_calls_json"]:
                        try:
                            tc_parsed = json.loads(r["tool_calls_json"])
                            if not isinstance(tc_parsed, list):
                                raise ValueError("tool_calls must be a list")
                        except Exception as e:
                            raise ValueError(f"Corrupted tool calls in message id={r['id']}: {e}") from e
                    if "metadata_json" in r.keys() and r["metadata_json"]:
                        try:
                            json.loads(r["metadata_json"])
                        except Exception as e:
                            raise ValueError(f"Corrupted metadata in message id={r['id']}: {e}") from e

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
