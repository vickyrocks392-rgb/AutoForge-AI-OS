"""Phase-19 learning telemetry signals (NO learning logic).

This module emits structured telemetry events that the Phase-19 learning
system will consume.  AutoForge does not learn inside a run; the events
are signals, not decisions.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class TelemetryEventType(str, Enum):
    UNIT_ESTIMATED = "unit.estimated"
    UNIT_STARTED = "unit.started"
    UNIT_COMPLETED = "unit.completed"
    UNIT_FAILED = "unit.failed"
    UNIT_SKIPPED = "unit.skipped"
    UNIT_UNAVAILABLE = "unit.unavailable"
    VERIFICATION_RESULT = "verification.result"
    REPAIR_ATTEMPTED = "repair.attempted"
    REPAIR_COMPLETED = "repair.completed"
    REPAIR_EXHAUSTED = "repair.exhausted"
    THROUGHPUT_SUMMARY = "throughput.summary"
    DRIFT_OBSERVED = "drift.observed"
    LLM_FALLBACK_USED = "llm.fallback_used"
    RAG_EVIDENCE_PRODUCED = "rag.evidence_produced"
    TARGET_RESOLVED = "target.resolved"
    PROVENANCE_RECORDED = "provenance.recorded"


class TelemetryEvent(BaseModel):
    """A single structured Phase-19 learning signal."""

    event_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    session_id: str = ""
    event_type: TelemetryEventType = TelemetryEventType.UNIT_COMPLETED
    unit_id: str = ""
    payload: dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=_utc_now)


class TelemetryRecorder:
    """Append-only recorder for Phase-19 learning signals."""

    def __init__(self, session_id: str = "") -> None:
        self._session_id = session_id or str(uuid.uuid4())
        self._events: list[TelemetryEvent] = []

    @property
    def session_id(self) -> str:
        return self._session_id

    @property
    def events(self) -> list[TelemetryEvent]:
        return list(self._events)

    def emit(
        self,
        event_type: TelemetryEventType,
        *,
        unit_id: str = "",
        payload: dict[str, Any] | None = None,
    ) -> TelemetryEvent:
        event = TelemetryEvent(
            session_id=self._session_id,
            event_type=event_type,
            unit_id=unit_id,
            payload=dict(payload or {}),
        )
        self._events.append(event)
        return event

    def events_of_type(self, event_type: TelemetryEventType) -> list[TelemetryEvent]:
        return [e for e in self._events if e.event_type == event_type]

    def summary(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for e in self._events:
            out[e.event_type.value] = out.get(e.event_type.value, 0) + 1
        return out


__all__ = [
    "TelemetryEventType",
    "TelemetryEvent",
    "TelemetryRecorder",
]