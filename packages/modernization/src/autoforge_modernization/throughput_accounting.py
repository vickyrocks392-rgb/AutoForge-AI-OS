"""Semantically-meaningful throughput accounting for AutoForge modernization.

Only artifacts that are PRODUCEd, verified, and carry no placeholder/skip
markers are counted as meaningful throughput.  Failed, skipped, and
unavailable units are tracked separately for diagnostics but excluded from
the throughput numerator.

The ledger is append-only: each completed unit appends exactly one entry.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class UnitKind(str, Enum):
    PRODUCE = "produce"
    SKIP = "skip"
    UNAVAILABLE = "unavailable"
    FAILED = "failed"
    REPAIR = "repair"


class LedgerEntry(BaseModel):
    """One append-only entry recorded per completed transformation unit."""

    entry_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    session_id: str = ""
    unit_id: str = ""
    kind: UnitKind = UnitKind.PRODUCE
    target_technology: str = ""
    source_file_count: int = 0
    output_file_count: int = 0
    placeholder_count: int = 0
    generated_code_bytes: int = 0
    verification_passed: bool = False
    verification_report_id: str = ""
    repair_outcome_id: str = ""
    llm_calls: int = 0
    rag_context_ids: list[str] = Field(default_factory=list)
    latency_ms: float = 0.0
    model: str = ""
    provider: str = ""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    error: str = ""
    timestamp: datetime = Field(default_factory=_utc_now)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ThroughputSummary(BaseModel):
    """High-level accounting summary for one session or full ledger."""

    session_id: str = ""
    total_units: int = 0
    meaningful_throughput: int = 0
    skipped: int = 0
    failed: int = 0
    unavailable: int = 0
    repaired: int = 0
    total_llm_calls: int = 0
    total_latency_ms: float = 0.0
    total_prompt_tokens: int = 0
    total_completion_tokens: int = 0
    per_technology: dict[str, dict[str, int]] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)

class ThroughputAccounting:
    """Append-only ledger with summary computation.

    Tracks every completed unit exactly once.  Meaningful throughput is
    defined as units that are: PRODUCE kind, verification passed, and have
    zero placeholder markers in the generated output.
    """

    def __init__(self, session_id: str = "") -> None:
        self._session_id = session_id or str(uuid.uuid4())
        self._ledger: list[LedgerEntry] = []

    @property
    def session_id(self) -> str:
        return self._session_id

    @property
    def ledger(self) -> list[LedgerEntry]:
        return list(self._ledger)

    def record(
        self,
        *,
        unit_id: str,
        kind: UnitKind,
        target_technology: str = "",
        source_file_count: int = 0,
        output_file_count: int = 0,
        placeholder_count: int = 0,
        generated_code_bytes: int = 0,
        verification_passed: bool = False,
        verification_report_id: str = "",
        repair_outcome_id: str = "",
        llm_calls: int = 0,
        rag_context_ids: list[str] | None = None,
        latency_ms: float = 0.0,
        model: str = "",
        provider: str = "",
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        error: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> LedgerEntry:
        """Append one entry for a completed transformation unit."""
        entry = LedgerEntry(
            session_id=self._session_id,
            unit_id=unit_id,
            kind=kind,
            target_technology=target_technology,
            source_file_count=source_file_count,
            output_file_count=output_file_count,
            placeholder_count=placeholder_count,
            generated_code_bytes=generated_code_bytes,
            verification_passed=verification_passed,
            verification_report_id=verification_report_id,
            repair_outcome_id=repair_outcome_id,
            llm_calls=llm_calls,
            rag_context_ids=list(rag_context_ids or []),
            latency_ms=latency_ms,
            model=model,
            provider=provider,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            error=error,
            metadata=dict(metadata or {}),
        )
        self._ledger.append(entry)
        return entry

    def summary(self) -> ThroughputSummary:
        """Compute summary statistics across the entire ledger."""
        per_tech: dict[str, dict[str, int]] = {}
        for entry in self._ledger:
            pt = entry.target_technology
            if pt not in per_tech:
                per_tech[pt] = {"produce": 0, "skip": 0, "fail": 0, "mean": 0}
            bucket = {
                UnitKind.PRODUCE: "produce",
                UnitKind.REPAIR: "produce",
                UnitKind.SKIP: "skip",
                UnitKind.FAILED: "fail",
                UnitKind.UNAVAILABLE: "fail",
            }.get(entry.kind, "fail")
            per_tech[pt][bucket] += 1

        meaningful = sum(
            1
            for e in self._ledger
            if e.kind in (UnitKind.PRODUCE, UnitKind.REPAIR)
            and e.verification_passed
            and e.placeholder_count == 0
        )
        return ThroughputSummary(
            session_id=self._session_id,
            total_units=len(self._ledger),
            meaningful_throughput=meaningful,
            skipped=sum(1 for e in self._ledger if e.kind == UnitKind.SKIP),
            failed=sum(1 for e in self._ledger if e.kind == UnitKind.FAILED),
            unavailable=sum(
                1 for e in self._ledger if e.kind == UnitKind.UNAVAILABLE
            ),
            repaired=sum(1 for e in self._ledger if e.kind == UnitKind.REPAIR),
            total_llm_calls=sum(e.llm_calls for e in self._ledger),
            total_latency_ms=sum(e.latency_ms for e in self._ledger),
            total_prompt_tokens=sum(e.prompt_tokens for e in self._ledger),
            total_completion_tokens=sum(e.completion_tokens for e in self._ledger),
            per_technology=per_tech,
        )


    @property
    def meaningful_rate(self) -> float:
        if self.total_units == 0:
            return 0.0
        return self.meaningful_throughput / self.total_units


__all__ = [
    "UnitKind",
    "LedgerEntry",
    "ThroughputSummary",
    "ThroughputAccounting",
]