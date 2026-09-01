"""Phase 18-D — knowledge domain models.

Identifiers follow the requirement that only identifiers supported by
AutoForge are used:

- ``project_id`` / ``workflow_id`` / ``execution_id`` — from orchestration
  project state (UUID strings when available).
- ``task_id`` / ``stage_id`` — engineering stage identity.
- ``source_id`` — deterministic content identity (sha256 of source content).
- ``chunk_id`` — deterministic ``source_id::<index>`` (also used as the
  vector point identity so upserts are idempotent replaces).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime | None) -> str:
    return dt.isoformat() if dt is not None else ""


class KnowledgeChunk(BaseModel):
    """A single indexed knowledge chunk (one vector point)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    knowledge_id: str = Field(..., min_length=1, description="Deterministic chunk identity (source_id::index).")
    source_id: str = Field(..., min_length=1, description="Deterministic source content identity.")
    chunk_id: str = Field(..., min_length=1, description="Alias of knowledge_id; explicit requirement field.")
    workspace_root: str = Field(default="", description="Workspace root path this knowledge belongs to.")
    project_id: str | None = Field(default=None, description="Orchestration project UUID (scope).")
    workflow_id: str | None = Field(default=None, description="Orchestration workflow UUID (scope).")
    execution_id: str | None = Field(default=None, description="Orchestration execution UUID (scope).")
    path: str = Field(..., description="Repository-relative source path.")
    document_type: str = Field(default="plain_text")
    language: str = Field(default="text")
    chunk_index: int = Field(..., ge=0)
    content: str = Field(..., min_length=1)
    content_hash: str = Field(..., min_length=8)
    start_line: int | None = None
    end_line: int | None = None
    embedding_model: str = Field(default="")
    embedding_dimension: int = Field(default=0, ge=0)
    embedding_version: str = Field(default="")
    created_at: str = Field(default_factory=lambda: _iso(_utc_now()))
    updated_at: str = Field(default_factory=lambda: _iso(_utc_now()))

    def payload(self) -> dict[str, Any]:
        """Qdrant payload representation (string timestamp values)."""
        return {
            "knowledge_id": self.knowledge_id,
            "source_id": self.source_id,
            "chunk_id": self.chunk_id,
            "workspace_root": self.workspace_root,
            "project_id": self.project_id,
            "workflow_id": self.workflow_id,
            "execution_id": self.execution_id,
            "path": self.path,
            "document_type": self.document_type,
            "language": self.language,
            "chunk_index": self.chunk_index,
            "content": self.content,
            "content_hash": self.content_hash,
            "start_line": self.start_line,
            "end_line": self.end_line,
            "embedding_model": self.embedding_model,
            "embedding_dimension": self.embedding_dimension,
            "embedding_version": self.embedding_version,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "KnowledgeChunk":
        return cls.model_validate(payload)


class SourceRecord(BaseModel):
    """Index-state record for one discovered source (SQLite metadata)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    source_id: str
    project_id: str | None
    workspace_root: str
    path: str
    source_hash: str
    document_type: str
    language: str
    chunk_count: int = Field(..., ge=0)
    embedding_model: str
    embedding_dimension: int = Field(..., ge=0)
    embedding_version: str
    indexed_at: str
    updated_at: str


class RetrievalScope(BaseModel):
    """Explicit scope for retrieval. Project isolation is mandatory."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    project_id: str | None = None
    workflow_id: str | None = None
    execution_id: str | None = None
    workspace_root: str | None = None

    @property
    def is_explicit(self) -> bool:
        return bool(self.project_id or self.workspace_root)


class RetrievalRequest(BaseModel):
    """A genuine vector retrieval request."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    query: str = Field(..., min_length=1)
    scope: RetrievalScope
    top_k: int = Field(default=6, ge=1, le=50)
    score_threshold: float | None = None
    include_content: bool = True
    content_max_chars: int = Field(default=1400, ge=0)


class RetrievalResultHit(BaseModel):
    """One retrieved knowledge chunk with its real score."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    chunk_id: str
    knowledge_id: str
    source_id: str
    path: str
    content: str
    score: float = Field(...)
    metadata: dict[str, Any] = Field(default_factory=dict)


class KnowledgeRetrievalResult(BaseModel):
    """Structure returned by genuine vector retrieval."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    query: str
    scope: RetrievalScope
    top_k: int
    hits: list[RetrievalResultHit] = Field(default_factory=list)
    retrieval_backend: str = Field(default="")
    collection: str = Field(default="")
    embedding_model: str = Field(default="")
    embedding_dimension: int = Field(default=0, ge=0)
    embedding_version: str = Field(default="")
    retrieval_ms: float = Field(default=0.0, ge=0.0)

    @property
    def count(self) -> int:
        return len(self.hits)


class IndexReport(BaseModel):
    """Result of an incremental indexing run."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    workspace_root: str
    project_id: str | None = None
    sources_scanned: int = Field(..., ge=0)
    inserted: int = Field(..., ge=0)
    updated: int = Field(..., ge=0)
    unchanged: int = Field(..., ge=0)
    deleted: int = Field(..., ge=0)
    total_chunks: int = Field(..., ge=0)
    embedding_model: str
    duration_ms: float = Field(default=0.0, ge=0.0)
    errors: list[str] = Field(default_factory=list)