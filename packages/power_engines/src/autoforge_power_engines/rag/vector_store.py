"""Platform Vector Store Interfaces and Persistent Adapters."""

from __future__ import annotations

import abc
import json
import logging
import math
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from autoforge_power_engines.rag.embeddings import BaseEmbeddingProvider, resolve_embedding_provider

logger = logging.getLogger("autoforge.power_engines.rag.vector_store")


class BaseVectorStore(abc.ABC):
    """Abstract interface for dense vector indexing and persistent similarity search."""

    @abc.abstractmethod
    def count(self) -> int:
        """Returns the total number of indexed vectors/chunks."""
        pass

    @abc.abstractmethod
    def upsert(
        self,
        chunks: List[Dict[str, Any]],
        embeddings: Optional[List[List[float]]] = None,
    ) -> int:
        """Indexes or updates chunks and their corresponding dense vectors."""
        pass

    @abc.abstractmethod
    def query(
        self,
        query_vector: List[float],
        top_k: int = 5,
        where: Optional[Dict[str, Any]] = None,
    ) -> List[Tuple[Dict[str, Any], float]]:
        """
        Executes vector similarity search against the index.
        Returns list of (chunk_dict, cosine_similarity_score [0..1]).
        """
        pass

    @abc.abstractmethod
    def delete_document(self, doc_id: str) -> int:
        """Purges all chunks associated with a doc_id or source_id."""
        pass

    @abc.abstractmethod
    def get_indexed_doc_ids(self) -> List[str]:
        """Returns unique list of document IDs registered in the index."""
        pass

    @abc.abstractmethod
    def reset(self) -> None:
        """Clears all vectors and metadata in the current collection."""
        pass


