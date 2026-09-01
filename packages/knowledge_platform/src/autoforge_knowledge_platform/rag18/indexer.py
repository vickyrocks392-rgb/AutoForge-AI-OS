"""Phase 18-D - incremental repository indexer.

Coordinates discovery, parsing, chunking, embedding and upsert into the local
vector store. Supports incremental (change-detection) and full-force reindexing.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from pathlib import Path

from autoforge_knowledge_platform.rag18.chunking import StructureAwareChunker
from autoforge_knowledge_platform.rag18.config import KnowledgeConfig
from autoforge_knowledge_platform.rag18.discovery import SourceCandidate, SourceDiscovery
from autoforge_knowledge_platform.rag18.embedding import EmbeddingService
from autoforge_knowledge_platform.rag18.errors import (
    EmbeddingUnavailableError,
    IncompatibleEmbeddingModelError,
)
from autoforge_knowledge_platform.rag18.hashing import hash_file
from autoforge_knowledge_platform.rag18.index_state import IndexStateStore
from autoforge_knowledge_platform.rag18.models import IndexReport, KnowledgeChunk, SourceRecord
from autoforge_knowledge_platform.rag18.store import KnowledgeStore

logger = logging.getLogger(__name__)


class KnowledgeIndexer:
    """Incremental repository-aware indexer into a local vector store."""

    def __init__(
        self,
        store: KnowledgeStore,
        embedding: EmbeddingService,
        config: KnowledgeConfig | None = None,
    ):
        self._store = store
        self._embedding = embedding
        self._config = config or KnowledgeConfig()
        self._discovery = SourceDiscovery(max_file_bytes=self._config.max_file_bytes)
        self._chunker = StructureAwareChunker(
            max_chars=self._config.chunk_max_chars,
            overlap_chars=self._config.chunk_overlap_chars,
        )

    @property
    def store(self) -> KnowledgeStore:
        return self._store

    @property
    def embedding(self) -> EmbeddingService:
        return self._embedding


    async def initialize(self) -> None:
        """Ensure signature + collection compatibility before indexing."""
        if not self._embedding.is_available():
            raise EmbeddingUnavailableError(
                f"Local embedding model '{self._embedding.model}' is unavailable. "
                "Refusing to index without real embeddings."
            )
        state = IndexStateStore(self._config.index_state_path)
        try:
            stored = state.get_embedding_signature()
        finally:
            state.close()
        signature = self._config.schema_signature

        if stored is not None and stored != signature:
            raise IncompatibleEmbeddingModelError(
                f"Indexed vectors were produced with {stored}, current embedding "
                f"configuration is {signature}. Run an explicit reindex before "
                "mixing vectors from different embedding models."
            )

        await self._store.set_expected_dimension(self._config.embedding_dimension)
        await self._store.initialize()
        state = IndexStateStore(self._config.index_state_path)
        try:
            state.set_embedding_signature(signature)
        finally:
            state.close()


    async def index_repository(
        self,
        workspace_root,
        *,
        project_id=None,
        workflow_id=None,
        execution_id=None,
        force=False,
    ) -> IndexReport:
        """Index (or incrementally update) a repository into local vectors."""
        started = time.perf_counter()
        root_str = str(Path(workspace_root).resolve())  # normalize symlinks
        candidates = self._discovery.discover(root_str)

        state = IndexStateStore(self._config.index_state_path)
        existing = state.list_paths(project_id=project_id, workspace_root=root_str)

        inserted = updated = unchanged = deleted = 0
        errors = []
        all_upserted = []

        # 1. Detect deletions (files removed since last index).
        if not force:
            existing_paths = {c.relative_path for c in candidates}
            for fpath, record in existing.items():
                if fpath not in existing_paths:
                    state.delete_source(record.source_id)
                    try:
                        await self._store.delete_by_source(record.source_id)
                    except Exception as exc:
                        logger.warning(
                            "Failed to delete source %s from store: %s",
                            record.source_id, exc,
                        )
                    deleted += 1

        # 2. Discover + parse candidates.
        work = []
        _LANG = {
            "py": "python",
            "ts": "typescript", "tsx": "typescript",
            "js": "javascript", "jsx": "javascript",
            "mjs": "javascript", "cjs": "javascript",
            "go": "go", "rs": "rust", "java": "java",
            "rb": "ruby", "php": "php",
            "c": "c", "h": "c",
            "cpp": "cpp", "hpp": "cpp",
            "cs": "csharp", "swift": "swift",
            "kt": "kotlin", "kts": "kotlin",
            "sh": "bash", "sql": "sql",
            "scala": "scala", "ex": "elixir", "exs": "elixir",
            "md": "markdown", "markdown": "markdown", "mdx": "markdown",
            "txt": "text", "rst": "rst", "adoc": "asciidoc",
        }
        _DTYPE = {
            "py": "python_source",
            "ts": "typescript_source", "tsx": "typescript_source",
            "js": "javascript_source", "jsx": "javascript_source",
            "mjs": "javascript_source", "cjs": "javascript_source",
            "go": "go_source", "rs": "rust_source", "java": "java_source",
            "rb": "ruby_source", "php": "php_source",
            "c": "c_source", "h": "c_source",
            "cpp": "cpp_source", "hpp": "cpp_source",
            "cs": "csharp_source", "swift": "swift_source",
            "kt": "kotlin_source", "kts": "kotlin_source",
            "sh": "shell_script", "sql": "sql_source",
            "scala": "scala_source", "ex": "elixir_source", "exs": "elixir_source",
            "md": "markdown", "markdown": "markdown", "mdx": "markdown",
            "rst": "rst", "adoc": "asciidoc",
        }

        for candidate in candidates:
            try:
                source_hash = hash_file(candidate.absolute_path)
            except OSError as exc:
                errors.append(f"Cannot read {candidate.relative_path}: {exc}")
                continue

            # If the path is in the index AND its content hash is unchanged, skip.
            # If the path is in the index BUT the hash changed, delete the old
            # source before re-indexing (so its stale chunks do not linger).
            if not force:
                prev = existing.get(candidate.relative_path)
                if prev is not None:
                    if prev.source_id == source_hash:
                        unchanged += 1
                        continue
                    # content changed → drop the old source from the store + state
                    state.delete_source(prev.source_id)
                    try:
                        await self._store.delete_by_source(prev.source_id)
                    except Exception as exc:
                        logger.warning(
                            "Failed to delete stale source %s from store: %s",
                            prev.source_id, exc,
                        )
                    deleted += 1

            try:
                text = Path(candidate.absolute_path).read_text(encoding="utf-8", errors="replace")
            except OSError as exc:
                errors.append(f"Cannot read {candidate.relative_path}: {exc}")
                continue

            suffix = candidate.relative_path.rsplit(".", 1)[-1].lower()
            language = _LANG.get(suffix, "text")
            document_type = _DTYPE.get(suffix, "plain_text")

            try:
                chunks = self._chunker.chunk(
                    text,
                    path=candidate.relative_path,
                    document_type=document_type,
                    language=language,
                    source_id=source_hash,
                    workspace_root=root_str,
                    project_id=project_id,
                    workflow_id=workflow_id,
                    execution_id=execution_id,
                    embedding_model=self._embedding.model,
                    embedding_dimension=self._embedding.dimension,
                    embedding_version=self._embedding.embedding_version,
                )
            except Exception as exc:
                errors.append(f"Chunking {candidate.relative_path}: {exc}")
                continue

            if not chunks:
                continue

            for chunk in chunks:
                work.append((candidate, chunk))

        # 3. Embed (local) + upsert (vector DB).
        if work:
            vectors = await self._embedding.embed_batch(
                [chunk.content for _, chunk in work],
                batch_size=self._config.ollama_batch_size,
            )
            all_upserted.extend(chunk for _, chunk in work)
            await self._store.upsert_chunks(all_upserted, vectors)

            # 4. Persist source records keyed by deterministic source hash.
            by_source = {}
            for chunk in all_upserted:
                by_source.setdefault(chunk.source_id, []).append(chunk)

            for src_id, src_chunks in by_source.items():
                sample = src_chunks[0]
                recorded = SourceRecord(
                    source_id=src_id,
                    project_id=project_id,
                    workspace_root=root_str,
                    path=sample.path,
                    source_hash=src_id,
                    document_type=sample.document_type,
                    language=sample.language,
                    chunk_count=len(src_chunks),
                    embedding_model=self._embedding.model,
                    embedding_dimension=self._embedding.dimension,
                    embedding_version=self._embedding.embedding_version,
                    indexed_at=datetime.now(timezone.utc).isoformat(),
                    updated_at=datetime.now(timezone.utc).isoformat(),
                )
                prev = existing.get(sample.path)
                state.upsert_source(recorded)
                if prev is None:
                    inserted += 1
                else:
                    updated += 1

        state.close()
        total_chunks = await self._safe_count()
        return IndexReport(
            workspace_root=root_str,
            project_id=project_id,
            sources_scanned=len(candidates),
            inserted=inserted,
            updated=updated,
            unchanged=unchanged,
            deleted=deleted,
            total_chunks=total_chunks,
            embedding_model=self._embedding.model,
            duration_ms=(time.perf_counter() - started) * 1000.0,
            errors=errors,
        )

    async def _safe_count(self) -> int:
        try:
            return await self._store.count()
        except Exception:
            return -1


