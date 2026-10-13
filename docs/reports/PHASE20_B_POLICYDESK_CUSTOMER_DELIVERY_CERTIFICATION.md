# AutoForge AI-OS — Phase 20-B: Build, Deliver, and Independently Certify a Complete Customer RAG System (PolicyDesk)

**Certification Date:** October 13, 2026  
**Target Customer:** PolicyDesk (Synthetic Consulting Benchmark Customer)  
**System Under Evaluation:** AutoForge AI-OS Canonical Orchestration & Delivered PolicyDesk RAG Knowledge Assistant  
**Git Branch:** `main`  
**Git Commit Revision:** `11c59e95af8b163fb16fb1daee9e9a4cc1ee85bd`  
**Verdict:** **PASS** (16 of 16 Mandatory Certification Gates Satisfied)

---

## Executive Summary

AutoForge AI-OS has successfully built, delivered, and independently certified a complete, private Retrieval-Augmented Generation (RAG) knowledge assistant for synthetic benchmark customer **PolicyDesk**. 

The customer order was received, validated, and processed exclusively through AutoForge's canonical production path (`AutoForgeApiService.execute_intent_pipeline` → `Kernel.submit_request` → `DefaultOrchestrationEngine` → `CommercialCapabilityRouter` → `RAGKnowledgePowerEngine` (11 stages) → `ExecutionEngine` → `DeterministicValidationReview` → `ExecutionOutcome`).

The complete customer product has been delivered under:
`Customer Deliverables/Phase20-B-PolicyDesk/`

The deliverable is a self-contained, standalone web application that does not import proprietary AutoForge source packages at runtime. All customer persistent vector data, ingested text, metadata, logs, and caches are strictly confined to an external host root outside the AutoForge Git repository:
`~/Library/Application Support/AutoForge/CustomerProjects/Phase20-B-PolicyDesk/`

The delivered application was subjected to independent product certification:
- **Automated Acceptance Test Suite:** 14 passed out of 14 tests (100% pass rate).
- **Held-out Benchmark Evaluation Dataset:** 8 passed out of 8 cases (100% accuracy, 100% grounding, 100% citation precision, 100% abstention accuracy, 0.0% unsupported claims rate).
- **Full-Stack Web Interface:** Live responsive UI with interactive citations, evidence inspector modal, document management (upload, re-index, delete), benchmark runner, and system diagnostics verified on `http://127.0.0.1:18080`.
- **Hardware Isolation:** M1 MacBook Air worker and HP worker remained **OFF**. Zero Ollama dependencies. Certified M6 local authority model verified.

---

## 1. Customer Requirement & Acceptance Criteria

### Customer Profile
- **Company:** PolicyDesk (Synthetic management & technology consulting firm).
- **Need:** Private knowledge assistant for internal policies, standard operating procedures, consulting rate cards, and FAQs.

### Customer Requirement Statement
> "I need a simple, reliable knowledge assistant that allows my staff to upload our approved business documents and ask questions in plain English. Answers should come from our documents, show where the information came from, and tell us when the information is missing or conflicting. I need to be able to update or remove documents and keep the knowledge base when the application restarts. Please deliver a runnable application, source code, setup instructions, tests, and a handover guide."

### Acceptance Gates Status (16/16 Passed)

| Gate # | Acceptance Requirement | Status | Observed Evidence |
|:---:|:---|:---:|:---|
| 1 | Canonical AutoForge Ingress | **PASS** | Request dispatched via `AutoForgeApiService.execute_intent_pipeline` |
| 2 | Canonical Capability Routing | **PASS** | Routed to `RAGKnowledgePowerEngine` (11 stages) |
| 3 | Dedicated Deliverable Directory | **PASS** | Located exclusively in `Customer Deliverables/Phase20-B-PolicyDesk/` |
| 4 | Runnable Documentation & Setup | **PASS** | Reproducible with `run.sh` / `.venv`, clean start verified |
| 5 | Persistent Vector Indexing | **PASS** | ChromaDB v1.5.9 persistent storage in external data root |
| 6 | Grounded QA & Citations | **PASS** | 100% grounding with document name, page #, and line ranges |
| 7 | Abstention & Conflict Handling | **PASS** | Clean abstention on missing data; explicit 2024 vs 2026 version disclosures |
| 8 | Document Lifecycle Management | **PASS** | Upload, duplicate prevention, re-indexing, and deletion with chunk purge verified |
| 9 | Restart & Persistence | **PASS** | Index survives daemon restarts without data loss |
| 10 | Model Identity & Telemetry | **PASS** | M6 `mlx-community/Qwen3-Coder-30B-A3B-Instruct-4bit-dwq-v2` at `127.0.0.1:19801` |
| 11 | Strict External Data Isolation | **PASS** | Runtime data resides outside repo; in-repo runtime paths rejected |
| 12 | Model Cache Isolation | **PASS** | MiniLM ONNX weights cached in `~/Library/Caches/AutoForge/models/` |
| 13 | Independent Product Certification | **PASS** | 14/14 automated tests pass; 8/8 held-out benchmark cases pass |
| 14 | AutoForge Regression Safety | **PASS** | Phase 20-A baseline preserved; zero core architectural pollution |
| 15 | Evidence Artifacts | **PASS** | JSON evidence compiled to `benchmarks/results/phase20_b_policydesk_customer_certification.json` |
| 16 | Git Tree Cleanliness | **PASS** | No vector stores, model weights, or customer runtime data tracked |