class PersistentChromaVectorStore(BaseVectorStore):
    """
    Persistent ChromaDB vector store adapter.
    Survives application restarts and guarantees tenant/project collection isolation.
    """

    def __init__(
        self,
        persist_dir: Path | str,
        collection_name: str = "autoforge_kb",
        embedding_provider: Optional[BaseEmbeddingProvider] = None,
    ):
        self.persist_dir = Path(persist_dir).resolve()
        self.persist_dir.mkdir(parents=True, exist_ok=True)
        self.collection_name = collection_name
        self.embedding_provider = embedding_provider or resolve_embedding_provider()

        import chromadb
        from chromadb.config import Settings

        self.client = chromadb.PersistentClient(
            path=str(self.persist_dir),
            settings=Settings(anonymized_telemetry=False, is_persistent=True),
        )

        fn = getattr(self.embedding_provider, "get_chroma_fn", lambda: None)()
        self.collection = self.client.get_or_create_collection(
            name=self.collection_name,
            embedding_function=fn,
            metadata={"hnsw:space": "cosine", "collection": self.collection_name},
        )
        logger.info(
            f"Initialized PersistentChromaVectorStore at {self.persist_dir} "
            f"(collection '{self.collection_name}', {self.collection.count()} chunks indexed)"
        )

    def count(self) -> int:
        return self.collection.count()

    def upsert(
        self,
        chunks: List[Dict[str, Any]],
        embeddings: Optional[List[List[float]]] = None,
    ) -> int:
        if not chunks:
            return 0

        ids: List[str] = []
        documents: List[str] = []
        metadatas: List[Dict[str, Any]] = []

        for c in chunks:
            cid = str(c.get("chunk_id", f"chk-{len(ids)}"))
            ids.append(cid)
            documents.append(str(c.get("content", "")))
            metas = {
                "source_id": str(c.get("source_id", "")),
                "file_path": str(c.get("file_path", "")),
                "document_type": str(c.get("document_type", "")),
                "line_start": int(c.get("line_start", 1)),
                "line_end": int(c.get("line_end", 1)),
                "content_hash": str(c.get("content_hash", "")),
            }
            metadatas.append(metas)

        # Compute embeddings if not provided and no internal chroma fn
        embed_payload = None
        if embeddings:
            embed_payload = embeddings
        elif getattr(self.embedding_provider, "get_chroma_fn", lambda: None)() is None:
            embed_payload = self.embedding_provider.embed_texts(documents)

        if embed_payload:
            self.collection.upsert(
                ids=ids,
                documents=documents,
                metadatas=metadatas,
                embeddings=embed_payload,
            )
        else:
            self.collection.upsert(
                ids=ids,
                documents=documents,
                metadatas=metadatas,
            )
        return len(chunks)

    def query(
        self,
        query_vector: List[float],
        top_k: int = 5,
        where: Optional[Dict[str, Any]] = None,
    ) -> List[Tuple[Dict[str, Any], float]]:
        if self.count() == 0:
            return []

        actual_k = min(top_k, self.count())
        kwargs: Dict[str, Any] = {
            "query_embeddings": [query_vector],
            "n_results": actual_k,
            "include": ["documents", "metadatas", "distances"],
        }
        if where:
            kwargs["where"] = where

        res = self.collection.query(**kwargs)
        if not res or not res.get("ids") or not res["ids"][0]:
            return []

        results: List[Tuple[Dict[str, Any], float]] = []
        ids = res["ids"][0]
        docs = res["documents"][0] if res.get("documents") else []
        metas = res["metadatas"][0] if res.get("metadatas") else []
        distances = res["distances"][0] if res.get("distances") else []

        for cid, doc, meta, dist in zip(ids, docs, metas, distances):
            # Cosine distance in Chroma is in [0, 2]; similarity = max(0, 1 - dist)
            sim = max(0.0, min(1.0, 1.0 - float(dist)))
            chunk_dict = {
                "chunk_id": cid,
                "content": doc,
                "source_id": meta.get("source_id", ""),
                "file_path": meta.get("file_path", ""),
                "document_type": meta.get("document_type", ""),
                "line_start": meta.get("line_start", 1),
                "line_end": meta.get("line_end", 1),
                "content_hash": meta.get("content_hash", ""),
                "score": round(sim, 4),
            }
            results.append((chunk_dict, round(sim, 4)))

        results.sort(key=lambda x: x[1], reverse=True)
        return results

    def delete_document(self, doc_id: str) -> int:
        count_before = self.count()
        # Query matching items by source_id or file_path
        existing = self.collection.get(where={"source_id": doc_id})
        del_ids = existing.get("ids", [])
        if not del_ids:
            existing_by_file = self.collection.get(where={"file_path": doc_id})
            del_ids = existing_by_file.get("ids", [])

        if del_ids:
            self.collection.delete(ids=del_ids)
            return len(del_ids)
        return 0

    def get_indexed_doc_ids(self) -> List[str]:
        items = self.collection.get(include=["metadatas"])
        doc_ids = set()
        for m in items.get("metadatas", []):
            if m and "source_id" in m:
                doc_ids.add(m["source_id"])
        return sorted(doc_ids)

    def reset(self) -> None:
        self.client.delete_collection(self.collection_name)
        fn = getattr(self.embedding_provider, "get_chroma_fn", lambda: None)()
        self.collection = self.client.create_collection(
            name=self.collection_name,
            embedding_function=fn,
            metadata={"hnsw:space": "cosine", "collection": self.collection_name},
        )


