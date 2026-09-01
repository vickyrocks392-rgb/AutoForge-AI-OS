"""Phase 18-D — local embedding abstraction.

``EmbeddingService`` is the AutoForge-owned seam. The default implementation
is ``OllamaEmbeddingService`` which talks ONLY to a local Ollama daemon
(e.g. ``nomic-embed-text``). There is deliberately no cloud embedding
configuration and no fallback: if the local runtime is unavailable the caller
receives :class:`EmbeddingUnavailableError` (FAIL CLEARLY) or a live test
skips explicitly.
"""

from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.request
from abc import ABC, abstractmethod
from typing import Any

from autoforge_knowledge_platform.rag18.config import DEFAULT_EMBEDDING_DIMENSION, DEFAULT_EMBEDDING_MODEL
from autoforge_knowledge_platform.rag18.errors import (
    EmbeddingModelUnavailableError,
    EmbeddingUnavailableError,
)

logger = logging.getLogger(__name__)

_LOCALHOSTS = {"127.0.0.1", "localhost", "::1", "[::1]"}


class EmbeddingService(ABC):
    """Provider/model agnostic embedding computation."""

    @property
    @abstractmethod
    def model(self) -> str:
        """Embedding model identifier (e.g. ``nomic-embed-text``)."""

    @property
    @abstractmethod
    def dimension(self) -> int:
        """Vector dimension of this embedding model."""

    @property
    @abstractmethod
    def embedding_version(self) -> str:
        """Scheme version; bump on incompatible embedding changes."""

    @abstractmethod
    def is_available(self) -> bool:
        """Probe the local embedding runtime without computing."""

    @abstractmethod
    async def embed(self, text: str) -> list[float]:
        """Embed a single piece of text. Never returns a fabricated vector."""

    async def embed_batch(self, texts: list[str], batch_size: int = 16) -> list[list[float]]:
        """Embed a batch of texts (default loops single embeddings)."""
        vectors: list[list[float]] = []
        for i in range(0, len(texts), batch_size):
            chunk = texts[i : i + batch_size]
            for text in chunk:
                vectors.append(await self.embed(text))
        return vectors


def _assert_local_host(base_url: str) -> None:
    """Offline guard: embeddings may only come from a local host."""
    url = base_url.split("://", 1)[-1]
    host = url.split(":")[0].strip("/").strip()
    if host not in _LOCALHOSTS:
        raise EmbeddingUnavailableError(
            f"Embedding base URL '{base_url}' resolves to non-local host '{host}'. "
            "Phase 18-D requires local-only embeddings."
        )


class OllamaEmbeddingService(EmbeddingService):
    """Local Ollama embedding provider (``/api/embed`` batch endpoint)."""

    def __init__(
        self,
        *,
        base_url: str = "http://127.0.0.1:11434",
        model: str = DEFAULT_EMBEDDING_MODEL,
        dimension: int = DEFAULT_EMBEDDING_DIMENSION,
        timeout_seconds: float = 120.0,
        embedding_version: str = "1",
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._expected_dimension = dimension
        self._timeout = timeout_seconds
        self._embedding_version = embedding_version
        self._verified_dimension: int | None = None
        _assert_local_host(self._base_url)

    # ── Metadata ──────────────────────────────────────────────────────────
    @property
    def model(self) -> str:
        return self._model

    @property
    def dimension(self) -> int:
        if self._verified_dimension is not None:
            return self._verified_dimension
        return self._expected_dimension

    @property
    def embedding_version(self) -> str:
        return self._embedding_version

    def _request(self, endpoint: str, payload: dict[str, Any]) -> dict[str, Any]:
        url = f"{self._base_url}{endpoint}"
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as response:
                body = response.read().decode("utf-8")
                return json.loads(body) if body else {}
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                raise EmbeddingModelUnavailableError(
                    f"Embedding model '{self._model}' is not installed in local Ollama"
                ) from exc
            raise EmbeddingUnavailableError(
                f"Local Ollama embedding failed: HTTP {exc.code}"
            ) from exc
        except (urllib.error.URLError, OSError) as exc:
            raise EmbeddingUnavailableError(
                f"Local Ollama embedding endpoint unreachable at {self._base_url}: {exc}"
            ) from exc

    def is_available(self) -> bool:
        """Check the model is installed (``/api/tags``) and dimension matches."""
        try:
            url = f"{self._base_url}/api/tags"
            req = urllib.request.Request(url, method="GET")
            with urllib.request.urlopen(req, timeout=min(self._timeout, 30.0)) as response:
                body = response.read().decode("utf-8")
            tags: dict[str, Any] = json.loads(body) if body else {}
        except Exception as exc:  # noqa: BLE001 - probe must not raise
            logger.debug("Embedding availability probe failed: %s", exc)
            return False
        models = tags.get("models") or []
        names = {m.get("name", "").split(":", 1)[0] for m in models}
        base = self._model.split(":", 1)[0]
        if base not in names:
            return False
        try:
            probe = self._request("/api/embed", {"model": self._model, "input": ["probe"]})
            emb = probe.get("embeddings") or []
            if not emb:
                return False
            if self._verified_dimension is None:
                self._verified_dimension = len(emb[0])
            return self._verified_dimension == self._expected_dimension
        except Exception as exc:  # noqa: BLE001
            logger.debug("Embedding dimension probe failed: %s", exc)
            return False

    async def embed(self, text: str) -> list[float]:
        if not text:
            raise EmbeddingUnavailableError("Cannot embed empty text")
        started = time.perf_counter()
        body = self._request("/api/embed", {"model": self._model, "input": [text]})
        embeddings = body.get("embeddings") or []
        if not embeddings or not isinstance(embeddings[0], list):
            raise EmbeddingUnavailableError(
                f"Local Ollama returned no embedding for model '{self._model}'"
            )
        vector = embeddings[0]
        if self._verified_dimension is None:
            self._verified_dimension = len(vector)
        if len(vector) != self._expected_dimension:
            raise EmbeddingUnavailableError(
                f"Embedding dimension mismatch: model '{self._model}' produced "
                f"{len(vector)} dims; expected {self._expected_dimension}"
            )
        logger.debug(
            "embed_one model=%s dim=%s elapsed_ms=%.1f",
            self._model, len(vector), (time.perf_counter() - started) * 1000,
        )
        return [float(v) for v in vector]

    async def embed_batch(self, texts: list[str], batch_size: int = 16) -> list[list[float]]:
        """Batch embedding via the local ``/api/embed`` endpoint."""
        if not texts:
            return []
        started = time.perf_counter()
        vectors: list[list[float]] = []
        for i in range(0, len(texts), batch_size):
            batch = texts[i : i + batch_size]
            body = self._request("/api/embed", {"model": self._model, "input": batch})
            embeddings = body.get("embeddings") or []
            if len(embeddings) != len(batch):
                raise EmbeddingUnavailableError(
                    f"Local Ollama returned {len(embeddings)} embeddings for "
                    f"batch of {len(batch)} items"
                )
            for raw in embeddings:
                if not isinstance(raw, list) or len(raw) != self._expected_dimension:
                    raise EmbeddingUnavailableError(
                        f"Embedding dimension mismatch: expected {self._expected_dimension}"
                    )
                vectors.append([float(v) for v in raw])
            if self._verified_dimension is None and vectors:
                self._verified_dimension = len(vectors[0])
        logger.info(
            "embed_batch model=%s n=%d batch_size=%d elapsed_ms=%.1f",
            self._model, len(texts), batch_size, (time.perf_counter() - started) * 1000,
        )
        return vectors
