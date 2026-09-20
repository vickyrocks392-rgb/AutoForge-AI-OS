"""Bounded Idempotency Storage & Key Management (18-COMMERCIAL-C)."""

from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger("autoforge.power_engines.automation.idempotency")


class IdempotencyStore:
    """
    Bounded local idempotency store backed by SQLite or in-memory dict.
    Provides deduplication for workflow execution keys and action idempotency keys.
    Architecturally designed to allow drop-in replacement by 18-J durable infrastructure.
    """

    def __init__(self, db_path: Optional[str | Path] = None):
        self.db_path = str(db_path) if db_path else ":memory:"
        if self.db_path != ":memory:":
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._get_connection() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS idempotency_keys (
                    idempotency_key TEXT PRIMARY KEY,
                    scope TEXT NOT NULL,
                    workflow_id TEXT NOT NULL,
                    execution_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    response_json TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)
            conn.commit()

    @staticmethod
    def generate_key(scope: str, identifier: str, parameters: Dict[str, Any]) -> str:
        """Derives a deterministic SHA-256 idempotency key."""
        serialized = json.dumps(parameters, sort_keys=True)
        raw = f"{scope}:{identifier}:{serialized}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def check_key(self, key: str) -> Tuple[bool, Optional[Dict[str, Any]]]:
        """
        Checks if a key has already completed execution.
        Returns: (exists, cached_response)
        """
        with self._get_connection() as conn:
            row = conn.execute(
                "SELECT status, response_json FROM idempotency_keys WHERE idempotency_key = ?",
                (key,)
            ).fetchone()
            if row:
                status = row["status"]
                resp = json.loads(row["response_json"]) if row["response_json"] else {}
                return True, resp
        return False, None

    def record_start(self, key: str, scope: str, workflow_id: str, execution_id: str) -> None:
        """Marks an idempotency key as IN_PROGRESS."""
        now = datetime.now(timezone.utc).isoformat()
        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO idempotency_keys
                (idempotency_key, scope, workflow_id, execution_id, status, response_json, created_at, updated_at)
                VALUES (?, ?, ?, ?, 'IN_PROGRESS', NULL, ?, ?)
                """,
                (key, scope, workflow_id, execution_id, now, now)
            )
            conn.commit()

    def record_complete(self, key: str, response: Dict[str, Any]) -> None:
        """Marks an idempotency key as COMPLETED with its cached response."""
        now = datetime.now(timezone.utc).isoformat()
        resp_str = json.dumps(response)
        with self._get_connection() as conn:
            conn.execute(
                """
                UPDATE idempotency_keys
                SET status = 'COMPLETED', response_json = ?, updated_at = ?
                WHERE idempotency_key = ?
                """,
                (resp_str, now, key)
            )
            conn.commit()
