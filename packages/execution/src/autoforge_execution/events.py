"""
Execution Platform canonical event integration — Phase 10.

Emits canonical events using the frozen autoforge_events vocabulary.
"""

from __future__ import annotations

import uuid
from typing import Any, Protocol

from autoforge_events.base import BaseEvent
from autoforge_events.event_types import EventCategory, EventType
from autoforge_events.execution_events import (
    ExecutionCancelled,
    ExecutionCompleted,
    ExecutionFailed,
    ExecutionStarted,
    ExecutionTimedOut,
)


class EventSinkProtocol(Protocol):
    """Protocol for event sinks receiving domain events."""

    def publish(self, event: Any) -> None:
        ...


class ExecutionEvents:
    """
    Factory and publisher for canonical execution events.
    """

    def __init__(self, sink: EventSinkProtocol | None = None) -> None:
        self._sink = sink

    def _safe_publish(self, event: BaseEvent) -> None:
        if not self._sink:
            return
        try:
            self._sink.publish(event)
        except Exception:
            # Event publication failures must never break execution
            pass

    def emit_execution_started(
        self,
        execution_id: uuid.UUID,
        task_id: uuid.UUID,
        project_id: uuid.UUID,
        *,
        input_data: dict[str, Any] | None = None,
        max_duration_seconds: float | None = None,
        correlation_id: uuid.UUID | None = None,
    ) -> None:
        event = ExecutionStarted(
            aggregate_id=execution_id,
            task_id=task_id,
            project_id=project_id,
            input_data=input_data or {},
            max_duration_seconds=max_duration_seconds,
            correlation_id=correlation_id,
        )
        self._safe_publish(event)

    def emit_execution_completed(
        self,
        execution_id: uuid.UUID,
        task_id: uuid.UUID,
        project_id: uuid.UUID,
        duration_seconds: float,
        *,
        output_data: dict[str, Any] | None = None,
        artifact_ids: list[uuid.UUID] | None = None,
        correlation_id: uuid.UUID | None = None,
    ) -> None:
        event = ExecutionCompleted(
            aggregate_id=execution_id,
            task_id=task_id,
            project_id=project_id,
            duration_seconds=duration_seconds,
            output_data=output_data or {},
            artifact_ids=artifact_ids or [],
            correlation_id=correlation_id,
        )
        self._safe_publish(event)

    def emit_execution_failed(
        self,
        execution_id: uuid.UUID,
        task_id: uuid.UUID,
        project_id: uuid.UUID,
        error_code: str,
        error_message: str,
        *,
        duration_seconds: float | None = None,
        recoverable: bool = False,
        error_details: dict[str, Any] | None = None,
        correlation_id: uuid.UUID | None = None,
    ) -> None:
        event = ExecutionFailed(
            aggregate_id=execution_id,
            task_id=task_id,
            project_id=project_id,
            error_code=error_code,
            error_message=error_message,
            duration_seconds=duration_seconds,
            recoverable=recoverable,
            error_details=error_details or {},
            correlation_id=correlation_id,
        )
        self._safe_publish(event)

    def emit_loop_event(
        self,
        event_type_str: str,
        task_id: str,
        *,
        workflow_id: uuid.UUID | None = None,
        correlation_id: uuid.UUID | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        try:
            event_type = EventType(event_type_str)
        except ValueError:
            return

        event = BaseEvent(
            event_type=event_type,
            event_category=EventCategory.LOOP,
            aggregate_id=workflow_id or uuid.uuid4(),
            aggregate_type="EngineeringLoop",
            correlation_id=correlation_id,
            metadata=metadata or {},
        )
        self._safe_publish(event)
