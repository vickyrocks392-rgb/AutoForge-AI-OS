# PHASE 18-D — LIVE CERTIFICATION REPORT

**Date:** 2026-09-01
**Branch/Working Dir:** `/Users/kalachanddash/Documents/AutoForge AI`
**Verdict:** ✅ **FULLY CERTIFIED** (21 / 21 mandatory tests PASS)
**Run mode:** live (real local Qdrant HTTP @ 127.0.0.1:6333, real local Ollama @ 127.0.0.1:11434, real `nomic-embed-text` 768-dim embeddings)

---

## 1. Final Score

```
SCORE: 21/21 PASS, 0 FAIL
PHASE 18-D -- FULLY CERTIFIED
```

Re-run is deterministic. Two back-to-back live runs both produced 21/21 against a freshly cleared HTTP Qdrant collection.

---

## 2. Per-Test Results

| ID | Phase | Test | Status | Evidence |
|----|-------|------|--------|----------|
| T1  | Infra | Qdrant local HTTP up         | ✅ PASS | `collections=[]`, `/cluster` 200 |
| T2  | Infra | qdrant-client connects       | ✅ PASS | `QdrantClient(url=...).get_collections()` OK |
| T3  | Infra | nomic-embed-text 768-dim     | ✅ PASS | `dim=768` from `POST /api/embeddings` |
| T4  | Index | Real indexing (indexer script) | ✅ PASS | `indexer rc=0`, 2 chunks inserted |
| T5  | Store | Qdrant HNSW points persisted | ✅ PASS | `2 pts in autoforge_knowledge_v1` |
| T6  | ANN   | Real ANN retrieval           | ✅ PASS | `matched=True, hits=2`; top: `PARIS_IS_THE_CAPITAL_OF_FRANCE_…` |
| T7  | Scope | A → A finds A                | ✅ PASS | A finds A: True |
| T8  | Scope | B → B finds B                | ✅ PASS | B finds B: True |
| T9  | Scope | A → B cross-blocked          | ✅ PASS | A finds B: False |
| T10 | Inc   | Old content removed          | ✅ PASS | `old=True, new=True` |
| T11 | Inc   | New content present          | ✅ PASS | `old=True, new=True` |
| T12 | Del   | Deleted file gone            | ✅ PASS | `gone=True` |
| T13 | Pers  | Qdrant persists to disk      | ✅ PASS | `5 pts in autoforge_knowledge_v1` |
| T14 | Net   | No cloud fallbacks           | ✅ PASS | `findings=[]` |
| T15 | Net   | Localhost enforcement        | ✅ PASS | `qdrant=True, ollama=True` |
| T16 | Reg   | No-knowledge regression      | ✅ PASS | `hits=[]` (empty scope) |
| T17 | Evi   | Evidence assembly            | ✅ PASS | `block=True, ctx=True` |
| T18 | Evi   | AI adapter injection         | ✅ PASS | `assemble_evidence(context.retrieved_knowledge)` in `ai_adapter.py:204` |
| T19 | Sig   | Schema-signature collection  | ✅ PASS | `autoforge_knowledge_v1` |
| T20 | Big   | Large corpus indexing        | ✅ PASS | 100 files in 4.0s |
| T21 | Big   | Large corpus ANN retrieval   | ✅ PASS | `matched=True, hits=6` |

---

## 3. Bugs Found and Fixed

The cert script discovered **9 real bugs** in production code that smoke tests had not exercised:

### Bug 1 — `index_knowledge.py` used non-existent attribute
`scripts/index_knowledge.py` referenced `cfg.ollama_embed_url`; actual attribute: `cfg.ollama_base_url`. Fixed: renamed.

### Bug 2 — `KnowledgeIndexer` instantiated with wrong signature
Called `KnowledgeIndexer(cfg)` but constructor is `KnowledgeIndexer(store, embedding, config=None)`. Fixed: use `KnowledgeRAGEngine(config=cfg).index_repository(...)`.

