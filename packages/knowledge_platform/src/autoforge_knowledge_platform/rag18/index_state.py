"""Phase 18-D — index-state metadata store (SQLite).

SQLite is used ONLY for ordinary metadata/state (requirement #3): per-source
index records, embedding signature, and counters. Vector retrieval lives in
the real vector database (Qdrant). This module never performs similarity
search.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import time
from pathlib import Path
from typing import Any

from autoforge_knowledge_platform.rag18.models import SourceRecord

logger = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sources (
    source_id TEXT PRIMARY KEY,
    project_id TEXT,
    workspace_root TEXT NOT NULL,
    path TEXT NOT NULL,
    source_hash TEXT NOT NULL,
    document_type TEXT NOT NULL,
    language TEXT NOT NULL,
    chunk_count INTEGER NOT NULL DEFAULT 0,
    embedding_model TEXT NOT NULL,
    embedding_dimension INTEGER NOT NULL,
    embedding_version TEXT NOT NULL,
    indexed_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


class IndexStateStore:
    """SQLite persistence for index metadata and the embedding signature."""

    def __init__(self, path: str | Path | None) -> None:
        self._path: str | None = str(path) if path else None
        self._conn: sqlite3.Connection | None = None

    def _connect(self) -> sqlite3.Connection:
        if self._conn is not None:
            return self._conn
        if self._path is None:
            raise RuntimeError("index_state_path not configured")
        Path(self._path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self._path)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)
        self._conn.commit()
        return self._conn

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    # ── Embedding signature ────────────────────────────────────────────────

    def get_embedding_signature(self) -> dict[str, Any] | None:
        conn = self._connect()
        row = conn.execute("SELECT value FROM meta WHERE key = 'embedding_signature'").fetchone()
        if row is None:
            return None
        try:
            return json.loads(row["value"])
        except (TypeError, ValueError):
            return None

    def set_embedding_signature(self, signature: dict[str, Any]) -> None:
        conn = self._connect()
        conn.execute(
            "INSERT OR REPLACE INTO meta (key, value) VALUES ('embedding_signature', ?)",
            (json.dumps(signature, sort_keys=True),),
        )
        conn.commit()

    # ── Source records ─────────────────────────────────────────────────────

    def upsert_source(self, record: SourceRecord) -> None:
        conn = self._connect()
        conn.execute(
            """
            INSERT OR REPLACE INTO sources (
                source_id, project_id, workspace_root, path, source_hash,
                document_type, language, chunk_count, embedding_model,
                embedding_dimension, embedding_version, indexed_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record.source_id,
                record.project_id,
                record.workspace_root,
                record.path,
                record.source_hash,
                record.document_type,
                record.language,
                record.chunk_count,
                record.embedding_model,
                record.embedding_dimension,
                record.embedding_version,
                record.indexed_at,
                record.updated_at,
            ),
        )
        conn.commit()

    def delete_source(self, source_id: str) -> None:
        conn = self._connect()
        conn.execute("DELETE FROM sources WHERE source_id = ?", (source_id,))
        conn.commit()

    def get_source(self, source_id: str) -> SourceRecord | None:
        conn = self._connect()
        row = conn.execute("SELECT * FROM sources WHERE source_id = ?", (source_id,)).fetchone()
        if row is None:
            return None
        return SourceRecord(**dict(row))

    def list_sources(self, workspace_root: str | None = None) -> list[SourceRecord]:
        conn = self._connect()
        if workspace_root is not None:
            rows = conn.execute(
                "SELECT * FROM sources WHERE workspace_root = ? ORDER BY path",
                (workspace_root,),
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM sources ORDER BY path").fetchall()
        return [SourceRecord(**dict(r)) for r in rows]

    def list_paths(self, project_id: str | None = None, workspace_root: str | None = None) -> dict[str, SourceRecord]:
        """Current indexed sources keyed by absolute path (change detection)."""
        records = self.list_sources(workspace_root=workspace_root)
        result: dict[str, SourceRecord] = {}
        for record in records:
            if project_id is not None and record.project_id != project_id:
                continue
            result[record.path] = record
        return result


def sqlite_stats(path: str | Path) -> dict[str, Any]:
    """Small diagnostics helper used by integration tests."""
    started = time.perf_counter()
    conn = sqlite3.connect(str(path))
    row = conn.execute("SELECT COUNT(*) AS n FROM sources").fetchone()
    conn.close()
    return {
        "source_count": int(row[0]),
        "latency_ms": (time.perf_counter() - started) * 1000.0,
    }