"""Phase 18-D — Local RAG / Knowledge Integration.

The AutoForge-owned knowledge subsystem for real, full, free, local,
offline-capable retrieval-augmented engineering:

    AutoForge
        |
        v
      KnowledgeStore (abstraction)
        |
        v
      Local Qdrant (self-hosted native process or embedded dev mode)
        |
        v
      Real retrieval (indexed ANN + metadata scope filtering)
        |
        v
      Local embeddings (Ollama, e.g. nomic-embed-text)
        |
        v
      ExecutionContext.retrieved_knowledge
        |
        v
      AIInfrastructureAdapter -> ModelRouterService -> local model

This package implements the production path only. It introduces NO cloud
dependency, NO paid service, NO remote vector database and NO network call
in retrieval/embedding once the local model and vector index are installed.
"""

from __future__ import annotations

from autoforge_knowledge_platform.rag18.config import KnowledgeConfig, default_knowledge_config
from autoforge_knowledge_platform.rag18.embedding import (
    EmbeddingService,
    OllamaEmbeddingService,
)
from autoforge_knowledge_platform.rag18.errors import (
    EmbeddingModelUnavailableError,
    EmbeddingUnavailableError,
    IncompatibleEmbeddingModelError,
    KnowledgeRagError,
    ScopeRequiredError,
    VectorStoreUnavailableError,
)
from autoforge_knowledge_platform.rag18.facade import KnowledgeRAGEngine
from autoforge_knowledge_platform.rag18.indexer import KnowledgeIndexer
from autoforge_knowledge_platform.rag18.models import (
    IndexReport,
    KnowledgeChunk,
    KnowledgeRetrievalResult,
    RetrievalRequest,
    RetrievalResultHit,
    RetrievalScope,
    SourceRecord,
)
from autoforge_knowledge_platform.rag18.qdrant_store import QdrantKnowledgeStore
from autoforge_knowledge_platform.rag18.retrieval import KnowledgeRetrievalService
from autoforge_knowledge_platform.rag18.store import (
    KnowledgeStore,
    KnowledgeStoreHealth,
    ScoredStoreHit,
)

__all__ = [
    "EmbeddingService",
    "EmbeddingModelUnavailableError",
    "EmbeddingUnavailableError",
    "IncompatibleEmbeddingModelError",
    "IndexReport",
    "KnowledgeChunk",
    "KnowledgeConfig",
    "KnowledgeIndexer",
    "KnowledgeRetrievalResult",
    "KnowledgeRetrievalService",
    "KnowledgeRAGEngine",
    "KnowledgeRagError",
    "KnowledgeStore",
    "KnowledgeStoreHealth",
    "OllamaEmbeddingService",
    "QdrantKnowledgeStore",
    "RetrievalRequest",
    "RetrievalResultHit",
    "RetrievalScope",
    "ScoredStoreHit",
    "ScopeRequiredError",
    "SourceRecord",
    "VectorStoreUnavailableError",
    "default_knowledge_config",
]