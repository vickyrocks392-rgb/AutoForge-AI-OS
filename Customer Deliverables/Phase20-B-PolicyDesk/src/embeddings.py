"""
PolicyDesk Knowledge Assistant — Local Embeddings Provider.
Wraps ONNX MiniLM (all-MiniLM-L6-v2) for local 384-dimensional dense vectors.
Caches model weights externally with zero network dependence after initial download.
"""

from __future__ import annotations

import logging
from typing import List
from chromadb.utils import embedding_functions

logger = logging.getLogger("policydesk.embeddings")


class PolicyDeskEmbeddingProvider:
    """Provides local embedding computation for PolicyDesk knowledge chunks and queries."""

    MODEL_ID = "sentence-transformers/all-MiniLM-L6-v2"
    DIMENSIONS = 384

    def __init__(self):
        self._fn = embedding_functions.DefaultEmbeddingFunction()

    @property
    def model_name(self) -> str:
        return self.MODEL_ID

    @property
    def dimensions(self) -> int:
        return self.DIMENSIONS

    def embed_texts(self, texts: List[str]) -> List[List[float]]:
        """Compute embeddings for a batch of text chunks."""
        if not texts:
            return []
        embeddings = self._fn(texts)
        # Validate dimensions
        if embeddings and len(embeddings[0]) != self.DIMENSIONS:
            raise ValueError(
                f"Embedding dimension mismatch: expected {self.DIMENSIONS}, got {len(embeddings[0])}"
            )
        return embeddings

    def embed_query(self, query: str) -> List[float]:
        """Compute embedding for a single user query."""
        res = self._fn([query])
        if not res or len(res[0]) != self.DIMENSIONS:
            raise ValueError(
                f"Query embedding dimension mismatch: expected {self.DIMENSIONS}, got {len(res[0]) if res else 0}"
            )
        return res[0]

    def get_chroma_embedding_function(self):
        """Returns the embedding function instance for direct ChromaDB integration."""
        return self._fn