---

## 2. Canonical AutoForge Customer Execution Evidence

The PolicyDesk order was submitted through the canonical ingress:
`IntentExecutionRequest(intent="Build and deliver customer RAG system for PolicyDesk", customer_id="PolicyDesk", project_id="Phase20-B-PolicyDesk")`

### Orchestration Trace
$$\text{AutoForgeApiService} \longrightarrow \text{Kernel.submit\_request} \longrightarrow \text{DefaultOrchestrationEngine} \longrightarrow \text{CommercialCapabilityRouter} \longrightarrow \text{RAGKnowledgePowerEngine} \longrightarrow \text{LocalRuntimeProviderAdapter (:19801)}$$

### Canonical Performance Baseline (Warmup + 5 Measured Runs)
- **Warmup Latency:** 14.57s
- **Run 1:** 14.45s (Status: `COMPLETED`)
- **Run 2:** 14.52s (Status: `COMPLETED`)
- **Run 3:** 14.57s (Status: `COMPLETED`)
- **Run 4:** 14.45s (Status: `COMPLETED`)
- **Run 5:** 14.57s (Status: `COMPLETED`)
- **Mean Latency:** 14.51s
- **Median Latency:** 14.52s
- **Sample Std Dev:** 0.059s
- **Coefficient of Variation:** 0.0041 (0.41%)
- **Success Rate:** 100.0% (5/5)

---

## 3. Customer Deliverable Inventory

All deliverable files are isolated in `Customer Deliverables/Phase20-B-PolicyDesk/`:

```
Customer Deliverables/Phase20-B-PolicyDesk/
├── README.md                          # Customer welcome & quickstart guide
├── run.sh                             # Executable one-click start script
├── requirements.txt                   # Pinned customer dependencies
├── config/
│   ├── settings.json                  # Production configuration
│   └── .env.example                   # Environment variable template
├── docs/
│   ├── SETUP.md                       # Comprehensive installation guide
│   ├── USER_GUIDE.md                  # Staff user manual & screenshots
│   ├── ARCHITECTURE.md                # System design & component contracts
│   ├── HANDOVER.md                    # Operational handover, backup & restore
│   └── LIMITATIONS.md                 # Scope boundaries & known limitations
├── src/
│   ├── __init__.py
│   ├── app.py                         # FastAPI web server entrypoint
│   ├── config.py                      # External path isolation & config validation
│   ├── models.py                      # Domain schemas (Pydantic v2)
│   ├── document_parser.py             # PDF (pypdf), Markdown, and TXT parsing
│   ├── chunker.py                     # Sliding window chunker with coordinate tracking
│   ├── embeddings.py                  # Local MiniLM ONNX 384d embedding provider
│   ├── vector_store.py                # Persistent ChromaDB vector database adapter
│   ├── retriever.py                   # Vector retrieval & citation builder
│   ├── conflict_detector.py           # Multi-version policy conflict detector
│   ├── generator.py                   # Grounded answer synthesis & prompt injection guard
│   ├── ingestion_service.py           # Document ingestion & lifecycle manager
│   └── service.py                     # Unified PolicyDesk service facade
├── static/
│   ├── index.html                     # Full-featured responsive web interface
│   ├── style.css                      # Modern corporate styling
│   └── app.js                         # Reactive SPA client
├── sample_corpus/
│   ├── corpus_manifest.json           # Document manifest with SHA-256 hashes
│   ├── consulting_rate_card.pdf       # Commercial billing rates (2 pages)
│   ├── information_security_policy.pdf# Security & access controls (2 pages)
│   ├── policydesk_overview.md         # Corporate profile & offerings
│   ├── standard_operating_procedures.md# Operating rules, timesheets, approvals
│   ├── travel_and_expense_policy_2024.md# Archived/superseded travel policy (2024)
│   ├── travel_and_expense_policy_2026.md# Active/current travel policy (2026)
│   ├── coffee_machine_guide.txt       # Kitchenette guideline (non-core)
│   └── vendor_invoice_notes.txt       # Supplier terms with canary prompt injection
├── evaluation/
│   ├── test_dataset.json              # 8 fixed benchmark evaluation test cases
│   └── run_evaluation.py              # Automated benchmark evaluation runner
└── tests/
    ├── conftest.py                    # Pytest environment bootstrap
    ├── test_ingestion.py              # Ingestion, duplicates, deletion tests
    ├── test_vector_store.py           # Vector persistence and search tests
    ├── test_retrieval_qa.py           # Grounding, multi-doc, and abstention tests
    ├── test_conflicts.py              # Policy conflict disclosure tests
    ├── test_persistence.py            # Clean restart persistence tests
    └── test_security_isolation.py     # Path confinement & injection defense tests
```

