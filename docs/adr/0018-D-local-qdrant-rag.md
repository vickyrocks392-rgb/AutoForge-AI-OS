# ADR-0018-D: Local Qdrant RAG — Self-Hosted, Offline-Capable Knowledge Integration

**Status:** Accepted  
**Date:** 2026-08-31  
**Supersedes:** ADR-0018-C (ollama-only embedding)  
**Deciders:** AutoForge Team

---

## Context

Phase 18-C wired Ollama embeddings into AutoForge's reasoning pipeline but
provided no persistent vector store. Reasoning context carried raw text chunks
that had to be re-embedded on every request. We need:

1. A **persistent**, queryable **vector database** that survives restarts.
2. **Real ANN/HNSW** indexing (not flat-list cosine similarity).
3. **Local-first / offline-capable** — no cloud dependencies.
4. **Privacy-preserving** — all data stays inside `.autoforge/`.
5. Full integration into the Phase 18-C production orchestration path.

---

## Decision

We adopt **Qdrant** (Rust/HNSW) as the local vector store and **Ollama**
(`nomic-embed-text`, 768-dim) as the embedding service, wired into the
existing `KnowledgeRAGEngine` facade.

### Architecture

```
Workspace files
      │
      ▼
FileDiscoveryService  (ignore patterns, file-type rules)
      │
      ▼
StructureAwareChunker  (markdown / code / plain segmentation)
      │
      ▼
OllamaEmbeddingService  (nomic-embed-text, 768-dim, batched)
      │
      ▼
QdrantKnowledgeStore  (HNSW index, local path, localhost-only)
      │
      ▼
KnowledgeRAGEngine  (orchestrator of store + retrieval)
      │
      ▼
OrchestrationEngine  (calls retrieve_for_context per stage)
      │
      ▼
AIInfrastructureAdapter.generate_plan  (injects [RETRIEVED KNOWLEDGE / EVIDENCE])
```

### Key Design Decisions

| Decision | Rationale |
|---|---|
| **Real Qdrant (not embedded mode)** | HNSW index requires a Rust process; embedded Python mode is experimental. |
| **Localhost-only enforcement** | `_assert_local_url` in `qdrant_store.py` and `embedding.py` rejects non-localhost URLs. |
| **Lazy client construction** | `QdrantKnowledgeStore._lazy_client()` defers `qdrant_client.QdrantClient()` until first use. |
| **Schema-signature collection naming** | `schema_signature` (model + dimension + version) prevents dimension-mismatch crashes when the embedding model changes. |
| **Source-id as deterministic hash** | `hash_file()` (BLAKE2b of first 64 KiB + file size) is the stable `source_id` key for incremental indexing. |
| **Incremental index** | `index_repository` compares discovered files against `IndexStateStore` and only re-embeds changed/added files. |
| **Graceful degradation** | If Qdrant or Ollama is unavailable, `retrieve_for_context` returns an empty result set at DEBUG level. |

### Storage Layout

```
.autoforge/knowledge/
├── vector-db/          # Qdrant persistent storage (binary)
└── index-state.json   # SourceRecord ledger (source_id -> metadata)
~/.ollama/             # Ollama model weights (standard Ollama location)
```

---

## Consequences

### Positive
- Vector search survives restarts (Qdrant persistence).
- Real HNSW ANN gives sub-10ms recall on 10k-100k chunks.
- Fully offline-capable; no network required once Ollama + Qdrant are running.
- RAG evidence injected into every stage's `generate_plan` prompt.
- Incremental indexing means re-indexing a 10 000-file workspace takes seconds.

### Negative
- Requires two background services (`qdrant` + `ollama serve`).
- `qdrant-client` is a new dependency for the knowledge_platform package.

### Neutral
- If neither service is running, the orchestrator degrades to zero-shot reasoning
  (no evidence block injected). Acceptable for Phase 0 / demo runs.

---

## Rollout Checklist

- [x] `qdrant_store.py` — full `QdrantKnowledgeStore` with HNSW
- [x] `embedding.py` — `OllamaEmbeddingService` with `_assert_local_url`
- [x] `chunking.py` — `StructureAwareChunker` with markdown/code/plain paths
- [x] `indexer.py` — `KnowledgeIndexer` with incremental index
- [x] `facade.py` — `KnowledgeRAGEngine` wiring
- [x] `ExecutionContext.retrieved_knowledge` field
- [x] `evidence.assemble_evidence()` helper
- [x] `OrchestrationEngine._retrieve_knowledge_for_context()` wired into stage execution
- [x] `AIInfrastructureAdapter.generate_plan` injects `[RETRIEVED KNOWLEDGE / EVIDENCE]`
- [x] `scripts/index_knowledge.py` with pre-flight checks
- [x] `pyproject.toml` updated with `qdrant-client>=1.7.0`
- [x] This ADR

## References
- Qdrant Quickstart: https://qdrant.tech/documentation/quick-start/
- Ollama Embeddings API: https://github.com/ollama/ollama/blob/main/docs/api.md#embeddings
- nomic-embed-text: https://ollama.com/library/nomic-embed-text
- ADR-0018-A, ADR-0018-B, ADR-0018-C (prior AutoForge knowledge phases)
