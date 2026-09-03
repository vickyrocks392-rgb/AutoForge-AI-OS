"""Metrics forensics for modernization (Phase 18-G.3).

Real metrics: wall-clock, per-stage throughput, LLM/RAG/tool counts,
semantic coverage, generated vs semantic LOC. NOT synthetic placeholders.
"""
from __future__ import annotations
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


def _utc_now(): return datetime.now(timezone.utc)


@dataclass
class StageTimer:
    name: str
    started_at: float = 0.0
    ended_at: float = 0.0
    count: int = 0
    bytes_in: int = 0
    bytes_out: int = 0
    notes: dict = field(default_factory=dict)

    def start(self): self.started_at = time.time()
    def stop(self): self.ended_at = time.time()
    def elapsed_ms(self): return int((self.ended_at - self.started_at) * 1000) if self.ended_at else 0
    def throughput(self): return self.count / max(0.001, (self.ended_at - self.started_at)) if self.ended_at else 0


class MetricsForensics:
    def __init__(self):
        self.start_wall = time.time()
        self.stages = {}
        self.counters = {
            "llm_calls": 0, "rag_calls": 0, "tool_calls": 0,
            "files_total": 0, "files_ok": 0, "files_review": 0, "files_blocked": 0,
            "cobol_loc": 0, "jcl_loc": 0, "sql_loc": 0, "generated_loc": 0, "semantic_loc": 0,
            "rag_hits": 0, "rag_misses": 0, "llm_tokens_in": 0, "llm_tokens_out": 0,
        }

    def stage(self, name: str) -> StageTimer:
        if name not in self.stages:
            self.stages[name] = StageTimer(name=name)
        return self.stages[name]

    def incr(self, key: str, n: int = 1):
        if key in self.counters:
            self.counters[key] += n

    def set_semantic_loc(self, n: int):
        """Semantic LOC = LOC of meaningful business logic (not boilerplate)."""
        self.counters["semantic_loc"] = n

    def set_generated_loc(self, n: int):
        self.counters["generated_loc"] = n

    def summary(self) -> dict:
        wall_ms = int((time.time() - self.start_wall) * 1000)
        stages = {name: {"elapsed_ms": s.elapsed_ms(), "count": s.count, "throughput": round(s.throughput(), 3)} for name, s in self.stages.items()}
        return {
            "wall_clock_ms": wall_ms,
            "stages": stages,
            "counters": dict(self.counters),
            "loc_ratio": round(self.counters["generated_loc"] / max(1, self.counters["semantic_loc"]), 3),
            "files_blocked_rate": round(self.counters["files_blocked"] / max(1, self.counters["files_total"]), 3),
            "files_review_rate": round(self.counters["files_review"] / max(1, self.counters["files_total"]), 3),
        }


__all__ = ["MetricsForensics", "StageTimer"]
