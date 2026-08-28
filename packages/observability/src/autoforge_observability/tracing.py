"""
Trace reconstruction and Span context management for AutoForge.
"""

from __future__ import annotations
import threading
import uuid
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple, Any
from autoforge_observability.models import TraceSpan, StructuredLogEntry


class TraceTracker:
    """
    Thread-safe repository for spans.
    Reconstructs TraceSpan DAG structures using correlation IDs.
    """

    def __init__(self) -> None:
        self._spans: Dict[uuid.UUID, TraceSpan] = {}
        self._lock = threading.Lock()

    def start_span(
        self,
        name: str,
        trace_id: uuid.UUID,
        parent_span_id: Optional[uuid.UUID] = None,
        correlation_id: Optional[uuid.UUID] = None,
        **kwargs: Any,
    ) -> TraceSpan:
        span_id = uuid.uuid4()
        span = TraceSpan(
            span_id=span_id,
            trace_id=trace_id,
            parent_span_id=parent_span_id,
            name=name,
            start_time=datetime.now(timezone.utc),
            correlation_id=correlation_id,
            **kwargs,
        )
        with self._lock:
            self._spans[span_id] = span
            if parent_span_id and parent_span_id in self._spans:
                # Add child reference to parent
                parent = self._spans[parent_span_id]
                updated_children = parent.child_spans + [span_id]
                self._spans[parent_span_id] = parent.model_copy(update={"child_spans": updated_children})
        return span

    def end_span(self, span_id: uuid.UUID, status: str = "completed") -> Optional[TraceSpan]:
        with self._lock:
            span = self._spans.get(span_id)
            if not span:
                return None
            updated = span.model_copy(
                update={
                    "end_time": datetime.now(timezone.utc),
                    "status": status,
                }
            )
            self._spans[span_id] = updated
            return updated

    def add_log_to_span(self, span_id: uuid.UUID, log_entry: StructuredLogEntry) -> bool:
        with self._lock:
            span = self._spans.get(span_id)
            if not span:
                return False
            updated_logs = span.logs + [log_entry]
            self._spans[span_id] = span.model_copy(update={"logs": updated_logs})
            return True

    def get_span(self, span_id: uuid.UUID) -> Optional[TraceSpan]:
        with self._lock:
            return self._spans.get(span_id)

    def get_trace_spans(self, trace_id: uuid.UUID) -> List[TraceSpan]:
        with self._lock:
            return [s for s in self._spans.values() if s.trace_id == trace_id]

    def get_span_by_correlation(self, correlation_id: uuid.UUID) -> Optional[TraceSpan]:
        with self._lock:
            for span in self._spans.values():
                if span.correlation_id == correlation_id:
                    return span
            return None

    def clear(self) -> None:
        with self._lock:
            self._spans.clear()
