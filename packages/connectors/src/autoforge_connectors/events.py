"""Canonical event integration for connectors.

All events are frozen ``autoforge_events.BaseEvent`` instances using ONLY the
existing canonical vocabulary — Phase 8 adds NO event types/categories
(ADR-001 governs additive extension; none is required here).

Mapping of connector facts onto canonical types:

    ====================================  ==========================
    Fact                                  Canonical EventType
    ====================================  ==========================
    connector operation failed            ``FAILURE_DETECTED``
                                          (category FAILURE)
    connector capability degraded         ``SERVICE_DEGRADED``
                                          (unavailable/binary/path)
    ====================================  ==========================

Successful operations intentionally emit NO bus event (noise control,
authorisation note in ADR-007); their latency/status are returned via
:class:`~autoforge_connectors.interfaces.OperationObservation` and recorded on
the connector's ``last_operation``. Structured detail lives exclusively in
event ``metadata`` with ``metadata.component == "connectors"``.
"""

from __future__ import annotations

import uuid
from typing import Any

from autoforge_events.base import BaseEvent
from autoforge_events.event_types import EventCategory, EventType

from autoforge_connectors.interfaces import (
    current_correlation_id,
)


def _meta(text: str, limit: int = 512) -> str:
    """Truncate free text for metadata payloads."""
    return text[:limit]


class ConnectorEvents:
    """Builds (and optionally publishes) connector domain events."""

    def __init__(self, sink: Any | None = None) -> None:
        self._sink = sink

    @property
    def enabled(self) -> bool:
        return self._sink is not None

    def _emit(self, event: BaseEvent) -> None:
        if self._sink is not None:
            self._sink.publish(event)

    # -- failure -------------------------------------------------------------

    def operation_failed(
        self,
        *,
        connector: str,
        operation: str,
        error_category: str,
        message: str,
        duration_ms: float = 0.0,
        details: dict[str, Any] | None = None,
        correlation_id: object | None = None,
        causation_id: uuid.UUID | None = None,
    ) -> BaseEvent:
        """A connector operation failed — canonical ``failure.detected``."""
        cid = correlation_id or current_correlation_id()
        base_details = dict(details or {})
        for key, value in list(base_details.items()):
            # Details may carry user paths; keep strings bounded.
            if isinstance(value, str):
                base_details[key] = _meta(value)
        event = BaseEvent(
            event_type=EventType.FAILURE_DETECTED,
            event_category=EventCategory.FAILURE,
            aggregate_id=uuid.uuid4(),
            aggregate_type="ConnectorOperation",
            correlation_id=cid if isinstance(cid, uuid.UUID) else None,
            causation_id=causation_id,
            metadata={
                "component": "connectors",
                "connector": connector,
                "operation": operation,
                "error_category": error_category,
                "duration_ms": round(duration_ms, 3),
                "message": _meta(message),
                **base_details,
            },
        )
        self._emit(event)
        return event

    # -- degradation ---------------------------------------------------------

    def connector_unavailable(
        self,
        *,
        connector: str,
        reason: str,
        correlation_id: object | None = None,
        causation_id: uuid.UUID | None = None,
    ) -> BaseEvent:
        """A connector lost availability — canonical ``service.degraded``."""
        cid = correlation_id or current_correlation_id()
        event = BaseEvent(
            event_type=EventType.SERVICE_DEGRADED,
            event_category=EventCategory.SERVICE,
            aggregate_id=uuid.uuid4(),
            aggregate_type="Connector",
            correlation_id=cid if isinstance(cid, uuid.UUID) else None,
            causation_id=causation_id,
            metadata={
                "component": "connectors",
                "connector": connector,
                "reason": _meta(reason),
            },
        )
        self._emit(event)
        return event
