"""Phase 18-D — genuine vector retrieval + bounded context assembly.

    query text
        → local embedding
        → vector store ANN search (metadata scope filter applied in-database)
        → top-k scored hits
        → KnowledgeRetrievalResult

Retrieval returns real scores from the vector backend; nothing is fabricated.
``KnowledgeRetrievalService.retrieve`` is the single authoritative production
retrieval path.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from autoforge_knowledge_platform.rag18.config import DEFAULT_COLLECTION_NAME, KnowledgeConfig
from autoforge_knowledge_platform.rag18.embedding import EmbeddingService
from autoforge_knowledge_platform.rag18.errors import (
    EmbeddingUnavailableError,
    ScopeRequiredError,
    VectorStoreUnavailableError,
)
from autoforge_knowledge_platform.rag18.models import (
    KnowledgeRetrievalResult,
    RetrievalRequest,
    RetrievalResultHit,
    RetrievalScope,
)
from autoforge_knowledge_platform.rag18.store import KnowledgeStore

logger = logging.getLogger(__name__)


class KnowledgeRetrievalService:
    """The one authoritative retrieval path for Phase 18-D."""

    def __init__(
        self,
        store: KnowledgeStore,
        embedding: EmbeddingService,
        config: KnowledgeConfig | None = None,
    ) -> None:
        self._store = store
        self._embedding = embedding
        self._config = config or KnowledgeConfig()

    @property
    def store(self) -> KnowledgeStore:
        return self._store

    @property
    def embedding(self) -> EmbeddingService:
        return self._embedding

    async def retrieve(self, request: RetrievalRequest) -> KnowledgeRetrievalResult:
        """Genuine scope-filtered vector retrieval.

        Raises ``ScopeRequiredError`` for unscoped queries unless
        ``allow_unscoped_retrieval`` is enabled (used only by explicit tests).
        """
        if not request.scope.is_explicit and not self._config.allow_unscoped_retrieval:
            raise ScopeRequiredError(
                "Retrieval requires an explicit project/workspace scope "
                "(project isolation is mandatory)."
            )

        started = time.perf_counter()
        try:
            if not self._embedding.is_available():
                raise EmbeddingUnavailableError(
                    f"Local embedding model '{self._embedding.model}' unavailable. "
                    "No fake query vector is substituted."
                )
            query_vector = await self._embedding.embed(request.query)
        except Exception:
            raise
        query_ms = (time.perf_counter() - started) * 1000.0

        try:
            hits = await self._store.query(
                query_vector,
                request.scope,
                top_k=request.top_k,
                score_threshold=request.score_threshold,
                content_max_chars=request.content_max_chars if request.include_content else 0,
            )
        except Exception as exc:
            raise VectorStoreUnavailableError(
                f"Local vector retrieval failed: {exc}"
            ) from exc

        result_hits = [
            RetrievalResultHit(
                chunk_id=hit.knowledge_id,
                knowledge_id=hit.knowledge_id,
                source_id=hit.source_id,
                path=hit.path,
                content=hit.content,
                score=hit.score,
                metadata=hit.metadata,
            )
            for hit in hits
        ]
        return KnowledgeRetrievalResult(
            query=request.query,
            scope=request.scope,
            top_k=request.top_k,
            hits=result_hits,
            retrieval_backend=self._store.backend_name,
            collection=getattr(self._store, "collection_name", DEFAULT_COLLECTION_NAME),
            embedding_model=self._embedding.model,
            embedding_dimension=self._embedding.dimension,
            embedding_version=self._embedding.embedding_version,
            retrieval_ms=(time.perf_counter() - started) * 1000.0,
        )

    async def assemble_evidence(
        self,
        result: KnowledgeRetrievalResult,
        *,
        max_chunks: int | None = None,
        max_total_chars: int | None = None,
        content_chars: int | None = None,
    ) -> str:
        """Bounded, explicitly-labelled RETRIEVED KNOWLEDGE / EVIDENCE block.

        This block is inserted into the reasoning prompt as evidence with
        source/path, chunk identity and relevance score — never as trusted
        system instructions.
        """
        max_chunks = max_chunks or self._config.evidence_max_chunks
        max_total_chars = max_total_chars or self._config.evidence_max_total_chars
        content_chars = content_chars or self._config.evidence_content_chars

        budget = max_total_chars
        blocks: list[str] = []
        for i, hit in enumerate(result.hits[:max_chunks], start=1):
            content = hit.content[:content_chars]
            budget -= len(content)
            if budget < 0:
                break
            blocks.append(
                "[RETRIEVED KNOWLEDGE / EVIDENCE] "
                f"(rank={i}, score={hit.score:.4f}, source={hit.path}, "
                f"chunk={hit.chunk_id}, model={result.embedding_model})\n"
                f"{content}"
            )
        if not blocks:
            return ""
        return "\n\n".join(blocks)


def build_retrieval_scope(
    *,
    project_id: str | None = None,
    workflow_id: str | None = None,
    execution_id: str | None = None,
    workspace_root: str | None = None,
) -> RetrievalScope:
    return RetrievalScope(
        project_id=project_id,
        workflow_id=workflow_id,
        execution_id=execution_id,
        workspace_root=workspace_root,
    )