"""
PolicyDesk Knowledge Assistant — FastAPI Application Entry Point.
Provides REST API endpoints and serves the customer web UI.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
import uvicorn

from config import PolicyDeskConfig, resolve_and_validate_paths
from models import (
    DocumentListResponse,
    DocumentUploadResponse,
    HealthResponse,
    QueryRequest,
    QueryResponse,
)
from service import PolicyDeskService

logger = logging.getLogger("policydesk.app")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

# Resolve configuration and validate external data isolation
config = resolve_and_validate_paths()
service = PolicyDeskService(config)

app = FastAPI(
    title=config.project_name,
    description="Customer RAG Knowledge Assistant for PolicyDesk consulting staff.",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

BASE_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = BASE_DIR / "static"
EVAL_DATASET_FILE = BASE_DIR / "evaluation" / "test_dataset.json"


# ── REST API Endpoints ────────────────────────────────────────────────────────

@app.post("/api/query", response_model=QueryResponse)
def query_knowledge(req: QueryRequest):
    """Ask a question in plain English against the ingested knowledge base."""
    try:
        return service.query(req)
    except Exception as e:
        logger.error(f"Error handling query: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Query execution failed: {str(e)}")


@app.get("/api/documents", response_model=DocumentListResponse)
def list_documents():
    """Retrieve all indexed documents and their ingestion metadata."""
    return service.list_documents()


@app.post("/api/documents/upload", response_model=DocumentUploadResponse)
async def upload_document(file: UploadFile = File(...)):
    """Upload and index a new PDF, Markdown, or plain-text file."""
    if not file.filename:
        raise HTTPException(status_code=400, detail="Filename missing.")

    ext = file.filename.split(".")[-1].lower()
    if ext not in ("pdf", "md", "txt", "markdown", "text"):
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file format: '.{ext}'. Supported formats are: .pdf, .md, .txt",
        )

    tmp_path = config.tmp_dir / file.filename
    try:
        with open(tmp_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        res = service.upload_document(tmp_path)
        return res
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        logger.error(f"Failed to process uploaded file '{file.filename}': {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Ingestion failed: {str(e)}")
    finally:
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except Exception:
                pass


@app.delete("/api/documents/{doc_id}")
def delete_document(doc_id: str):
    """Remove a document and purge all its retrievable chunks from the persistent index."""
    success = service.delete_document(doc_id)
    if not success:
        raise HTTPException(status_code=404, detail=f"Document '{doc_id}' not found in registry.")
    return {"status": "deleted", "doc_id": doc_id, "message": f"Successfully deleted '{doc_id}' and all associated vector chunks."}


@app.get("/api/health", response_model=HealthResponse)
def get_health():
    """System health check and diagnostic configuration."""
    return service.get_health()


@app.post("/api/reset")
def reset_knowledge_base():
    """Reset the knowledge base (wipes all documents and index while retaining configuration)."""
    service.reset_knowledge_base()
    return {"status": "reset", "message": "Knowledge base and vector index successfully reset."}


@app.get("/api/evaluation/dataset")
def get_evaluation_dataset():
    """Get the fixed held-out evaluation dataset."""
    if not EVAL_DATASET_FILE.exists():
        raise HTTPException(status_code=404, detail="Evaluation dataset not found.")
    data = json.loads(EVAL_DATASET_FILE.read_text(encoding="utf-8"))
    return data


@app.post("/api/evaluation/run")
def run_evaluation_suite():
    """Execute the full benchmark evaluation suite and return measured metrics."""
    if not EVAL_DATASET_FILE.exists():
        raise HTTPException(status_code=404, detail="Evaluation dataset not found.")
    
    data = json.loads(EVAL_DATASET_FILE.read_text(encoding="utf-8"))
    test_cases = data.get("test_cases", [])

    results = []
    correct_count = 0
    grounded_count = 0
    abstention_correct_count = 0
    total_abstention_cases = 0
    citation_correct_count = 0

    for case in test_cases:
        cid = case["id"]
        q = case["query"]
        expected_docs = case.get("expected_docs", [])
        expected_abstain = case.get("expected_abstain", False)

        resp = service.query(QueryRequest(query=q, top_k=5))
        
        # Check abstention
        abstain_match = (resp.abstained == expected_abstain)
        if expected_abstain:
            total_abstention_cases += 1
            if abstain_match:
                abstention_correct_count += 1

        # Check citations
        cited_docs = [c.filename for c in resp.citations]
        citation_match = True
        if expected_docs:
            overlap = any(any(ed.lower() in cd.lower() for cd in cited_docs) for ed in expected_docs)
            citation_match = overlap
        if citation_match:
            citation_correct_count += 1

        if resp.is_grounded:
            grounded_count += 1

        case_passed = abstain_match and (citation_match or expected_abstain)
        if case_passed:
            correct_count += 1

        results.append({
            "id": cid,
            "category": case.get("category", "general"),
            "query": q,
            "answer": resp.answer,
            "citations": [c.model_dump() for c in resp.citations],
            "abstained": resp.abstained,
            "expected_abstain": expected_abstain,
            "is_grounded": resp.is_grounded,
            "latency_ms": resp.latency_ms,
            "passed": case_passed,
        })

    total = len(test_cases)
    metrics = {
        "total_cases": total,
        "passed_cases": correct_count,
        "accuracy": round(correct_count / total, 4) if total else 0.0,
        "grounding_rate": round(grounded_count / total, 4) if total else 0.0,
        "citation_accuracy": round(citation_correct_count / total, 4) if total else 0.0,
        "abstention_accuracy": round(abstention_correct_count / total_abstention_cases, 4) if total_abstention_cases else 1.0,
    }

    return {
        "status": "completed",
        "metrics": metrics,
        "case_results": results,
    }


# ── Web UI Serving ────────────────────────────────────────────────────────────

if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    @app.get("/")
    def serve_index():
        return FileResponse(STATIC_DIR / "index.html")


if __name__ == "__main__":
    uvicorn.run(app, host=config.host, port=config.port)
