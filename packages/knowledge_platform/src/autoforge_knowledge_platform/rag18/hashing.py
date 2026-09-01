"""Phase 18-D — deterministic content hashing.

Used for chunk identity, source identity, change detection and incremental
indexing. Everything is pure sha256 over the exact content bytes/text so the
pipeline is reproducible.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from autoforge_knowledge_platform.rag18.models import KnowledgeChunk


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_text(text: str) -> str:
    return sha256_bytes(text.encode("utf-8"))


def hash_file(path: str | Path) -> str:
    hasher = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(65536), b""):
            hasher.update(block)
    return hasher.hexdigest()


def source_hash_from_chunks(chunks: list[KnowledgeChunk]) -> str:
    """Deterministic source-level hash over ordered chunk content hashes."""
    ordered = sorted(chunks, key=lambda c: c.chunk_index)
    digest_input = "\n".join(c.content_hash for c in ordered).encode("utf-8")
    return sha256_bytes(digest_input)


def chunk_id_for(source_id: str, index: int) -> str:
    return f"{source_id}::{index}"


def vector_point_id(chunk_id: str) -> int:
    """Deterministic uint64 vector point id derived from the chunk id.

    Qdrant accepts integer point ids; a deterministic mapping makes upserts
    idempotent replaces and reindexing safe.
    """
    digest = hashlib.sha256(chunk_id.encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big") & 0x7FFFFFFFFFFFFFFF