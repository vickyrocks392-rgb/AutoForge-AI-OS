"""
AutoForge Measured Throughput Models.

Establishes throughput measurement models. The base contract is that
AutoForge does NOT use hard-coded LOC/day assumptions — it tracks
ACTUAL observed throughput and uses that for ETA calculations.

Throughput is segmented by technology, strategy, model, toolchain,
and hardware profile. This allows accurate per-component estimation.

Reuses:
- jobs: ModernizationJob (via job_id)
- units: MigrationUnit (via unit_id)
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class ThroughputMetric(str, Enum):
    """The throughput metric being measured."""

    LOC_PER_HOUR = "loc_per_hour"
    LOC_PER_DAY = "loc_per_day"
    FILES_PER_HOUR = "files_per_hour"
    MODULES_PER_HOUR = "modules_per_hour"
    TRANSFORMATIONS_PER_HOUR = "transformations_per_hour"
    VERIFICATION_THROUGHPUT = "verification_throughput"
    FAILURE_RATE = "failure_rate"
    RETRY_RATE = "retry_rate"
    INFERENCE_TIME_SEC = "inference_time_sec"
    CONTEXT_TOKENS = "context_tokens"
    TOOL_EXEC_TIME_SEC = "tool_exec_time_sec"


class ThroughputSegment(BaseModel):
    """A segmentation dimension for throughput tracking."""

    technology: str | None = None
    migration_strategy: str | None = None
    transformation_type: str | None = None
    model_id: str | None = None
    toolchain: str | None = None
    hardware_profile: str | None = None


class ThroughputObservation(BaseModel):
    """
    A single observation of throughput.

    Observations are added over time as AutoForge executes work.
    Aggregation produces the actual measured throughput for ETA.
    """

    observation_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    project_id: str
    job_id: str | None = None
    unit_id: str | None = None

    metric: ThroughputMetric
    value: float
    timestamp: datetime = Field(default_factory=_utc_now)

    segment: ThroughputSegment = Field(default_factory=ThroughputSegment)

    # Sample context
    sample_size: int = 1
    duration_seconds: float | None = None

    # Confidence (based on sample size)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)


class ThroughputProfile(BaseModel):
    """
    Aggregated throughput profile for a project.

    Contains all observations plus summary statistics. Used by
    the EstimationEngine to compute live ETA.
    """

    profile_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    project_id: str

    observations: list[ThroughputObservation] = Field(default_factory=list)

    # Summary statistics
    loc_per_hour_avg: float = 0.0
    loc_per_day_avg: float = 0.0
    failure_rate: float = 0.0
    retry_rate: float = 0.0
    average_inference_time_sec: float = 0.0
    average_context_tokens: float = 0.0
    average_tool_exec_time_sec: float = 0.0

    # Segmentation summary
    by_technology: dict[str, dict[str, float]] = Field(default_factory=dict)
    by_strategy: dict[str, dict[str, float]] = Field(default_factory=dict)
    by_model: dict[str, dict[str, float]] = Field(default_factory=dict)

    # Coverage
    has_sufficient_data: bool = False
    min_observations_for_reliable_eta: int = 3
    total_observations: int = 0

    last_updated: datetime = Field(default_factory=_utc_now)

    def add_observation(self, obs: ThroughputObservation) -> None:
        """Add an observation and recalculate summaries."""
        self.observations.append(obs)
        self.total_observations = len(self.observations)
        self.last_updated = _utc_now()
        self._recalc()

    def _recalc(self) -> None:
        """Recalculate summary statistics."""
        if not self.observations:
            return
        loc_hours = [o.value for o in self.observations if o.metric == ThroughputMetric.LOC_PER_HOUR]
        if loc_hours:
            self.loc_per_hour_avg = sum(loc_hours) / len(loc_hours)
            self.loc_per_day_avg = self.loc_per_hour_avg * 8  # 8h workday
        failures = [o for o in self.observations if o.metric == ThroughputMetric.FAILURE_RATE]
        if failures:
            self.failure_rate = sum(o.value for o in failures) / len(failures)
        inf_times = [o.value for o in self.observations if o.metric == ThroughputMetric.INFERENCE_TIME_SEC]
        if inf_times:
            self.average_inference_time_sec = sum(inf_times) / len(inf_times)
        ctx_tokens = [o.value for o in self.observations if o.metric == ThroughputMetric.CONTEXT_TOKENS]
        if ctx_tokens:
            self.average_context_tokens = sum(ctx_tokens) / len(ctx_tokens)
        tool_times = [o.value for o in self.observations if o.metric == ThroughputMetric.TOOL_EXEC_TIME_SEC]
        if tool_times:
            self.average_tool_exec_time_sec = sum(tool_times) / len(tool_times)
        self.has_sufficient_data = self.total_observations >= self.min_observations_for_reliable_eta
