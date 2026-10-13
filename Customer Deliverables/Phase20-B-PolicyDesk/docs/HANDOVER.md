# PolicyDesk Knowledge Assistant — Customer Handover Guide

---

## 1. Executive Summary

This deliverable contains the complete, standalone, customer-ready **PolicyDesk Knowledge Assistant** requested by PolicyDesk.

The application satisfies all customer acceptance criteria:
- Document ingestion for PDF, Markdown, and TXT files.
- Persistent ChromaDB vector indexing across restarts.
- Plain-English natural language queries.
- Verifiable citations with page/line coordinates and clickable evidence inspector.
- Transparent policy version conflict disclosure.
- Explicit abstention on unanswerable questions.
- Document lifecycle management (upload, update, delete).
- Zero proprietary AutoForge internal imports.

---

## 2. Directory Layout of Deliverable

```
Phase20-B-PolicyDesk/
├── src/                # Core application source code
├── static/             # Responsive web UI (HTML, CSS, JS)
├── sample_corpus/      # Approved sample business documents (PDF, MD, TXT)
├── evaluation/         # Benchmark evaluation dataset and runner
├── tests/              # Automated unit, integration, and security tests
├── docs/               # Technical and user documentation
├── config/             # Configuration templates and settings
├── requirements.txt    # Pinned dependency manifest
├── run.sh              # One-click startup script
└── README.md           # Welcome overview
```

---

## 3. Operations & Maintenance

### Starting the Application
```bash
./run.sh
```

### Backing Up the Knowledge Base
To back up PolicyDesk's vector index and ingestion registry:
```bash
tar -czvf policydesk_backup.tar.gz "$HOME/Library/Application Support/AutoForge/CustomerProjects/Phase20-B-PolicyDesk"
```

### Restoring from Backup
```bash
tar -xzvf policydesk_backup.tar.gz -C "$HOME/Library/Application Support/AutoForge/CustomerProjects/Phase20-B-PolicyDesk"
```

### Safe Resetting
To wipe the knowledge base without deleting configuration:
```bash
curl -X POST http://127.0.0.1:8080/api/reset
```
Or click **Reset Knowledge Base** in the **System & Health** view of the web UI.

---

## 4. Acceptance Verification Summary

| Requirement | Result | Evidence |
| :--- | :--- | :--- |
| PDF, MD, TXT Ingestion | PASS | `tests/test_ingestion.py` |
| Persistent Vector Store | PASS | `tests/test_vector_store.py`, `tests/test_persistence.py` |
| Verifiable Citations | PASS | `tests/test_retrieval_qa.py` |
| Policy Conflict Disclosure | PASS | `tests/test_conflicts.py` |
| Explicit Abstention | PASS | `tests/test_retrieval_qa.py` |
| Security & Confinement | PASS | `tests/test_security_isolation.py` |
| Benchmark Dataset | PASS (100%) | `evaluation/run_evaluation.py` |