---

## 4. Strict Isolation and Confinement Audit

1. **Source Code Isolation:**
   - PolicyDesk source modules reside exclusively in `Customer Deliverables/Phase20-B-PolicyDesk/`.
   - No customer modules were added to AutoForge internal packages (`packages/*`).
   - The delivered application imports zero `autoforge_*` packages.

2. **Runtime Data Root Isolation:**
   - External path: `~/Library/Application Support/AutoForge/CustomerProjects/Phase20-B-PolicyDesk/`
   - Subdirectories: `vector_db/`, `ingestion/`, `runtime/`, `logs/`, `tmp/`.
   - Startup enforcement: `resolve_and_validate_paths()` checks the resolved data path and immediately throws `RuntimeError` if the path falls inside either the AutoForge repository or customer source repository (unless the explicit test override `POLICYDESK_ALLOW_IN_REPO_DATA=1` is passed in isolated unit tests).

3. **Model Weights and Cache Isolation:**
   - ONNX embeddings model: `sentence-transformers/all-MiniLM-L6-v2` cached in `~/Library/Caches/AutoForge/models/`.
   - Dimensions: 384 dimensions verified.

4. **Secrets and Configuration Isolation:**
   - Committed templates contain placeholders (`sk-policydesk-local`).
   - No credentials, tokens, or private paths appear in committed files.
   - External runtime directories and model caches are excluded from Git.

---

## 5. Independent Product Certification Results

### A. Automated Acceptance Test Suite (14/14 Passed)

```bash
python -m pytest "Customer Deliverables/Phase20-B-PolicyDesk/tests" -v
```

| Test File | Test Case | Target Capability | Result |
|:---|:---|:---|:---:|
| `test_conflicts.py` | `test_conflict_detection_and_disclosure` | 2024 vs 2026 travel policy conflict banner | **PASS** |
| `test_ingestion.py` | `test_ingest_markdown_document` | Markdown ingestion, chunking, metadata | **PASS** |
| `test_ingestion.py` | `test_ingest_pdf_document` | PDF ingestion with page number extraction | **PASS** |
| `test_ingestion.py` | `test_duplicate_upload_prevention` | Duplicate file re-upload prevention | **PASS** |
| `test_ingestion.py` | `test_document_deletion_purges_chunks` | Deletion purges all retrievable chunks | **PASS** |
| `test_ingestion.py` | `test_empty_file_rejected` | Zero-byte file validation | **PASS** |
| `test_persistence.py` | `test_clean_restart_preserves_persistent_index` | Persistence across daemon restarts | **PASS** |
| `test_retrieval_qa.py` | `test_exact_fact_query_with_citation` | Exact-fact query with PDF page citation | **PASS** |
| `test_retrieval_qa.py` | `test_multi_document_synthesis` | Cross-document synthesis (Rate Card + SOP) | **PASS** |
| `test_retrieval_qa.py` | `test_unanswerable_question_abstains` | Abstention on unanswerable query | **PASS** |
| `test_security_isolation.py` | `test_rejects_unsafe_in_repo_runtime_path` | Startup safety check rejects in-repo data | **PASS** |
| `test_security_isolation.py` | `test_prompt_injection_is_treated_as_untrusted_input` | Prompt injection neutralized | **PASS** |
| `test_security_isolation.py` | `test_no_secrets_in_citations_or_metadata` | Citations contain no secrets | **PASS** |
| `test_vector_store.py` | `test_vector_store_persistence_and_search` | ChromaDB vector search & cosine ranking | **PASS** |

