"""Phase 18-D — AutoForge-owned KnowledgeStore abstraction.

The abstraction preserves backend independence, testability, scope enforcement
and provenance. It exposes ONLY knowledge-domain operations:

    upsert / query / delete_by_source / delete_by_filter / count / health

No AutoForge caller imports the vector backend directly; they depend on this
interface (or the retrieval service facade).
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from autoforge_knowledge_platform.rag18.models import KnowledgeChunk, RetrievalScope


@dataclass(frozen=True)
class ScoredStoreHit:
    """A scored hit from the store (backed by a real vector score)."""

    knowledge_id: str
    source_id: str
    path: str
    content: str
    score: float
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class KnowledgeStoreHealth:
    """Observability snapshot of the vector store."""

    ok: bool
    backend: str
    collection: str
    points_count: int = 0
    error: str | None = None
    latency_ms: float = 0.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "backend": self.backend,
            "collection": self.collection,
            "points_count": self.points_count,
            "error": self.error,
            "latency_ms": round(self.latency_ms, 3),
        }


class KnowledgeStore(ABC):
    """Backend-independent persistent vector knowledge store."""

    @property
    @abstractmethod
    def backend_name(self) -> str: ...

    @abstractmethod
    async def initialize(self) -> None:
        """Ensure the collection/index exists and is compatible."""

    @abstractmethod
    async def upsert_chunks(self, chunks: list[KnowledgeChunk], vectors: list[list[float]]) -> int:
        """Insert or replace chunk vectors. Returns the number of upserted points."""

    @abstractmethod
    async def query(
        self,
        query_vector: list[float],
        scope: RetrievalScope,
        *,
        top_k: int,
        score_threshold: float | None = None,
        content_max_chars: int = 1400,
        offset: int = 0,
    ) -> list[ScoredStoreHit]:
        """Indexed nearest-neighbour search filtered by scope (no brute force)."""

    @abstractmethod
    async def delete_by_source(self, source_id: str) -> int:
        """Delete every chunk belonging to a source. Returns deleted count."""

    @abstractmethod
    async def delete_by_filter(self, payload_filter: dict[str, Any]) -> int:
        """Delete chunks matching arbitrary metadata filter keys/values."""

    @abstractmethod
    async def count(self, scope: RetrievalScope | None = None) -> int:
        """Total points, optionally restricted to a scope."""

    @abstractmethod
    async def vector_dimension(self) -> int | None:
        """Vector dimension of the existing collection (None if absent)."""

    @abstractmethod
    async def health(self) -> KnowledgeStoreHealth:
        """Real backend reachability/index check."""

    @abstractmethod
    async def close(self) -> None: ...