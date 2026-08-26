"""Shared per-operation instrumentation for connector implementations.

One context manager drives: latency capture, ``last_operation`` recording and
canonical failure-event emission (failures only — see ``events.py``). Keeping
it central guarantees uniform error classification across connectors.
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from autoforge_connectors.errors import ConnectorError
from autoforge_connectors.events import ConnectorEvents
from autoforge_connectors.interfaces import OperationObservation


@contextmanager
def observe_connector_operation(
    *,
    events: ConnectorEvents | None,
    record_into: dict[str, Any],
    connector: str,
    operation: str,
    detail: dict[str, Any] | None = None,
) -> Iterator[OperationObservation]:
    """Instrument one connector operation.

    Yields an :class:`OperationObservation`; on success it is stored under
    ``record_into["last_operation"]`` with status ``"ok"``. On a
    :class:`ConnectorError` the observation records the error category AND
    (when ``events`` provided) a canonical ``failure.detected`` event is
    published. Non-connector exceptions propagate unobserved — they indicate
    bugs inside the platform itself and must fail loudly.
    """
    observation = OperationObservation(
        connector=connector, operation=operation, detail=dict(detail or {})
    )
    started = time.perf_counter()
    try:
        yield observation
    except ConnectorError as exc:
        observation.status = "failed"
        observation.error_category = exc.category
        observation.duration_ms = (time.perf_counter() - started) * 1000.0
        record_into["last_operation"] = observation
        if events is not None:
            events.operation_failed(
                connector=connector,
                operation=operation,
                error_category=exc.category,
                message=str(exc),
                duration_ms=observation.duration_ms,
                details=exc.details or None,
            )
        raise
    else:
        observation.duration_ms = (time.perf_counter() - started) * 1000.0
        record_into["last_operation"] = observation
