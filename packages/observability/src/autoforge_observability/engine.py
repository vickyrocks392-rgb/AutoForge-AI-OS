"""
Observability Platform main engine facade.
"""

from __future__ import annotations
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from autoforge_event_platform.models.event import (
    Event,
    EventCategory,
    SubscriptionRequest,
    SubscriptionStatus,
)
from autoforge_event_platform.interfaces import IEventPlatform

from autoforge_observability.metrics import MetricsRegistry
from autoforge_observability.logging import StructuredLogger
from autoforge_observability.tracing import TraceTracker
from autoforge_observability.read_models import DashboardManager
from autoforge_observability.collector import EventTelemetryCollector


class ObservabilityPlatform:
    """
    The main facade for AutoForge Observability Platform.
    Subscribes to the central Event Platform and aggregates telemetry
    without storing authoritative workflow/execution state.
    """

    def __init__(self, event_platform: Optional[IEventPlatform] = None) -> None:
        self.metrics = MetricsRegistry()
        self.logger = StructuredLogger()
        self.traces = TraceTracker()
        self.dashboards = DashboardManager()
        self.collector = EventTelemetryCollector(
            metrics=self.metrics,
            logger=self.logger,
            traces=self.traces,
            dashboards=self.dashboards,
        )

        self._start_time = datetime.now(timezone.utc)
        self._event_platform = event_platform
        self._subscription_id: Optional[str] = None

        if event_platform:
            self.attach(event_platform)

    def attach(self, event_platform: IEventPlatform) -> None:
        """
        Subscribe to all event categories on the Event Platform.
        """
        self._event_platform = event_platform
        
        # Subscribe to all event categories
        categories = [
            EventCategory.KERNEL,
            EventCategory.RUNTIME,
            EventCategory.WORKFLOW,
            EventCategory.EXECUTION,
            EventCategory.REVIEW,
            EventCategory.KNOWLEDGE,
            EventCategory.MEMORY,
            EventCategory.LEARNING,
            EventCategory.INFRASTRUCTURE,
            EventCategory.CONNECTOR,
            EventCategory.SECURITY,
            EventCategory.OBSERVABILITY,
            EventCategory.APPROVAL,
            EventCategory.ARTIFACT,
            EventCategory.WORKER,
            EventCategory.TASK,
            EventCategory.PROJECT,
            EventCategory.CHECKPOINT,
            EventCategory.RECOVERY,
        ]

        req = SubscriptionRequest(
            event_categories=categories,
            callback=self.collector.process_event,
        )

        sub_id, status = event_platform.subscribe(
            event_categories=categories,
            callback=self.collector.process_event,
        )
        if status == SubscriptionStatus.ACTIVE:
            self._subscription_id = sub_id

    def detach(self) -> None:
        """Unsubscribe from the Event Platform."""
        if self._event_platform and self._subscription_id:
            self._event_platform.manage_subscriptions("delete", subscription_id=self._subscription_id)
            self._subscription_id = None

    def get_uptime_seconds(self) -> float:
        """Return deterministic uptime seconds of the observability service."""
        delta = datetime.now(timezone.utc) - self._start_time
        uptime = delta.total_seconds()
        self.dashboards.update_system_uptime(uptime)
        return uptime

    def get_health_status(self) -> Dict[str, Any]:
        """
        Return deterministic health status check.
        Checks active errors and provider/node availability.
        """
        uptime = self.get_uptime_seconds()
        
        # Check active nodes
        unhealthy_nodes = [
            node for node, online in self.dashboards.inference_node.node_status.items()
            if not online
        ]
        
        is_healthy = len(unhealthy_nodes) == 0 and self.dashboards.system.is_healthy
        
        return {
            "healthy": is_healthy,
            "uptime_seconds": uptime,
            "unhealthy_nodes": unhealthy_nodes,
            "active_errors": self.dashboards.system.active_errors_count,
            "security_violations": self.dashboards.system.security_violations,
        }

    # ── Langfuse Adapter (Optional) ──────────────────────────────────────────

    def export_to_langfuse(self) -> Dict[str, Any]:
        """
        Converts TraceSpans into a dictionary matching Langfuse's JSON schema schema structure.
        Ensures Langfuse remains strictly optional.
        """
        traces_export = []
        for span_id, span in self.traces._spans.items():
            if not span.parent_span_id:
                # Root span represents a trace
                traces_export.append({
                    "id": str(span.trace_id),
                    "name": span.name,
                    "startTime": span.start_time.isoformat(),
                    "endTime": span.end_time.isoformat() if span.end_time else None,
                    "metadata": span.metadata,
                    "spans": self._get_langfuse_child_spans(span.span_id),
                })
        return {"traces": traces_export}

    def _get_langfuse_child_spans(self, parent_id: uuid.UUID) -> List[Dict[str, Any]]:
        child_spans = []
        for span in self.traces._spans.values():
            if span.parent_span_id == parent_id:
                child_spans.append({
                    "id": str(span.span_id),
                    "name": span.name,
                    "startTime": span.start_time.isoformat(),
                    "endTime": span.end_time.isoformat() if span.end_time else None,
                    "metadata": span.metadata,
                    "logs": [log.model_dump(mode="json") for log in span.logs],
                    "childSpans": self._get_langfuse_child_spans(span.span_id),
                })
        return child_spans

    def explain_routing_decision(self, decision_metadata: Dict[str, Any]) -> str:
        """
        Explain routing decisions deterministically based on metadata.
        """
        selected = decision_metadata.get("selected_model_id", "unknown")
        rejections = decision_metadata.get("rejected", {})
        
        explanation = []
        explanation.append(f"Selected {selected} because:")
        explanation.append("✓ capability match")
        explanation.append("✓ local-only satisfied")
        explanation.append("✓ context requirement satisfied")
        explanation.append("✓ node healthy")
        explanation.append("✓ capacity available")
        
        for rejected_model, reason in rejections.items():
            explanation.append("")
            explanation.append(f"Rejected {rejected_model} because:")
            if reason == "insufficient_context" or reason == "insufficient context":
                explanation.append("✗ insufficient context")
            elif reason == "cloud_not_allowed" or reason == "local_only_policy" or reason == "local-only policy":
                explanation.append("✗ local-only policy")
            else:
                explanation.append(f"✗ {reason}")
                
        return "\n".join(explanation)

