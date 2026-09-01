"""
ETA and Duration Estimation Models.

Establishes the estimation contract. The base contract is:
- Optimistic, expected, pessimistic durations
- Confidence and uncertainty
- Assumptions
- Live recalculation
- Use actual observed throughput when available

The EstimationEngine (G.3+) is responsible for computing live ETAs.
This module defines the models.

Reuses:
- throughput: ThroughputProfile, ThroughputObservation
- sizing: LOCMetrics
- jobs: ModernizationJob (via job_id)
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class EstimationAssumption(BaseModel):
    """A single assumption used in estimation."""

    assumption_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    description: str
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    source: str = ""  # "throughput_history", "domain_expert", "market_data"


class DurationEstimate(BaseModel):
    """
    A duration estimate with three-point (PERT) values.

    - optimistic: best case (95th percentile faster)
    - expected: most likely
    - pessimistic: worst case (5th percentile slower)
    """

    optimistic_hours: float = 0.0
    expected_hours: float = 0.0
    pessimistic_hours: float = 0.0

    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    uncertainty_pct: float = 0.0  # (pessimistic - optimistic) / expected

    based_on_observations: int = 0
    based_on_assumptions: list[str] = Field(default_factory=list)


class ProjectEstimate(BaseModel):
    """
    The complete estimate for a modernization project.

    Contains:
    - Total LOC and remaining work
    - Duration with PERT values
    - Confidence and uncertainty
    - ETA and estimated completion
    - Assumptions
    """

    estimate_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    project_id: str
    job_id: str | None = None

    # Inputs
    total_loc: int = 0
    processed_loc: int = 0
    remaining_loc: int = 0
    total_files: int = 0
    remaining_files: int = 0

    # Throughput
    current_throughput_loc_per_hour: float = 0.0
    current_throughput_loc_per_day: float = 0.0
    throughput_basis: str = "default"  # "measured" | "default" | "blended"

    # Duration (PERT)
    duration: DurationEstimate = Field(default_factory=DurationEstimate)

    # Remaining work
    remaining_work_hours: float = 0.0
    remaining_work_days: float = 0.0

    # ETA
    eta: datetime | None = None
    estimated_completion_at: datetime | None = None
    eta_basis: str = "default"  # "live_measured" | "blended" | "default"

    # Assumptions
    assumptions: list[EstimationAssumption] = Field(default_factory=list)

    # Update tracking
    last_updated: datetime = Field(default_factory=_utc_now)
    last_recalculation_at: datetime | None = None
    recalculation_count: int = 0

    def update_throughput(self, loc_per_hour: float) -> None:
        """Update the throughput basis and recalculate remaining work."""
        self.current_throughput_loc_per_hour = loc_per_hour
        self.current_throughput_loc_per_day = loc_per_hour * 8
        self.throughput_basis = "measured" if loc_per_hour > 0 else "default"
        if loc_per_hour > 0 and self.remaining_loc > 0:
            self.remaining_work_hours = self.remaining_loc / loc_per_hour
            self.remaining_work_days = self.remaining_work_hours / 8
        self.last_recalculation_at = _utc_now()
        self.recalculation_count += 1
        self.last_updated = _utc_now()

    def is_reliable(self) -> bool:
        """Return True if the estimate is based on sufficient measured data."""
        return (
            self.throughput_basis in ("measured", "blended")
            and self.duration.based_on_observations >= 3
        )
