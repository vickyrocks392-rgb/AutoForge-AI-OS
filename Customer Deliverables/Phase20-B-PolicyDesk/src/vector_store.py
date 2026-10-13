"""
PolicyDesk Knowledge Assistant — Persistent ChromaDB Vector Store Adapter.
Maintains persistent vector collection in external data directory.
Survives process restarts and guarantees isolated project namespacing.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import chromadb
from chromadb.config import Settings

from models import ChunkRecord
from embeddings import PolicyDeskEmbeddingProvider

logger = logging.getLogger("policydesk.vector_store")


class PolicyDeskVectorStore:
    """Manages persistent ChromaDB vector storage for PolicyDesk knowledge base."""

    def __init__(
        self,
        persist_dir: Path | str,
        collection_name: str = "policydesk_kb",
        embedding_provider: Optional[PolicyDeskEmbeddingProvider] = None,
    ):
        self.persist_dir = Path(persist_dir).resolve()
        self.persist_dir.mkdir(parents=True, exist_ok=True)
        self.collection_name = collection_name
        self.embedding_provider = embedding_provider or PolicyDeskEmbeddingProvider()

        # Initialize persistent Chroma client
        self.client = chromadb.PersistentClient(
            path=str(self.persist_dir),
            settings=Settings(anonymized_telemetry=False, is_persistent=True),
        )

        # Get or create collection with cosine similarity metric
        self.collection = self.client.get_or_create_collection(
            name=self.collection_name,
            embedding_function=self.embedding_provider.get_chroma_embedding_function(),
            metadata={"hnsw:space": "cosine", "project": "PolicyDesk", "version": "1.0"},
        )
        logger.info(
            f"Initialized persistent ChromaDB vector store at {self.persist_dir} "
            f"(collection '{self.collection_name}', {self.collection.count()} chunks currently indexed)"
        )

    def count_chunks(self) -> int:
        """Total chunks currently stored in the collection."""
        return self.collection.count()

    def add_chunks(self, chunks: List[ChunkRecord]) -> int:
        """Add or update chunks in the persistent vector index."""
        if not chunks:
            return 0

        ids: List[str] = []
        documents: List[str] = []
        metadatas: List[Dict[str, Any]] = []

        for c in chunks:
            ids.append(c.chunk_id)
            documents.append(c.content)
            metadatas.append({
                "doc_id": c.doc_id,
                "filename": c.filename,
                "format": c.format,
                "page": c.page if c.page is not None else -1,
                "line_start": c.line_start,
                "line_end": c.line_end,
                "section": c.section or "",
                "content_hash": c.content_hash,
            })

        self.collection.upsert(
            ids=ids,
            documents=documents,
            metadatas=metadatas,
        )
        logger.info(f"Upserted {len(chunks)} chunks into vector collection '{self.collection_name}'.")
        return len(chunks)

    def query(self, query_text: str, top_k: int = 5) -> List[Tuple[ChunkRecord, float]]:
        """
        Query the persistent index for top-k relevant chunks.
        Returns list of tuples: (ChunkRecord, similarity_score) sorted by relevance.
        """
        if self.collection.count() == 0 or not query_text.strip():
            return []

        actual_k = min(top_k, self.collection.count())
        res = self.collection.query(
            query_texts=[query_text],
            n_results=actual_k,
            include=["documents", "metadatas", "distances"],
        )

        results: List[Tuple[ChunkRecord, float]] = []
        if not res or not res.get("ids") or not res["ids"][0]:
            return []

        doc_ids = res["ids"][0]
        docs = res["documents"][0] if res.get("documents") else []
        metas = res["metadatas"][0] if res.get("metadatas") else []
        distances = res["distances"][0] if res.get("distances") else []

        for cid, doc_text, meta, dist in zip(doc_ids, docs, metas, distances):
            # Chroma cosine distance is in [0, 2]; similarity = max(0.0, 1.0 - dist)
            similarity = max(0.0, min(1.0, 1.0 - float(dist)))
            page_val = meta.get("page")
            actual_page = page_val if (page_val is not None and page_val != -1) else None

            record = ChunkRecord(
                chunk_id=cid,
                doc_id=meta.get("doc_id", "unknown"),
                filename=meta.get("filename", "unknown"),
                format=meta.get("format", "unknown"),
                page=actual_page,
                line_start=int(meta.get("line_start", 1)),
                line_end=int(meta.get("line_end", 1)),
                section=meta.get("section", ""),
                content=doc_text,
                content_hash=meta.get("content_hash", ""),
            )
            results.append((record, round(similarity, 4)))

        # Sort descending by similarity
        results.sort(key=lambda x: x[1], reverse=True)
        return results

    def delete_document(self, doc_id: str) -> int:
        """Remove all chunks belonging to a document from the persistent index."""
        existing = self.collection.get(where={"doc_id": doc_id})
        count_to_delete = len(existing.get("ids", []))
        if count_to_delete > 0:
            self.collection.delete(where={"doc_id": doc_id})
            logger.info(f"Deleted {count_to_delete} chunks for doc_id '{doc_id}' from vector collection.")
        return count_to_delete

    def get_indexed_doc_ids(self) -> List[str]:
        """Return list of distinct doc_ids indexed in the collection."""
        all_items = self.collection.get(include=["metadatas"])
        doc_ids = set()
        for meta in all_items.get("metadatas", []):
            if meta and "doc_id" in meta:
                doc_ids.add(meta["doc_id"])
        return sorted(doc_ids)

    def reset(self) -> None:
        """Safely reset and wipe the collection (retaining namespace)."""
        self.client.delete_collection(self.collection_name)
        self.collection = self.client.create_collection(
            name=self.collection_name,
            embedding_function=self.embedding_provider.get_chroma_embedding_function(),
            metadata={"hnsw:space": "cosine", "project": "PolicyDesk", "version": "1.0"},
        )
        logger.info(f"Reset vector collection '{self.collection_name}'.")
