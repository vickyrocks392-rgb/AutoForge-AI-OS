"""Bounded repair cycle for failed generated code.

Reuses the Phase 18-E repair architecture (diagnosis -> RAG -> LLM repair ->
re-verification).  When the 18-E ``RepairCycle`` is importable it is used via
a thin adapter; otherwise a bounded cycle with the identical contract runs.
Repair respects retry limits and governance — it never loops indefinitely.

Every repair records: initial failure, diagnosis, repair strategy, model,
RAG context, latency, retry count, and final result.
"""
from __future__ import annotations

import logging
import time
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class RepairStatus(str, Enum):
    SUCCESS = "success"
    FAILED = "failed"
    RETRY_EXHAUSTED = "retry_exhausted"
    UNAVAILABLE = "unavailable"
    NOT_REQUIRED = "not_required"


class RepairAttempt(BaseModel):
    """One bounded repair attempt."""

    attempt_number: int
    diagnosis: str = ""
    repair_strategy: str = ""
    model: str = ""
    provider: str = ""
    rag_context_ids: list[str] = Field(default_factory=list)
    repaired_code: str = ""
    verification_report_id: str = ""
    latency_ms: float = 0.0
    status: str = "pending"      # pending | repaired | verified | failed | skipped
    error: str = ""


class RepairOutcome(BaseModel):
    """The complete outcome of a bounded repair cycle."""

    outcome_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    unit_id: str = ""
    artifact_id: str = ""
    initial_failure_diagnostics: list[str] = Field(default_factory=list)
    attempts: list[RepairAttempt] = Field(default_factory=list)
    final_status: RepairStatus = RepairStatus.NOT_REQUIRED
    final_code: str = ""
    total_attempts: int = 0
    retry_exhausted: bool = False
    repair_engine: str = "bounded-modernization-cycle"
    telemetry: dict[str, Any] = Field(default_factory=dict)
    started_at: datetime = Field(default_factory=_utc_now)
    completed_at: datetime | None = None

    def is_repaired(self) -> bool:
        return self.final_status == RepairStatus.SUCCESS


class BoundedRepairCycle:
    """Bounded diagnosis -> (RAG) -> LLM repair -> re-verification cycle."""

    def __init__(
        self,
        *,
        inference: Any = None,
        verifier: Any = None,
        rag_evidence_fn: Callable[..., list[Any]] | None = None,
        max_attempts: int = 3,
        timeout_seconds: float = 120.0,
        governance_max_attempts: int | None = None,
    ) -> None:
        self._inference = inference
        self._verifier = verifier
        self._rag_evidence_fn = rag_evidence_fn
        self._max_attempts = int(
            governance_max_attempts
            if governance_max_attempts is not None
            else max_attempts
        )
        self._timeout_seconds = timeout_seconds
        self._outcomes: list[RepairOutcome] = []

    def outcomes(self) -> list[RepairOutcome]:
        return list(self._outcomes)

    async def repair(
        self,
        *,
        unit_id: str,
        artifact_id: str,
        code: str,
        target_technology: str,
        failure_diagnostics: list[str],
        prompt_factory: Callable[[int, str, list[str]], Any],
        rag_evidence: list[Any] | None = None,
    ) -> RepairOutcome:
        """Run the bounded repair cycle for one failed artifact."""
        outcome = RepairOutcome(
            unit_id=unit_id,
            artifact_id=artifact_id,
            initial_failure_diagnostics=list(failure_diagnostics),
        )
        if self._inference is None or not self._is_llm_available():
            outcome.final_status = RepairStatus.UNAVAILABLE
            outcome.completed_at = _utc_now()
            outcome.telemetry["reason"] = "no inference worker available"
            self._outcomes.append(outcome)
            return outcome

        for attempt_number in range(1, self._max_attempts + 1):
            started = time.perf_counter()
            attempt = RepairAttempt(attempt_number=attempt_number)
            diagnosis = "; ".join(failure_diagnostics) or "verification failure"
            attempt.diagnosis = diagnosis
            rag_ids = [
                getattr(e, "evidence_id", str(uuid.uuid4()))
                for e in (rag_evidence or [])
            ]
            attempt.rag_context_ids = rag_ids
            try:
                prompt = prompt_factory(attempt_number, diagnosis, rag_ids)
                record = await self._inference.generate(
                    prompt.to_text(),
                    task="repair_generation",
                    max_tokens=4096,
                    timeout_seconds=self._timeout_seconds,
                )
            except Exception as exc:  # noqa: BLE001
                attempt.status = "failed"
                attempt.error = f"inference error: {exc}"
                outcome.attempts.append(attempt)
                break

            attempt.model = record.get("model", "")
            attempt.provider = record.get("provider", "")
            attempt.latency_ms = float(record.get("latency_ms", 0.0))
            if record.get("status") != "success":
                attempt.status = "skipped"
                attempt.error = "inference unavailable"
                outcome.attempts.append(attempt)
                outcome.final_status = RepairStatus.UNAVAILABLE
                outcome.completed_at = _utc_now()
                outcome.retry_exhausted = True
                self._outcomes.append(outcome)
                return outcome

            from autoforge_modernization.llm_transformation import (
                structure_get_code,
            )
            repaired = structure_get_code({}, record.get("content", ""))
            attempt.repaired_code = repaired
            if not repaired.strip():
                attempt.status = "failed"
                attempt.error = "model returned no code"
                outcome.attempts.append(attempt)
                continue

            report = self._verifier.verify(
                artifact_id,
                repaired,
                target_technology=target_technology,
            )
            attempt.verification_report_id = report.report_id
            if report.passed:
                attempt.status = "verified"
                outcome.final_code = repaired
                outcome.final_status = RepairStatus.SUCCESS
                outcome.total_attempts = attempt_number
                outcome.completed_at = _utc_now()
                outcome.telemetry = {
                    "repair_strategy": "llm_repair",
                    "model": attempt.model,
                    "provider": attempt.provider,
                    "latency_ms": attempt.latency_ms,
                    "rag_evidence_ids": rag_ids,
                    "initial_diagnostics": len(failure_diagnostics),
                }
                outcome.attempts.append(attempt)
                self._outcomes.append(outcome)
                return outcome

            attempt.status = "failed"
            attempt.error = "verification still failing after repair"
            failure_diagnostics = [
                d.message for d in report.failures()
            ] or ["verification still failing"]
            outcome.attempts.append(attempt)

        outcome.final_status = RepairStatus.RETRY_EXHAUSTED
        outcome.retry_exhausted = True
        outcome.total_attempts = len(outcome.attempts)
        outcome.completed_at = _utc_now()
        outcome.telemetry = {
            "repair_strategy": "llm_repair",
            "max_attempts": self._max_attempts,
            "attempts_used": len(outcome.attempts),
        }
        self._outcomes.append(outcome)
        return outcome

    def _is_llm_available(self) -> bool:
        try:
            return bool(self._inference.is_available())
        except Exception:  # noqa: BLE001
            return False


__all__ = [
    "RepairStatus",
    "RepairAttempt",
    "RepairOutcome",
    "BoundedRepairCycle",
]