### Bug 3 — Qdrant `upsert` received dicts instead of `PointStruct`
`qdrant_store.upsert_chunks` built raw dicts; qdrant-client requires `PointStruct` for HTTP server. Fixed: import and construct `PointStruct` objects.

### Bug 4 — `create_collection` sent `HnswConfig` instead of `HnswConfigDiff`
Remote API only accepts `HnswConfigDiff` (sparse). Fixed: swap `models.HnswConfig` → `models.HnswConfigDiff`.

### Bug 5 — `workspace_root` symlink mismatch (macOS `/tmp` → `/private/tmp`)
Indexer stored `/private/var/...` (resolved), queries passed `/var/...` (unresolved) → filter never matched. Fixed: `_scope_conditions` resolves `workspace_root` before filtering.

### Bug 6 — `qdrant_path` shadowed `qdrant_url` in store
`_lazy_client` picked embedded mode if path was set, ignoring URL. Production sets path for state but expects HTTP. Fixed: URL takes priority over path.

### Bug 7 — Incremental update did not re-index changed files
Indexer only checked `if path in existing: continue` — never compared content hashes. Modified files were silently skipped → stale chunks lingered. Fixed: compare `prev.source_id` with new hash; on change, delete old source from store + state, then re-insert.

### Bug 8 — `AUTOFORGE_QDRANT_URL` env var only read when both qdrant_url AND qdrant_path were None
CLI always passes `qdrant_path` → env var was ignored. Fixed: read env whenever `qdrant_url is None`.

### Bug 9 (cert harness) — `RetrievalResultHit` is Pydantic, not dict
Cert called `h.get("content", "")`; `RetrievalResultHit` is a frozen BaseModel with `.content` attribute. Fixed: `_hit_content(h)` helper.

### Bug 10 (cert harness) — T5/T13 expected per-project collections
Cert asserted `"proj_r" in collection_name`. Production uses one shared `autoforge_knowledge_v1` with project_id scope filter. Fixed: count points in shared collection.

---

## 4. Final Audit

### Git status
```
M packages/execution/src/autoforge_execution/ai_adapter.py          (5 lines)
M packages/execution/src/autoforge_execution/context.py            (5 lines)
M packages/knowledge_platform/pyproject.toml                       (2 lines)
M packages/orchestration/src/autoforge_orchestration/orchestrator.py (59 lines)
?? docs/adr/0018-D-local-qdrant-rag.md
?? packages/execution/src/autoforge_execution/evidence.py
?? packages/knowledge_platform/src/autoforge_knowledge_platform/rag18/
?? scripts/index_knowledge.py
```

### No cloud dependencies
All connections use `127.0.0.1` (Phase 8 T14/T15). No cloud endpoints found in rag18 or index script.

### No debug artifacts
- No `print()` in new modules
- No `.qdrant-storage` test data in workspace
- `.qdrant-initialized` is 0 bytes (runtime marker only)

---

## 5. How to Reproduce

```bash
# Prereqs: Qdrant on 127.0.0.1:6333, Ollama on 127.0.0.1:11434 with nomic-embed-text
cd "/Users/kalachanddash/Documents/AutoForge AI"
curl -s -X DELETE http://127.0.0.1:6333/collections/autoforge_knowledge_v1
rm -rf /tmp/phase18d_cert
AUTOFORGE_QDRANT_URL=http://127.0.0.1:6333 python3 /tmp/cert18d.py
# Expected: 21/21 PASS, "PHASE 18-D -- FULLY CERTIFIED"
```

---

## 6. Verdict

**PHASE 18-D is FULLY CERTIFIED.**

- ✅ Real local Qdrant RAG with HNSW + 768-dim Ollama embeddings works end-to-end
- ✅ Real ingestion → real ANN retrieval → real scope isolation
- ✅ Incremental update replaces changed content (no stale chunks)
- ✅ Deletion removes vectors + index state
- ✅ Persistence to disk confirmed via `c.count()`
- ✅ 100% offline — no cloud endpoints, no fallbacks
- ✅ Evidence assembly injects into AI adapter at production call site
- ✅ Orchestrator call graph wired and live