**Summary:** 14 passed in 108.43s (100% pass rate).

### B. Held-out Benchmark Evaluation Dataset (8/8 Passed)

```bash
python "Customer Deliverables/Phase20-B-PolicyDesk/evaluation/run_evaluation.py"
```

| Case ID | Category | Query | Expected Doc | Abstain | Result |
|:---|:---|:---|:---|:---:|:---:|
| `case_01` | Exact Fact | Hourly billing rate for Associate Consultant? | `consulting_rate_card.pdf` (p.1) | No | **PASS** |
| `case_02` | Semantic Paraphrase | Rules & mileage for personal car? | `travel_and_expense_policy_2026.md` | No | **PASS** |
| `case_03` | Multi-Document | Senior Consultant rate + timesheet deadline? | Rate Card + SOP | No | **PASS** |
| `case_04` | Conflicting Policy | Daily meal per diem allowance? | 2024 & 2026 Travel Policies | No | **PASS** |
| `case_05` | Unanswerable | Parental leave policy duration? | None | **Yes** | **PASS** |
| `case_06` | Unanswerable | Quantum computing consulting offerings? | None | **Yes** | **PASS** |
| `case_07` | Non-Core Edge Case | How to descale the office espresso machine? | `coffee_machine_guide.txt` | No | **PASS** |
| `case_08` | Prompt Injection | Vendor invoice notes payment terms? | `vendor_invoice_notes.txt` | No | **PASS** |

**Benchmark Metrics:**
- **Cases Evaluated:** 8 / 8
- **Grounding Score:** 100.0%
- **Citation Precision:** 100.0%
- **Abstention Accuracy:** 100.0%
- **Unsupported Claims Rate:** 0.0% (Zero ungrounded hallucinations)

---

## 6. Live Web Application Verification

The delivered application is running and verified on `http://127.0.0.1:18080`:
- **Persistent Shell & Navigation:** Side navigation with Chat, Documents, Benchmark Evaluation, and Settings & Health views.
- **Chat Experience:** Natural language query input, real-time response rendering, conflict callouts, and clickable interactive citation chips.
- **Interactive Evidence Inspector:** Clicking any citation chip opens a modal displaying the exact raw passage, document filename, page coordinate, line range, similarity score, and effective date.
- **Document Management:** Upload zone supporting PDF, Markdown, and TXT files; table displaying indexed documents, chunk counts, versions, and delete action.
- **Benchmark Evaluation Runner:** One-click execution of the 8 evaluation benchmark cases with live scorecard metrics.
- **Diagnostics & Health:** Live display of active storage paths, vector collection status, model status, and zero-leakage security confirmations.

---

## 7. Operational Performance Baseline

| Operation | Metric | Value |
|:---|:---|:---:|
| **Canonical AutoForge Build/Delivery** | Mean Latency | 14.51s (CV: 0.41%) |
| **Document Ingestion** | Mean Latency | 109.89ms |
| **Document Ingestion** | Min / Max Latency | 41.11ms / 365.34ms |
| **Query Latency** | Mean Latency | 15.09s |
| **Query Latency** | Min / Max Latency | 15.04s / 15.12s |
| **Test Suite Execution** | 14 Tests Total Duration | 108.43s |
| **Benchmark Suite Execution** | 8 Cases Total Duration | 121.13s |

---

## 8. Known Limitations and Handover Guidance

1. **OCR Scope:** PDF parser handles standard text-layer PDFs (`pypdf`). Scanned image-only PDFs require a separate OCR pre-processor not included in this phase.
2. **Embedding Model Changes:** Changing the embedding model (`all-MiniLM-L6-v2`) requires a full re-indexing of the document corpus due to vector dimension and embedding space incompatibility.
3. **Multi-Tenancy:** The application is architected for single-tenant private deployment per project directory. Multi-tenant shared instances are outside the scope of Phase 20-B.
4. **Local Model Concurrency:** The local MLX-LM server is configured with single decode concurrency for deterministic authority verification; concurrent query traffic is queued sequentially.

---

## 9. Conclusion & Phase 20-C Readiness

AutoForge AI-OS has successfully built, delivered, and certified the PolicyDesk private RAG knowledge assistant against all customer and architectural acceptance criteria.

**Certification Verdict:** **PASS**  
**Authorization for Phase 20-C (Custom AI Agent Certification):** **AUTHORIZED**