class InMemoryDenseVectorStore(BaseVectorStore):
    """
    Lightweight, persistent dense vector store with cosine similarity ranking.
    No binary C-extensions required; perfect for test doubles and constrained runtimes.
    """

    def __init__(
        self,
        persist_dir: Path | str,
        collection_name: str = "autoforge_kb",
        embedding_provider: Optional[BaseEmbeddingProvider] = None,
    ):
        self.persist_dir = Path(persist_dir).resolve()
        self.persist_dir.mkdir(parents=True, exist_ok=True)
        self.collection_name = collection_name
        self.storage_file = self.persist_dir / f"{collection_name}_vectors.json"
        self.embedding_provider = embedding_provider or resolve_embedding_provider()
        self._entries: List[Dict[str, Any]] = []
        self._load()

    def _load(self) -> None:
        if self.storage_file.exists():
            try:
                data = json.loads(self.storage_file.read_text(encoding="utf-8"))
                self._entries = data.get("entries", [])
            except Exception:
                self._entries = []
        else:
            self._entries = []

    def _save(self) -> None:
        payload = {"entries": self._entries}
        self.storage_file.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def count(self) -> int:
        return len(self._entries)

    def upsert(
        self,
        chunks: List[Dict[str, Any]],
        embeddings: Optional[List[List[float]]] = None,
    ) -> int:
        if not chunks:
            return 0

        if not embeddings:
            texts = [c.get("content", "") for c in chunks]
            embeddings = self.embedding_provider.embed_texts(texts)

        existing_map = {e["chunk_id"]: idx for idx, e in enumerate(self._entries)}
        for c, vec in zip(chunks, embeddings):
            cid = str(c.get("chunk_id", f"chk-{len(self._entries)}"))
            record = {
                "chunk_id": cid,
                "content": c.get("content", ""),
                "source_id": c.get("source_id", ""),
                "file_path": c.get("file_path", ""),
                "document_type": c.get("document_type", ""),
                "line_start": c.get("line_start", 1),
                "line_end": c.get("line_end", 1),
                "content_hash": c.get("content_hash", ""),
                "vector": vec,
            }
            if cid in existing_map:
                self._entries[existing_map[cid]] = record
            else:
                self._entries.append(record)
                existing_map[cid] = len(self._entries) - 1

        self._save()
        return len(chunks)

    @staticmethod
    def _cosine_similarity(v1: List[float], v2: List[float]) -> float:
        if not v1 or not v2 or len(v1) != len(v2):
            return 0.0
        dot = sum(a * b for a, b in zip(v1, v2))
        norm1 = math.sqrt(sum(a * a for a in v1))
        norm2 = math.sqrt(sum(b * b for b in v2))
        if norm1 < 1e-9 or norm2 < 1e-9:
            return 0.0
        return max(0.0, min(1.0, dot / (norm1 * norm2)))

    def query(
        self,
        query_vector: List[float],
        top_k: int = 5,
        where: Optional[Dict[str, Any]] = None,
    ) -> List[Tuple[Dict[str, Any], float]]:
        if not self._entries or not query_vector:
            return []

        scored: List[Tuple[Dict[str, Any], float]] = []
        for e in self._entries:
            if where:
                match = True
                for k, v in where.items():
                    if e.get(k) != v:
                        match = False
                        break
                if not match:
                    continue

            sim = self._cosine_similarity(query_vector, e.get("vector", []))
            item = dict(e)
            item.pop("vector", None)
            item["score"] = round(sim, 4)
            scored.append((item, round(sim, 4)))

        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:top_k]

    def delete_document(self, doc_id: str) -> int:
        before = len(self._entries)
        self._entries = [
            e for e in self._entries
            if e.get("source_id") != doc_id and e.get("file_path") != doc_id
        ]
        removed = before - len(self._entries)
        if removed > 0:
            self._save()
        return removed

    def get_indexed_doc_ids(self) -> List[str]:
        return sorted({e.get("source_id", "") for e in self._entries if e.get("source_id")})

    def reset(self) -> None:
        self._entries = []
        if self.storage_file.exists():
            self.storage_file.unlink()


def create_vector_store(
    backend: str,
    persist_dir: Path | str,
    collection_name: str = "autoforge_kb",
    embedding_provider: Optional[BaseEmbeddingProvider] = None,
) -> BaseVectorStore:
    """Factory creating appropriate vector store backend."""
    if backend == "chromadb":
        try:
            return PersistentChromaVectorStore(
                persist_dir=persist_dir,
                collection_name=collection_name,
                embedding_provider=embedding_provider,
            )
        except Exception as e:
            logger.warning(f"Failed to initialize ChromaDB ({e}); falling back to InMemoryDenseVectorStore.")
            return InMemoryDenseVectorStore(
                persist_dir=persist_dir,
                collection_name=collection_name,
                embedding_provider=embedding_provider,
            )
    else:
        return InMemoryDenseVectorStore(
            persist_dir=persist_dir,
            collection_name=collection_name,
            embedding_provider=embedding_provider,
        )
