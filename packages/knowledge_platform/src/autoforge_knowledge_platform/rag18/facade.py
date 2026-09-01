"""Phase 18-D — orchestration-facing facade.

Wires the store, local embeddings, incremental indexer, retrieval service and
evidence assembly behind a single object that the orchestration layer can
inject. Preserves backend independence: no AutoForge caller imports Qdrant.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from autoforge_knowledge_platform.rag18.config import KnowledgeConfig, default_knowledge_config
from autoforge_knowledge_platform.rag18.embedding import EmbeddingService, OllamaEmbeddingService
from autoforge_knowledge_platform.rag18.indexer import KnowledgeIndexer
from autoforge_knowledge_platform.rag18.models import (
    IndexReport,
    KnowledgeRetrievalResult,
    RetrievalRequest,
    RetrievalScope,
)
from autoforge_knowledge_platform.rag18.qdrant_store import QdrantKnowledgeStore
from autoforge_knowledge_platform.rag18.retrieval import KnowledgeRetrievalService
from autoforge_knowledge_platform.rag18.store import KnowledgeStore

logger = logging.getLogger(__name__)


class KnowledgeRAGEngine:
    """Composed 18-D facade: index, retrieve, assemble evidence, health."""

    def __init__(
        self,
        config: KnowledgeConfig | None = None,
        *,
        store: KnowledgeStore | None = None,
        embedding: EmbeddingService | None = None,
    ) -> None:
        self._config = config or KnowledgeConfig()
        self._store = store or QdrantKnowledgeStore(self._config)
        self._embedding = embedding or OllamaEmbeddingService(
            base_url=self._config.ollama_base_url,
            model=self._config.embedding_model,
            dimension=self._config.embedding_dimension,
            timeout_seconds=self._config.ollama_timeout_seconds,
            embedding_version=self._config.embedding_version,
        )
        self._indexer = KnowledgeIndexer(self._store, self._embedding, self._config)
        self._retrieval = KnowledgeRetrievalService(self._store, self._embedding, self._config)
        self._initialized = False

    # ── Accessors ───────────────────────────────────────────────────────────

    @property
    def store(self) -> KnowledgeStore:
        return self._store

    @property
    def embedding(self) -> EmbeddingService:
        return self._embedding

    @property
    def indexer(self) -> KnowledgeIndexer:
        return self._indexer

    @property
    def retrieval(self) -> KnowledgeRetrievalService:
        return self._retrieval

    @property
    def config(self) -> KnowledgeConfig:
        return self._config

    # ── Lifecycle ───────────────────────────────────────────────────────────

    async def initialize(self) -> None:
        if self._initialized:
            return
        await self._indexer.initialize()
        self._initialized = True

    async def health(self) -> dict[str, Any]:
        healthy = await self._store.health()
        return {
            "ok": healthy.ok,
            "vector_db": healthy.as_dict(),
            "embedding": {
                "ok": self._embedding.is_available(),
                "model": self._embedding.model,
                "dimension": self._embedding.dimension,
            },
            "collection": healthy.collection,
        }

    async def close(self) -> None:
        await self._store.close()

    # ── Operations ──────────────────────────────────────────────────────────

    async def index_repository(
        self,
        workspace_root: str | Path,
        *,
        project_id: str | None = None,
        workflow_id: str | None = None,
        execution_id: str | None = None,
        force: bool = False,
    ) -> IndexReport:
        await self.initialize()
        return await self._indexer.index_repository(
            workspace_root,
            project_id=project_id,
            workflow_id=workflow_id,
            execution_id=execution_id,
            force=force,
        )

    async def retrieve(self, request: RetrievalRequest) -> KnowledgeRetrievalResult:
        await self.initialize()
        return await self._retrieval.retrieve(request)

    async def retrieve_for_context(
        self,
        query: str,
        *,
        project_id: str | None = None,
        workflow_id: str | None = None,
        execution_id: str | None = None,
        workspace_root: str | None = None,
        top_k: int | None = None,
        score_threshold: float | None = None,
    ) -> KnowledgeRetrievalResult:
        """Convenience: retrieve with an explicit scope from orchestration ids."""
        scope = RetrievalScope(
            project_id=project_id,
            workflow_id=workflow_id,
            execution_id=execution_id,
            workspace_root=workspace_root,
        )
        request = RetrievalRequest(
            query=query,
            scope=scope,
            top_k=top_k or self._config.top_k_default,
            score_threshold=(
                score_threshold
                if score_threshold is not None
                else self._config.score_threshold_default
            ),
        )
        return await self.retrieve(request)


__all__ = ["KnowledgeRAGEngine"]