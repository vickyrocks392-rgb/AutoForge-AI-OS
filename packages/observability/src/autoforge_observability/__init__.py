"""
AutoForge Observability Platform.
"""

from autoforge_observability.engine import ObservabilityPlatform
from autoforge_observability.models import (
    Severity,
    MetricObservation,
    StructuredLogEntry,
    TraceSpan,
)
from autoforge_observability.metrics import MetricsRegistry
from autoforge_observability.logging import StructuredLogger
from autoforge_observability.tracing import TraceTracker
from autoforge_observability.read_models import DashboardManager

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
]

__version__ = "0.1.0"
