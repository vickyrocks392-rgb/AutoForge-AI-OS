# PolicyDesk Knowledge Assistant — Setup & Installation Guide

This guide describes how to install, configure, and launch the standalone PolicyDesk Knowledge Assistant on macOS or Linux.

---

## 1. Prerequisites

- **Python**: Python 3.10, 3.11, or 3.12.
- **Operating System**: macOS (Apple Silicon or Intel) or Linux (x86_64 or arm64).
- **RAM**: Minimum 4 GB RAM (8 GB+ recommended).
- **Disk Space**: ~500 MB for Python packages and local embedding models.

---

## 2. Clean Environment Setup

From the deliverable directory:

```bash
cd "Customer Deliverables/Phase20-B-PolicyDesk"
```

Create an isolated virtual environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

Install pinned dependencies:

```bash
pip install -r requirements.txt
```

---

## 3. Configuration

Copy the example environment configuration template:

```bash
cp config/.env.example .env
```

Key environment variables:

| Variable | Default Value | Description |
| :--- | :--- | :--- |
| `POLICYDESK_DATA_DIR` | `~/Library/Application Support/AutoForge/CustomerProjects/Phase20-B-PolicyDesk` | Persistent runtime storage path (Must be outside source repositories) |
| `POLICYDESK_PORT` | `8080` | Port for the web interface and REST API |
| `POLICYDESK_LLM_URL` | `http://127.0.0.1:19801/v1` | OpenAI-compatible LLM endpoint (Optional local server) |
| `POLICYDESK_LLM_MODEL` | `mlx-community/Qwen3-Coder-30B-A3B-Instruct-4bit-dwq-v2` | Target generation model identifier |

---

## 4. Launching the Application

Start the application with the included launcher:

```bash
./run.sh
```

Or manually via Python:

```bash
PYTHONPATH=src python3 src/app.py
```

Open your browser to:
[http://127.0.0.1:8080](http://127.0.0.1:8080)

---

## 5. Running Automated Tests

Run the full customer product verification test suite:

```bash
PYTHONPATH=src pytest tests -v
```

---

## 6. Running the Benchmark Evaluation

Execute the deterministic benchmark evaluation dataset against the active knowledge base:

```bash
PYTHONPATH=src python3 evaluation/run_evaluation.py
```
