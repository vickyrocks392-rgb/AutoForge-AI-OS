"""Canonical event factory for the AI Infrastructure Platform.

All events are canonical :class:`autoforge_events.base.BaseEvent` instances
using ONLY the frozen ``autoforge_events`` vocabulary — no new event types
are introduced by Phase 7. Mapping of continuity facts onto the existing
vocabulary:

    ============================  =========================================
    Fact                          Canonical EventType
    ============================  =========================================
    attempt failure               ``FAILURE_DETECTED``
    retry scheduled/attempted     ``RECOVERY_STARTED`` (metadata.phase=retry)
    provider failover transition  ``SERVICE_DEGRADED``
    execution finally succeeded   ``RECOVERY_COMPLETED`` (after resilience)
    every candidate exhausted     ``RECOVERY_FAILED``
    checkpoint restored           ``CHECKPOINT_RESTORED``
    ============================  =========================================

Structured detail (candidates, attempts, provider switches) lives in event
``metadata``, never in new types. The sink is the injected
:class:`autoforge_ai_infrastructure.interfaces.CanonicalEventSink`
(satisfied structurally by the Event Platform's ``CanonicalEventBus``).
"""

from __future__ import annotations

import uuid
from typing import Any

from autoforge_events.base import BaseEvent
from autoforge_events.event_types import EventCategory, EventType

from autoforge_ai_infrastructure.metadata import AttemptRecord

_FAILURE_TYPES = frozenset(
    {
        EventType.FAILURE_DETECTED,
        EventType.RECOVERY_STARTED,
        EventType.RECOVERY_COMPLETED,
        EventType.RECOVERY_FAILED,
    }
)


def _event(
    *,
    event_type: EventType,
    aggregate_id: uuid.UUID,
    aggregate_type: str,
    correlation_id: uuid.UUID | None,
    causation_id: uuid.UUID | None,
    metadata: dict[str, Any],
) -> BaseEvent:
    return BaseEvent(
        event_type=event_type,
        event_category=(
            EventCategory.FAILURE if event_type in _FAILURE_TYPES else EventCategory.SERVICE
        ),
        aggregate_id=aggregate_id,
        aggregate_type=aggregate_type,
        correlation_id=correlation_id,
        causation_id=causation_id,
        metadata=metadata,
    )


class AIInfrastructureEvents:
    """Builds (and optionally publishes) AI infrastructure domain events."""

    def __init__(self, sink: Any | None = None) -> None:
        self._sink = sink

    @property
    def enabled(self) -> bool:
        return self._sink is not None

    def _emit(self, event: BaseEvent) -> None:
        if self._sink is not None:
            self._sink.publish(event)

    # -- continuity ----------------------------------------------------------

    def failure_detected(
        self,
        record: AttemptRecord,
        correlation_id: uuid.UUID | None = None,
        causation_id: uuid.UUID | None = None,
    ) -> BaseEvent:
        event = _event(
            event_type=EventType.FAILURE_DETECTED,
            aggregate_id=record.execution_id,
            aggregate_type="AiExecution",
            correlation_id=correlation_id,
            causation_id=causation_id,
            metadata={
                "component": "ai_infrastructure",
                **record.summary(),
            },
        )
        self._emit(event)
        return event

    def recovery_started(
        self,
        execution_id: uuid.UUID,
        phase: str,
        from_provider: str | None,
        to_model: str | None,
        correlation_id: uuid.UUID | None = None,
        causation_id: uuid.UUID | None = None,
    ) -> BaseEvent:
        """A resilience action begins: ``phase`` is ``retry`` or ``failover``."""
        event = _event(
            event_type=EventType.RECOVERY_STARTED,
            aggregate_id=execution_id,
            aggregate_type="AiExecution",
            correlation_id=correlation_id,
            causation_id=causation_id,
            metadata={
                "component": "ai_infrastructure",
                "phase": phase,
                "from_provider": from_provider,
                "to_model": to_model,
            },
        )
        self._emit(event)
        return event

    def service_degraded(
        self,
        execution_id: uuid.UUID,
        provider_id: str,
        reason: str,
        correlation_id: uuid.UUID | None = None,
        causation_id: uuid.UUID | None = None,
    ) -> BaseEvent:
        """Provider failover transition observed during continuity."""
        event = _event(
            event_type=EventType.SERVICE_DEGRADED,
            aggregate_id=execution_id,
            aggregate_type="Provider",
            correlation_id=correlation_id,
            causation_id=causation_id,
            metadata={
                "component": "ai_infrastructure",
                "provider_id": provider_id,
                "reason": reason[:512],
            },
        )
        self._emit(event)
        return event

    def recovery_completed(
        self,
        execution_id: uuid.UUID,
        model_id: str,
        provider_id: str,
        attempts: int,
        failovers: int,
        correlation_id: uuid.UUID | None = None,
        causation_id: uuid.UUID | None = None,
    ) -> BaseEvent:
        event = _event(
            event_type=EventType.RECOVERY_COMPLETED,
            aggregate_id=execution_id,
            aggregate_type="AiExecution",
            correlation_id=correlation_id,
            causation_id=causation_id,
            metadata={
                "component": "ai_infrastructure",
                "model_id": model_id,
                "provider_id": provider_id,
                "attempts": attempts,
                "failovers": failovers,
            },
        )
        self._emit(event)
        return event

    def recovery_failed(
        self,
        execution_id: uuid.UUID,
        history_summary: list[dict[str, Any]],
        error_message: str,
        correlation_id: uuid.UUID | None = None,
        causation_id: uuid.UUID | None = None,
    ) -> BaseEvent:
        event = _event(
            event_type=EventType.RECOVERY_FAILED,
            aggregate_id=execution_id,
            aggregate_type="AiExecution",
            correlation_id=correlation_id,
            causation_id=causation_id,
            metadata={
                "component": "ai_infrastructure",
                "attempt_history": history_summary,
                "error_message": error_message[:512],
            },
        )
        self._emit(event)
        return event

    def checkpoint_restored(
        self,
        execution_id: uuid.UUID,
        checkpoint_id: uuid.UUID,
        project_id: uuid.UUID,
        correlation_id: uuid.UUID | None = None,
        causation_id: uuid.UUID | None = None,
    ) -> BaseEvent:
        event = _event(
            event_type=EventType.CHECKPOINT_RESTORED,
            aggregate_id=checkpoint_id,
            aggregate_type="Checkpoint",
            correlation_id=correlation_id,
            causation_id=causation_id,
            metadata={
                "component": "ai_infrastructure",
                "execution_id": str(execution_id),
                "project_id": str(project_id),
                "restored_by": "execution_continuity_manager",
            },
        )
        self._emit(event)
        return event
