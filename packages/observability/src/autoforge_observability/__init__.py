"""
AutoForge Observability Platform.
"""

from autoforge_observability.engine import ObservabilityPlatform
from autoforge_observability.models import (
    Severity,
    MetricObservation,
    StructuredLogEntry,
    TraceSpan,
    NodeIdentity,
    NodeStatusEnum,
    NodeResourceMetadata,
    RoutingDecisionRecord,
    NodeObservabilityReadModel,
    FleetObservabilityReadModel,
)
from autoforge_observability.metrics import MetricsRegistry
from autoforge_observability.logging import StructuredLogger
from autoforge_observability.tracing import TraceTracker
from autoforge_observability.read_models import DashboardManager
from autoforge_observability.collector import EventTelemetryCollector

__all__ = [
    "ObservabilityPlatform",
    "Severity",
    "MetricObservation",
    "StructuredLogEntry",
    "TraceSpan",
    "MetricsRegistry",
    "StructuredLogger",
    "TraceTracker",
    "DashboardManager",
    "EventTelemetryCollector",
    "NodeIdentity",
    "NodeStatusEnum",
    "NodeResourceMetadata",
    "RoutingDecisionRecord",
    "NodeObservabilityReadModel",
    "FleetObservabilityReadModel",
]

__version__ = "0.1.0"
