"""PERT-style estimation and live ETA tracking for modernization tasks.

Provides deterministic per-unit estimates and live drift tracking against
actual durations.  Estimates are based on historical data when available;
otherwise a conservative fallback is used.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class DriftStatus(str, Enum):
    ON_TRACK = "on_track"
    AHEAD = "ahead"
    BEHIND = "behind"
    UNKNOWN = "unknown"


@dataclass
class _DurationSample:
    unit_id: str
    estimated_ms: float
    actual_ms: float
    timestamp: datetime


@dataclass
class PertEstimate:
    optimistic_ms: float
    most_likely_ms: float
    pessimistic_ms: float

    @property
    def expected_ms(self) -> float:
        return (
            self.optimistic_ms
            + 4 * self.most_likely_ms
            + self.pessimistic_ms
        ) / 6

    @property
    def sigma_ms(self) -> float:
        return (self.pessimistic_ms - self.optimistic_ms) / 6


class UnitEstimate(BaseModel):
    unit_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    artifact_count: int = 0
    estimated_seconds: float = 0.0
    estimate_type: str = "historical"
    drift_seconds: float = 0.0
    drift_status: DriftStatus = DriftStatus.UNKNOWN
    completed_at: datetime | None = None
    started_at: datetime = Field(default_factory=_utc_now)


class LiveETA(BaseModel):
    session_id: str = ""
    total_units: int = 0
    completed_units: int = 0
    estimated_remaining_ms: float = 0.0
    estimated_total_ms: float = 0.0
    drift_ms: float = 0.0
    drift_status: DriftStatus = DriftStatus.UNKNOWN
    updated_at: datetime = Field(default_factory=_utc_now)


class DriftEntry(BaseModel):
    entry_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    session_id: str = ""
    unit_id: str = ""
    estimated_ms: float = 0.0
    actual_ms: float = 0.0
    drift_ms: float = 0.0
    status: DriftStatus = DriftStatus.UNKNOWN
    timestamp: datetime = Field(default_factory=_utc_now)


_DRIFT_THRESHOLD_PCT = 0.15


class ModernizationEstimator:
    """PERT estimator with rolling historical averages and live ETA."""

    FALLBACK_PER_ARTIFACT_MS: float = 30_000.0

    def __init__(self, session_id: str = "") -> None:
        self._session_id = session_id or str(uuid.uuid4())
        self._samples: list[_DurationSample] = []
        self._pending: dict[str, float] = {}
        self._estimates: dict[str, UnitEstimate] = {}

    @property
    def session_id(self) -> str:
        return self._session_id

    def _compute_pert(self) -> PertEstimate | None:
        if len(self._samples) < 3:
            return None
        actuals = sorted(s.actual_ms for s in self._samples)
        n = len(actuals)
        return PertEstimate(
            optimistic_ms=actuals[0],
            most_likely_ms=actuals[n // 2],
            pessimistic_ms=actuals[-1],
        )

    def _pert_estimate(self, artifact_count: int) -> PertEstimate:
        pert = self._compute_pert()
        if pert is None:
            base = artifact_count * self.FALLBACK_PER_ARTIFACT_MS
            return PertEstimate(
                optimistic_ms=base * 0.5,
                most_likely_ms=base,
                pessimistic_ms=base * 1.5,
            )
        ref_count = max(
            1,
            sum(e.artifact_count for e in self._estimates.values())
            // max(1, len(self._estimates)),
        )
        scale = artifact_count / ref_count
        return PertEstimate(
            optimistic_ms=pert.optimistic_ms * scale,
            most_likely_ms=pert.most_likely_ms * scale,
            pessimistic_ms=pert.pessimistic_ms * scale,
        )

    def estimate(self, unit_id: str, artifact_count: int = 1) -> UnitEstimate:
        """Return a PERT-based estimate for one transformation unit."""
        pert = self._pert_estimate(artifact_count)
        est = UnitEstimate(
            unit_id=unit_id,
            artifact_count=artifact_count,
            estimated_seconds=pert.expected_ms / 1000.0,
            estimate_type="historical" if self._compute_pert() else "fallback",
        )
        self._estimates[unit_id] = est
        self._pending[unit_id] = time.monotonic()
        return est

    def start_unit(self, unit_id: str) -> None:
        self._pending[unit_id] = time.monotonic()

    def complete_unit(
        self,
        unit_id: str,
        *,
        completed_count: int,
        total_units: int,
    ) -> tuple[DriftEntry, LiveETA]:
        start_time = self._pending.pop(unit_id, None)
        est = self._estimates.get(unit_id)
        estimated_ms = est.estimated_seconds * 1000.0 if est else 0.0
        actual_ms = (
            (time.monotonic() - start_time) * 1000.0
            if start_time
            else 0.0
        )
        drift_ms = actual_ms - estimated_ms
        pct = abs(drift_ms) / max(estimated_ms, 1.0)
        if pct <= _DRIFT_THRESHOLD_PCT:
            status = DriftStatus.ON_TRACK
        elif actual_ms < estimated_ms:
            status = DriftStatus.AHEAD
        else:
            status = DriftStatus.BEHIND
        self._samples.append(
            _DurationSample(unit_id, estimated_ms, actual_ms, _utc_now())
        )
        if est:
            est.drift_seconds = drift_ms / 1000.0
            est.drift_status = status
            est.completed_at = _utc_now()
        avg_ms = (
            sum(s.actual_ms for s in self._samples[-max(3, completed_count):])
            / max(1, min(3, completed_count))
        )
        remaining = max(0, total_units - completed_count)
        return (
            DriftEntry(
                session_id=self._session_id,
                unit_id=unit_id,
                estimated_ms=estimated_ms,
                actual_ms=actual_ms,
                drift_ms=drift_ms,
                status=status,
            ),
            LiveETA(
                session_id=self._session_id,
                total_units=total_units,
                completed_units=completed_count,
                estimated_remaining_ms=remaining * avg_ms,
                estimated_total_ms=completed_count * avg_ms,
                drift_ms=drift_ms,
                drift_status=status,
            ),
        )

    def live_eta(self, completed_count: int, total_units: int) -> LiveETA:
        avg_ms = (
            sum(s.actual_ms for s in self._samples[-max(3, completed_count):])
            / max(1, min(3, completed_count))
        )
        remaining = max(0, total_units - completed_count)
        return LiveETA(
            session_id=self._session_id,
            total_units=total_units,
            completed_units=completed_count,
            estimated_remaining_ms=remaining * avg_ms,
            estimated_total_ms=completed_count * avg_ms,
            drift_status=DriftStatus.UNKNOWN,
        )


__all__ = [
    "PertEstimate",
    "DriftStatus",
    "UnitEstimate",
    "LiveETA",
    "DriftEntry",
    "ModernizationEstimator",
]