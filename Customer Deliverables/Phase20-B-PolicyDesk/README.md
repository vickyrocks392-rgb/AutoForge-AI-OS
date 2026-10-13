# PolicyDesk Knowledge Assistant

> **Deliverable Package for Synthetic Benchmark Customer: PolicyDesk**  
> **Phase 20-B Certified Deliverable**

---

## 1. Overview

PolicyDesk Knowledge Assistant is a turnkey, self-contained document question-answering assistant designed for PolicyDesk staff. It allows employees to upload approved company policies, service descriptions, standard operating procedures, and rate cards, and ask natural language questions with 100% verifiable source attribution.

Key Features:
- **Multi-Format Ingestion**: Ingests PDF (with page numbering), Markdown, and plain text files.
- **Persistent Vector Store**: Uses local ChromaDB to persist embeddings and document collections across restarts.
- **Verifiable Citations**: Every claim is cited with source document name, page number, line range, and similarity score.
- **Clickable Evidence Inspector**: Interactive citation badges open a dedicated modal showing the exact supporting passage.
- **Transparent Policy Conflicts**: Identifies when active policies supersede older ones (e.g. 2026 vs 2024 travel policy).
- **Conservative Abstention**: Explicitly admits when requested information is missing from the corpus.
- **Untrusted Input Defense**: Safeguards system prompts against prompt injections embedded in uploaded documents.
- **Strict Data Isolation**: Production databases, caches, and uploaded state reside outside source code repositories.

---

## 2. Quickstart

### Installation & Launch
```bash
cd "Customer Deliverables/Phase20-B-PolicyDesk"
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
./run.sh
```

Navigate to [http://127.0.0.1:8080](http://127.0.0.1:8080) in your browser.

### Run Automated Tests
```bash
PYTHONPATH=src pytest tests -v
```

### Run Benchmark Evaluation
```bash
PYTHONPATH=src python3 evaluation/run_evaluation.py
```

---

## 3. Documentation

- [Setup Guide](docs/SETUP.md)
- [Staff User Guide](docs/USER_GUIDE.md)
- [Architecture Specification](docs/ARCHITECTURE.md)
- [Customer Handover Notes](docs/HANDOVER.md)
- [Operational Limitations](docs/LIMITATIONS.md)
