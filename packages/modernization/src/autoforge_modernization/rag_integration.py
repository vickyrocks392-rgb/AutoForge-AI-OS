"""RAG integration for modernization (Phase 18-G.3).

Wires modernization engine into knowledge platform `rag18` retrieval
(`KnowledgeRetrievalService.retrieve`). Records calls/latency/hits
for forensics. Falls back to a local stub if RAG unavailable.
"""
from __future__ import annotations
import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class RAGCallRecord:
    query: str
    scope: str
    hits: int
    latency_ms: int
    error: str | None = None
    result_summary: str = ""


class RAGClient:
    def __init__(self, retrieval_service=None, available: bool = True):
        self.service = retrieval_service
        self.available = available
        self.calls = []
        self.metrics = {"calls": 0, "hits": 0, "misses": 0, "errors": 0, "total_latency_ms": 0}

    def retrieve(self, query: str, scope: str = "modernization", top_k: int = 5) -> dict:
        start = time.time()
        record = RAGCallRecord(query=query[:200], scope=scope, hits=0, latency_ms=0)
        if not self.available or self.service is None:
            record.error = "RAG unavailable (graceful degradation)"
            record.latency_ms = int((time.time() - start) * 1000)
            self.calls.append(record)
            self.metrics["calls"] += 1
            self.metrics["misses"] += 1
            self.metrics["errors"] += 1
            self.metrics["total_latency_ms"] += record.latency_ms
            return {"hits": [], "available": False, "error": record.error}
        try:
            from autoforge_knowledge_platform.rag18.models import (
                RetrievalRequest, RetrievalScope,
            )
            scope_obj = RetrievalScope(name=scope) if hasattr(RetrievalScope, "name") else None
            req = RetrievalRequest(query=query, scope=scope_obj or scope, top_k=top_k)
            res = self.service.retrieve(req)
            hits = getattr(res, "hits", []) or []
            record.hits = len(hits)
            record.latency_ms = int((time.time() - start) * 1000)
            record.result_summary = "; ".join(h.summary() for h in hits[:3]) if hits else ""
            self.calls.append(record)
            self.metrics["calls"] += 1
            self.metrics["hits"] += len(hits)
            self.metrics["total_latency_ms"] += record.latency_ms
            return {"hits": [h.dict() if hasattr(h, "dict") else str(h) for h in hits], "available": True}
        except Exception as e:
            record.error = f"RAG retrieve failed: {e}"
            record.latency_ms = int((time.time() - start) * 1000)
            self.calls.append(record)
            self.metrics["calls"] += 1
            self.metrics["errors"] += 1
            self.metrics["total_latency_ms"] += record.latency_ms
            return {"hits": [], "available": False, "error": record.error}

    def get_metrics(self):
        return {**self.metrics, "hit_rate": self.metrics["hits"] / max(1, self.metrics["calls"])}


__all__ = ["RAGClient", "RAGCallRecord"]
