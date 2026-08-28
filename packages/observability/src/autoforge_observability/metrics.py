"""
Deterministic metric collection, aggregation, and percentile calculation for AutoForge.
"""

from __future__ import annotations
import threading
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple, Any
from autoforge_observability.models import MetricObservation


class MetricsRegistry:
    """
    Thread-safe registry for counter, gauge, and duration metric observations.
    Calculates statistical percentiles (p50, p90, p99) deterministically.
    """

    def __init__(self) -> None:
        self._counters: Dict[str, float] = {}
        self._gauges: Dict[str, float] = {}
        self._histograms: Dict[str, List[float]] = {}
        self._observations: List[MetricObservation] = []
        self._lock = threading.Lock()

    def record_counter(self, name: str, value: float = 1.0, dimensions: Optional[Dict[str, Any]] = None) -> None:
        with self._lock:
            self._counters[name] = self._counters.get(name, 0.0) + value
            self._observations.append(
                MetricObservation(
                    name=name,
                    value=value,
                    timestamp=datetime.now(timezone.utc),
                    dimensions=dimensions or {},
                )
            )

    def record_gauge(self, name: str, value: float, dimensions: Optional[Dict[str, Any]] = None) -> None:
        with self._lock:
            self._gauges[name] = value
            self._observations.append(
                MetricObservation(
                    name=name,
                    value=value,
                    timestamp=datetime.now(timezone.utc),
                    dimensions=dimensions or {},
                )
            )

    def record_histogram(self, name: str, value: float, dimensions: Optional[Dict[str, Any]] = None) -> None:
        with self._lock:
            if name not in self._histograms:
                self._histograms[name] = []
            self._histograms[name].append(value)
            self._observations.append(
                MetricObservation(
                    name=name,
                    value=value,
                    timestamp=datetime.now(timezone.utc),
                    dimensions=dimensions or {},
                )
            )

    def get_counter(self, name: str) -> float:
        with self._lock:
            return self._counters.get(name, 0.0)

    def get_gauge(self, name: str) -> float:
        with self._lock:
            return self._gauges.get(name, 0.0)

    def get_percentile(self, name: str, percentile: float) -> float:
        """
        Calculate percentile (0.0 to 100.0) for a recorded histogram/duration metric.
        """
        with self._lock:
            values = self._histograms.get(name)
            if not values:
                return 0.0
            
            sorted_vals = sorted(values)
            k = (len(sorted_vals) - 1) * (percentile / 100.0)
            f = int(k)
            c = f + 1
            if c < len(sorted_vals):
                return sorted_vals[f] + (k - f) * (sorted_vals[c] - sorted_vals[f])
            return sorted_vals[f]

    def get_average(self, name: str) -> float:
        with self._lock:
            values = self._histograms.get(name)
            if not values:
                return 0.0
            return sum(values) / len(values)

    def get_observations(self) -> List[MetricObservation]:
        with self._lock:
            return list(self._observations)

    def clear(self) -> None:
        with self._lock:
            self._counters.clear()
            self._gauges.clear()
            self._histograms.clear()
            self._observations.clear()
