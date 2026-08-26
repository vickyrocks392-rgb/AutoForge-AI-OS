"""Ports (structural protocols) owned by the Connector Platform.

Following the consumer-owned-port convention (ADR-002 / ADR-006 style), the
platform defines the narrow structural seams its connectors need. Concrete
implementations live elsewhere or are injected from the composition root;
this package imports NO other AutoForge package.
"""

from __future__ import annotations

import contextvars
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from autoforge_events.base import BaseEvent


@runtime_checkable
class ConnectorEventSink(Protocol):
    """Structural port for publishing canonical domain events.

    Satisfied structurally by the Event Platform's ``CanonicalEventBus`` and
    trivially by recording fakes in tests. Events published through this sink
    are ALWAYS frozen ``autoforge_events.BaseEvent`` instances.
    """

    def publish(self, event: BaseEvent) -> Any: ...


_current_correlation_id: contextvars.ContextVar[object] = contextvars.ContextVar(
    "autoforge_connector_correlation_id", default=None
)


def set_correlation_id(correlation_id: object) -> contextvars.Token:
    """Bind the ambient correlation ID for connector operations on this task."""
    return _current_correlation_id.set(correlation_id)


def reset_correlation_id(token: contextvars.Token) -> None:
    """Restore a previously bound correlation-ID token."""
    _current_correlation_id.reset(token)


def current_correlation_id() -> object:
    """Return the ambient correlation ID, or ``None``."""
    return _current_correlation_id.get()


@dataclass
class OperationObservation:
    """Structured observation of the most recent connector operation.

    Provides per-operation identity, latency and error category without
    emitting event noise for successful reads/writes; consumers needing
    full telemetry should poll ``last_operation`` or wrap calls themselves.
    """

    connector: str
    operation: str
    status: str = "ok"
    duration_ms: float = 0.0
    error_category: str | None = None
    detail: dict[str, Any] = field(default_factory=dict)

    def summary(self) -> dict[str, Any]:
        return {
            "connector": self.connector,
            "operation": self.operation,
            "status": self.status,
            "duration_ms": round(self.duration_ms, 3),
            "error_category": self.error_category,
            "detail": dict(self.detail),
        }
