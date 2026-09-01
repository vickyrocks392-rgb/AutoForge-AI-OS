"""Phase 18-D — knowledge subsystem configuration.

Everything is local-first and configurable through environment variables so
the system can be tuned without code changes. No cloud configuration exists.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any


DEFAULT_COLLECTION_NAME = "autoforge_knowledge_v1"
DEFAULT_EMBEDDING_MODEL = "nomic-embed-text"
DEFAULT_EMBEDDING_DIMENSION = 768  # nomic-embed-text
DEFAULT_EMBEDDING_VERSION = "1"
DEFAULT_OLLAMA_BASE_URL = "http://127.0.0.1:11434"
DEFAULT_QDRANT_URL = "http://127.0.0.1:6333"


def _env_int(name: str, default: int) -> int:
    val = os.environ.get(name)
    if val is None or not val.strip():
        return default
    try:
        return int(val.strip())
    except ValueError:
        return default


def _env_float(name: str, default: float | None) -> float | None:
    val = os.environ.get(name)
    if val is None or not val.strip():
        return default
    try:
        return float(val.strip())
    except ValueError:
        return default


@dataclass(frozen=True)
class KnowledgeConfig:
    """Configuration for the Phase 18-D knowledge subsystem.

    ``qdrant_path`` selects the embedded (dev/test) vector backend. When it is
    ``None`` the production self-hosted server at ``qdrant_url`` (or the
    environment default ``http://127.0.0.1:6333``) is used.
    """

    # Vector database
    collection_name: str = DEFAULT_COLLECTION_NAME
    qdrant_url: str | None = None
    qdrant_path: str | None = None
    qdrant_timeout_seconds: float = 30.0

    # Embeddings (local)
    embedding_model: str = DEFAULT_EMBEDDING_MODEL
    embedding_dimension: int = DEFAULT_EMBEDDING_DIMENSION
    embedding_version: str = DEFAULT_EMBEDDING_VERSION
    ollama_base_url: str = DEFAULT_OLLAMA_BASE_URL
    ollama_timeout_seconds: float = 120.0
    ollama_batch_size: int = 16

    # Index-state metadata (SQLite — metadata/state ONLY, not vector retrieval)
    index_state_path: str | None = None

    # Chunking
    chunk_max_chars: int = 2400
    chunk_overlap_chars: int = 160

    # Discovery
    max_file_bytes: int = 512_000

    # Retrieval / context assembly
    top_k_default: int = 6
    score_threshold_default: float | None = None
    evidence_max_chunks: int = 6
    evidence_max_total_chars: int = 6000
    evidence_content_chars: int = 1400

    # Hard offline guard: retrieval/embedding must only reach local hosts.
    allowed_embedding_hosts: tuple[str, ...] = ("127.0.0.1", "localhost", "::1")
    allow_unscoped_retrieval: bool = False

    workspace_root: str | None = None

    def __post_init__(self) -> None:
        if self.qdrant_url is None:
            # Read from env even if qdrant_path is set (env always wins over defaults)
            object.__setattr__(self, "qdrant_url", os.environ.get("AUTOFORGE_QDRANT_URL", DEFAULT_QDRANT_URL))
        if self.ollama_base_url == DEFAULT_OLLAMA_BASE_URL:
            object.__setattr__(self, "ollama_base_url", os.environ.get("AUTOFORGE_OLLAMA_URL", DEFAULT_OLLAMA_BASE_URL))
        if self.embedding_model == DEFAULT_EMBEDDING_MODEL:
            object.__setattr__(self, "embedding_model", os.environ.get("AUTOFORGE_EMBEDDING_MODEL", DEFAULT_EMBEDDING_MODEL))
        if self.index_state_path is None and self.workspace_root:
            object.__setattr__(
                self,
                "index_state_path",
                str(Path(self.workspace_root) / ".autoforge" / "knowledge" / "index_state.sqlite3"),
            )
    def make_derived(
        self,
        *,
        workspace_root: str | Path | None = None,
        index_state_path: str | Path | None = None,
    ) -> "KnowledgeConfig":
        """Produce a copy with derived local paths resolved."""
        root = Path(workspace_root or self.workspace_root or Path.cwd())
        return KnowledgeConfig(
            collection_name=self.collection_name,
            qdrant_url=self.qdrant_url,
            qdrant_path=self.qdrant_path,
            qdrant_timeout_seconds=self.qdrant_timeout_seconds,
            embedding_model=self.embedding_model,
            embedding_dimension=self.embedding_dimension,
            embedding_version=self.embedding_version,
            ollama_base_url=self.ollama_base_url,
            ollama_timeout_seconds=self.ollama_timeout_seconds,
            ollama_batch_size=self.ollama_batch_size,
            index_state_path=str(index_state_path) if index_state_path else str(
                Path(root) / ".autoforge" / "knowledge" / "index_state.sqlite3"
            ),
            chunk_max_chars=self.chunk_max_chars,
            chunk_overlap_chars=self.chunk_overlap_chars,
            max_file_bytes=self.max_file_bytes,
            top_k_default=self.top_k_default,
            score_threshold_default=self.score_threshold_default,
            evidence_max_chunks=self.evidence_max_chunks,
            evidence_max_total_chars=self.evidence_max_total_chars,
            evidence_content_chars=self.evidence_content_chars,
            allowed_embedding_hosts=self.allowed_embedding_hosts,
            allow_unscoped_retrieval=self.allow_unscoped_retrieval,
            workspace_root=str(root),
        )

    def default_vector_db_path(self, workspace_root: str | Path | None = None) -> str:
        root = Path(workspace_root or self.workspace_root or Path.cwd())
        return str(root / ".autoforge" / "knowledge" / "vector-db")

    @property
    def schema_signature(self) -> dict[str, Any]:
        """Embedding-signature used to detect incompatible indexes."""
        return {
            "embedding_model": self.embedding_model,
            "embedding_dimension": self.embedding_dimension,
            "embedding_version": self.embedding_version,
            "collection_name": self.collection_name,
        }


def default_knowledge_config(workspace_root: str | Path | None = None) -> KnowledgeConfig:
    """Convenience factory honouring repository conventions.

    Storage lands under ``<workspace>/.autoforge/knowledge/``:
      - vector DB at ``knowledge/vector-db/`` (Qdrant persistent storage)
      - index-state metadata at ``knowledge/index_state.sqlite3``
    """
    return KnowledgeConfig().make_derived(workspace_root=workspace_root)