"""
Migration Units and Waves.

Defines the atomic unit of transformation (MigrationUnit) and the
wave-based grouping (MigrationWave) used by the transformation engine.

A MigrationUnit is a single, addressable, verifiable piece of work.
A MigrationWave is a group of units executed together (with a single
gate decision, single batch verification, and single checkpoint).

Reuses:
- strategy: MigrationStrategy, MigrationUnitSpec
- checkpoints: ModernizationCheckpoint (defined in checkpoints.py)
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

from autoforge_modernization.strategy import MigrationStrategy, MigrationUnitSpec


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


# ── Unit / Wave Status ──────────────────────────────────────────────────────────


class UnitStatus(str, Enum):
    """Status of a single migration unit during execution."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    AWAITING_VERIFICATION = "awaiting_verification"
    VERIFIED = "verified"
    FAILED = "failed"
    SKIPPED = "skipped"
    BLOCKED = "blocked"  # Capability gap or HITL


class WaveStatus(str, Enum):
    """Status of a migration wave."""

    PENDING = "pending"
    AT_GATE = "at_gate"  # Waiting for gate decision
    EXECUTING = "executing"
    VERIFYING = "verifying"
    COMPLETE = "complete"
    PARTIAL = "partial"  # Some units failed
    FAILED = "failed"
    CANCELLED = "cancelled"


# ── Migration Unit (execution instance) ──────────────────────────────────────


class MigrationUnit(BaseModel):
    """
    An executable instance of a migration unit during execution.

    This is distinct from MigrationUnitSpec (the plan-time spec). At
    execution time, each spec becomes a MigrationUnit with state.
    """

    unit_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    spec_id: str  # References the MigrationUnitSpec
    wave_id: str
    project_id: str
    job_id: str

    # Component
    component_id: str
    strategy: MigrationStrategy

    # Execution state
    status: UnitStatus = UnitStatus.PENDING
    started_at: datetime | None = None
    finished_at: datetime | None = None

    # Retries
    attempt_count: int = 0
    max_attempts: int = 3

    # Verification
    verification_passed: bool = False
    verification_report_id: str | None = None
    verification_failures: list[str] = Field(default_factory=list)

    # Outputs
    transformation_artifact_ids: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)

    # Errors
    last_error: str | None = None
    error_history: list[str] = Field(default_factory=list)

    # Risk
    risk_level: str = "medium"

    # LOC
    estimated_loc: int | None = None
    actual_loc_changed: int | None = None

    # Dependencies
    depends_on: list[str] = Field(default_factory=list)  # Other unit_ids

    def is_terminal(self) -> bool:
        """Return True if the unit is in a terminal state."""
        return self.status in (
            UnitStatus.VERIFIED,
            UnitStatus.FAILED,
            UnitStatus.SKIPPED,
        )

    def can_start(self, completed_units: set[str]) -> bool:
        """Return True if all dependencies are satisfied."""
        return all(d in completed_units for d in self.depends_on)

    def record_attempt(self, error: str | None = None) -> None:
        """Record an execution attempt."""
        self.attempt_count += 1
        if error:
            self.error_history.append(error)
            self.last_error = error


# ── Migration Wave (execution batch) ────────────────────────────────────────


class MigrationWave(BaseModel):
    """
    A group of migration units executed together.

    Each wave has:
    - A single gate decision
    - A single batch verification
    - A single checkpoint
    - A clear dependency order between waves
    """

    wave_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    project_id: str
    job_id: str
    wave_index: int

    name: str
    description: str = ""

    # Units in this wave
    unit_ids: list[str] = Field(default_factory=list)
    unit_count: int = 0

    # Wave ordering
    depends_on_waves: list[int] = Field(default_factory=list)

    # Execution state
    status: WaveStatus = WaveStatus.PENDING
    started_at: datetime | None = None
    finished_at: datetime | None = None

    # Gate state (references the planning gate decision)
    gate_decision_id: str | None = None
    gate_approved: bool = False

    # Checkpoint
    checkpoint_id: str | None = None

    # LOC accounting
    estimated_loc: int = 0
    actual_loc_processed: int = 0

    # Success / failure
    units_completed: int = 0
    units_failed: int = 0
    units_skipped: int = 0

    # Throughput
    throughput_loc_per_hour: float = 0.0
    started_processing_at: datetime | None = None
    last_checkpoint_at: datetime | None = None

    # Risk
    risk_level: str = "medium"

    def is_complete(self) -> bool:
        return self.status in (WaveStatus.COMPLETE, WaveStatus.PARTIAL, WaveStatus.FAILED, WaveStatus.CANCELLED)

    def progress_percentage(self) -> float:
        if self.unit_count == 0:
            return 0.0
        return (self.units_completed / self.unit_count) * 100.0
