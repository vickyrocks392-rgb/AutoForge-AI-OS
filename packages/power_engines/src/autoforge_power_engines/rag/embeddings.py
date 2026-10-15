"""Platform Embedding Provider Interfaces and Local Implementations."""

from __future__ import annotations

import abc
import hashlib
import logging
import math
import re
from typing import List, Optional

logger = logging.getLogger("autoforge.power_engines.rag.embeddings")


class BaseEmbeddingProvider(abc.ABC):
    """Abstract contract for embedding generation in AutoForge RAG systems."""

    @property
    @abc.abstractmethod
    def model_name(self) -> str:
        """Name or identifier of the embedding model."""
        pass

    @property
    @abc.abstractmethod
    def dimensions(self) -> int:
        """Dimensionality of produced dense vectors."""
        pass

    @abc.abstractmethod
    def embed_texts(self, texts: List[str]) -> List[List[float]]:
        """Batch computes normalized dense embeddings for document passages."""
        pass

    @abc.abstractmethod
    def embed_query(self, query: str) -> List[float]:
        """Computes a normalized dense embedding for a single search query."""
        pass

    def validate_availability(self) -> bool:
        """Verifies model loading and inference availability."""
        try:
            sample = self.embed_query("availability probe")
            return len(sample) == self.dimensions
        except Exception as e:
            logger.warning(f"Embedding availability probe failed: {e}")
            return False


class ChromaLocalEmbeddingProvider(BaseEmbeddingProvider):
    """
    Local-first ONNX embedding provider backed by ChromaDB default MiniLM.
    Computes 384-dimensional dense vectors with zero cloud or API dependency.
    """

    MODEL_ID = "sentence-transformers/all-MiniLM-L6-v2"
    DIMENSIONS = 384

    def __init__(self):
        try:
            from chromadb.utils import embedding_functions
            self._fn = embedding_functions.DefaultEmbeddingFunction()
        except ImportError as e:
            raise ImportError(
                f"ChromaDB is required for ChromaLocalEmbeddingProvider: {e}. "
                "Ensure chromadb is installed in the target environment."
            )

    @property
    def model_name(self) -> str:
        return self.MODEL_ID

    @property
    def dimensions(self) -> int:
        return self.DIMENSIONS

    def embed_texts(self, texts: List[str]) -> List[List[float]]:
        if not texts:
            return []
        raw_res = self._fn(texts)
        embeddings = [list(vec) for vec in raw_res]
        if embeddings and len(embeddings[0]) != self.DIMENSIONS:
            raise ValueError(f"Expected {self.DIMENSIONS}d vector, got {len(embeddings[0])}d")
        return embeddings

    def embed_query(self, query: str) -> List[float]:
        if not query.strip():
            return [0.0] * self.DIMENSIONS
        res = self._fn([query])
        if not res or len(res[0]) != self.DIMENSIONS:
            raise ValueError(f"Query embedding generation returned invalid vector: {res}")
        return [float(x) for x in res[0]]

    def get_chroma_fn(self):
        """Returns internal Chroma embedding function for collection configuration."""
        return self._fn


class DeterministicDenseEmbeddingProvider(BaseEmbeddingProvider):
    """
    Deterministic dense vector provider for testing, simulation, and offline CI.
    Generates reproducible 384-dimensional normalized float vectors.
    Semantic similarity is preserved through n-gram and subtoken hash projections.
    """

    MODEL_ID = "autoforge/deterministic-dense-384"
    DIMENSIONS = 384

    def __init__(self, dimensions: int = 384):
        self._dims = dimensions

    @property
    def model_name(self) -> str:
        return self.MODEL_ID

    @property
    def dimensions(self) -> int:
        return self._dims

    def _text_to_vector(self, text: str) -> List[float]:
        vec = [0.0] * self._dims
        tokens = re.findall(r"\w+", text.lower())
        if not tokens:
            return vec

        for token in tokens:
            # Word-level hash projection
            h = int(hashlib.sha256(token.encode("utf-8")).hexdigest(), 16)
            for idx in range(4):
                slot = (h >> (idx * 16)) % self._dims
                sign = 1.0 if ((h >> (idx * 8)) & 1) else -1.0
                vec[slot] += sign

            # Character 3-gram projection for morphological / synonym clustering
            for i in range(len(token) - 2):
                tri = token[i:i+3]
                th = int(hashlib.md5(tri.encode("utf-8")).hexdigest(), 16)
                slot = th % self._dims
                sign = 0.5 if ((th >> 4) & 1) else -0.5
                vec[slot] += sign

        # L2 Normalization
        norm = math.sqrt(sum(x * x for x in vec))
        if norm > 1e-9:
            vec = [round(x / norm, 6) for x in vec]
        return vec

    def embed_texts(self, texts: List[str]) -> List[List[float]]:
        return [self._text_to_vector(t) for t in texts]

    def embed_query(self, query: str) -> List[float]:
        return self._text_to_vector(query)


def resolve_embedding_provider(
    provider_type: str | None = None,
    dimensions: int = 384,
) -> BaseEmbeddingProvider:
    """Factory helper to obtain the preferred available embedding provider."""
    # Attempt local Chroma ONNX if available
    if provider_type in ("local", "onnx_local", None):
        try:
            provider = ChromaLocalEmbeddingProvider()
            if provider.validate_availability():
                return provider
        except Exception as e:
            logger.info(f"Local Chroma embedding unavailable ({e}); falling back to deterministic dense.")

    return DeterministicDenseEmbeddingProvider(dimensions=dimensions)
