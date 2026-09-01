"""Phase 18-D — explicit failure semantics.

Principles (requirement #29/#30/#48):

- Never fabricate retrieval, embeddings, vectors, scores or provenance.
- Unavailable local infrastructure raises a typed error (FAIL CLEARLY) or is
  skipped explicitly by live tests — it is never reported as PASS.
- Zero retrieval results are NOT an error: callers continue without knowledge
  and record ``no_relevant_knowledge``.
- There is deliberately NO cloud fallback anywhere in this package.
"""

from __future__ import annotations


class KnowledgeRagError(Exception):
    """Base error for the Phase 18-D knowledge subsystem."""


class VectorStoreUnavailableError(KnowledgeRagError):
    """The local vector database is unavailable (not running / no index)."""


class EmbeddingUnavailableError(KnowledgeRagError):
    """The local embedding runtime is unavailable.

    Never converted into a cloud call. Callers must fail clearly or skip the
    live test explicitly.
    """


class EmbeddingModelUnavailableError(EmbeddingUnavailableError):
    """The requested embedding model is not installed in the local runtime."""


class IncompatibleEmbeddingModelError(KnowledgeRagError):
    """Vectors in the store belong to a different embedding model/dimension.

    Recovery requires an explicit reindex (never silent mixing).
    """


class ScopeRequiredError(KnowledgeRagError):
    """A retrieval query was issued without an explicit project/workspace scope."""


class CorruptSourceError(KnowledgeRagError):
    """A source file could not be parsed/indexed safely."""