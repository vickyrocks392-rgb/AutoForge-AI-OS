"""Review Engine canonical event integration — Phase 11.

Emits review events using the FROZEN autoforge_events vocabulary.  No new
event types are introduced (section 27: do not expand vocabulary without ADR).
The existing REVIEW category and REVIEW_* event types are reused.
"""

from __future__ import annotations

import uuid
from typing import Any, Protocol

from autoforge_events.base import BaseEvent
from autoforge_events.event_types import EventCategory, EventType


class ReviewEventSinkProtocol(Protocol):
    """Protocol for event sinks that receive review events."""

    def publish(self, event: Any) -> None:
        ...


class ReviewEvents:
    """Factory/publisher for canonical review events."""

    _VERBOSE_NAMES = {
        "review.completed": "ReviewEngine",
        "review.approved": "ReviewEngine",
        "review.rejected": "ReviewEngine",
        "review.changes_requested": "ReviewEngine",
    }

    def __init__(self, sink: ReviewEventSinkProtocol | None = None) -> None:
        self._sink = sink

    def _safe_publish(self, event: BaseEvent) -> None:
        if self._sink is None:
            return
        try:
            self._sink.publish(event)
        except Exception:
            # Event failures must never break review.
            pass

    def _emit(
        self,
        event_type: EventType,
        review_id: str,
        *,
        correlation_id: uuid.UUID | None,
        aggregate_id: uuid.UUID | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        try:
            rid = uuid.UUID(review_id) if review_id else uuid.uuid4()
        except ValueError:
            rid = uuid.uuid4()
        event = BaseEvent(
            event_type=event_type,
            event_category=EventCategory.REVIEW,
            aggregate_id=aggregate_id or rid,
            aggregate_type="Review",
            correlation_id=correlation_id,
            metadata=metadata or {},
        )
        self._safe_publish(event)

    def emit_completed(
        self,
        review_id: str,
        *,
        gate: str,
        decision: str,
        correlation_id: uuid.UUID | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        self._emit(
            EventType.REVIEW_COMPLETED,
            review_id,
            correlation_id=correlation_id,
            metadata={"gate": gate, "decision": decision, **(metadata or {})},
        )

    async def emit(self, name: str, payload: Any, *, correlation_id: Any = None, **kw) -> None:
        """Generic async emit dispatched by canonical event name (section 27).

        Maps string names to existing REVIEW event types — no new vocabulary
        is introduced.
        """
        rid = getattr(payload, "review_id", None) or getattr(payload, "request_id", None) or ""
        cid = correlation_id or getattr(payload, "correlation_id", None)
        md = getattr(payload, "metadata", None) or {}
        if name == "review.started":
            # No dedicated event type — emit completed-style with a marker.
            self._emit(
                EventType.REVIEW_COMPLETED,
                rid,
                correlation_id=cid,
                metadata={"phase": "started", **(md if isinstance(md, dict) else {})},
            )
        elif name == "review.completed":
            gate = kw.get("gate", "")
            decision = kw.get("decision", "")
            self.emit_completed(
                rid, gate=gate, decision=decision, correlation_id=cid, metadata=md,
            )
        elif name == "review.cycle_completed":
            self._emit(
                EventType.REVIEW_COMPLETED,
                rid,
                correlation_id=cid,
                metadata={"phase": "cycle_completed", **(md if isinstance(md, dict) else {})},
            )
        else:
            # Unknown name — fall back to REVIEW_COMPLETED as a safe marker.
            self._emit(
                EventType.REVIEW_COMPLETED,
                rid,
                correlation_id=cid,
                metadata={**(md if isinstance(md, dict) else {}), "phase": name},
            )

    def emit_approved(
        self,
        review_id: str,
        *,
        correlation_id: uuid.UUID | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        self._emit(EventType.REVIEW_APPROVED, review_id, correlation_id=correlation_id, metadata=metadata)

    def emit_rejected(
        self,
        review_id: str,
        *,
        correlation_id: uuid.UUID | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        self._emit(EventType.REVIEW_REJECTED, review_id, correlation_id=correlation_id, metadata=metadata)

    def emit_changes_requested(
        self,
        review_id: str,
        *,
        correlation_id: uuid.UUID | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        self._emit(
            EventType.REVIEW_CHANGES_REQUESTED,
            review_id,
            correlation_id=correlation_id,
            metadata=metadata,
        )