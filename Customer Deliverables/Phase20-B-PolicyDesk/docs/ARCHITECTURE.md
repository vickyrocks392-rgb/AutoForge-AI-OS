# PolicyDesk Knowledge Assistant — Architecture Specification

This document details the system design, components, and data isolation boundaries for PolicyDesk.

---

## 1. Architectural Overview

```
[ User Web Browser ] <--> [ FastAPI REST API / Static Host (app.py) ]
                                      |
                     [ Core Service Orchestrator (service.py) ]
                                      |
         +----------------------------+----------------------------+
         |                            |                            |
[ Document Parser ]         [ Persistent Vector Store ]   [ Answer Generator ]
 (pypdf, Markdown, txt)      (ChromaDB Collection)         (Local OpenAI API / Extractive)
         |                            |                            |
  [ Chunker ]                 [ Local Embeddings ]         [ Conflict Detector ]
 (Bounded windows)           (all-MiniLM-L6-v2, 384-dim)   (Superseded versioning)
```

---

## 2. Component Specifications

### Ingestion Subsystem (`document_parser.py`, `chunker.py`, `ingestion_service.py`)
- **Supported Formats**: PDF (via `pypdf`/`PyPDF2`), Markdown, and plain text.
- **Normalization**: Preserves heading hierarchy and line numbering.
- **Chunk Size**: 500 characters with 60-character sliding overlap.
- **Deduplication**: SHA-256 fingerprinting prevents duplicate indexing.
- **Lifecycle**: Re-ingesting updates replaces prior chunks cleanly; deletion purges all chunks by `doc_id`.

### Vector Store Subsystem (`vector_store.py`, `embeddings.py`)
- **Technology**: Persistent ChromaDB instance.
- **Collection**: `policydesk_kb`.
- **Distance Metric**: Cosine similarity (`hnsw:space = "cosine"`).
- **Embeddings**: `sentence-transformers/all-MiniLM-L6-v2` generating 384-dimensional dense vectors.
- **Model Cache**: Cached in external user directory (`~/Library/Caches/AutoForge/models/`).

### Retrieval & Grounding Subsystem (`retriever.py`, `conflict_detector.py`)
- **Relevance Filter**: Cosine similarity threshold ensures low-confidence chunks trigger abstention.
- **Attribution**: Extracts exact line ranges, document IDs, page numbers, and similarity scores.
- **Conflict Handling**: Transparently flags superseded versions (e.g. 2024 vs 2026 policies).

### Generation Subsystem (`generator.py`)
- **Inference Protocol**: OpenAI-compatible chat completions endpoint (`http://127.0.0.1:19801/v1`).
- **Authority Model**: `mlx-community/Qwen3-Coder-30B-A3B-Instruct-4bit-dwq-v2` (M6 node).
- **Prompt Injection Defense**: Encapsulates retrieved content in `<untrusted_retrieved_context>` blocks with explicit system rules barring instruction execution.
- **Air-Gapped / Offline Fallback**: Deterministic extractive grounding synthesizes factually accurate sentences if the LLM runtime is offline.

---

## 3. Strict Confinement & Data Isolation

1. **Source Code**: Stored exclusively within `Customer Deliverables/Phase20-B-PolicyDesk/`.
2. **Runtime Data Root**: Default path is outside the git repository:
   `~/Library/Application Support/AutoForge/CustomerProjects/Phase20-B-PolicyDesk/`
   - `vector_db/`: Persistent ChromaDB index files.
   - `ingestion/`: Document registry and stored copies.
   - `runtime/`: Session state.
   - `logs/`: Application logging.
   - `tmp/`: Temporary processing files.
3. **Safety Guards**: `config.py` validates on startup that the data directory is not inside the source repository, failing closed if an unsafe path is detected.
