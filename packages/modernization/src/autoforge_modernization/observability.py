"""
Modernization Observability Dashboard Contract.

Establishes the data model and event contracts for the dedicated
Legacy Modernization observability dashboard. The dashboard must
display: JOB (status, phase, wave, component), TIME (elapsed, ETA, checkpoints),
PROGRESS (LOC, files, modules), HEALTH (successes, failures, blockers),
CHECKPOINT (resume position).

The architecture supports RESUME FROM LAST CHECKPOINT without restarting.
This is the G.1 contract. Actual dashboard rendering belongs to later stages.

Reuses:
- autoforge_observability: DashboardManager, MetricObservation
- jobs: ModernizationJob
- units: MigrationWave, MigrationUnit
- estimation: ProjectEstimate
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)



class ModernizationDashboardJob(BaseModel):
    """Job section of the modernization dashboard."""

    job_id: str
    project_id: str
    name: str
    status: str
    current_phase: str
    current_wave_id: str | None = None
    current_unit_id: str | None = None
    current_component_id: str | None = None
    current_module: str | None = None
    current_file: str | None = None
    current_operation: str | None = None


class ModernizationDashboardTime(BaseModel):
    """Time section of the modernization dashboard."""

    start_time: datetime | None = None
    elapsed_seconds: float = 0.0
    last_checkpoint_at: datetime | None = None
    eta: datetime | None = None
    estimated_completion_at: datetime | None = None
    is_running: bool = False


class ModernizationDashboardProgress(BaseModel):
    """Progress section of the modernization dashboard."""

    total_loc: int = 0
    processed_loc: int = 0
    remaining_loc: int = 0
    loc_per_hour: float = 0.0
    loc_per_day: float = 0.0

    files_total: int = 0
    files_processed: int = 0
    files_remaining: int = 0

    modules_total: int = 0
    modules_completed: int = 0
    modules_remaining: int = 0

    percentage_complete: float = 0.0


class ModernizationDashboardHealth(BaseModel):
    """Health section of the modernization dashboard."""

    successes: int = 0
    failures: int = 0
    skipped: int = 0
    blocked: int = 0
    retries: int = 0

    verification_passed: int = 0
    verification_failed: int = 0

    unresolved_findings: int = 0
    open_capability_gaps: int = 0
    open_business_intent_gaps: int = 0

    risk_level: str = "medium"


class ModernizationDashboardCheckpoint(BaseModel):
    """Checkpoint section of the modernization dashboard."""

    last_checkpoint_id: str | None = None
    last_checkpoint_at: datetime | None = None
    current_unit_id: str | None = None
    last_successful_action: str | None = None
    last_failure_reason: str | None = None
    evidence_ids: list[str] = Field(default_factory=list)

    can_resume_from_checkpoint: bool = False
    resume_blocker: str | None = None


class ModernizationDashboard(BaseModel):
    """
    The complete modernization dashboard read model.

    This is the consolidated dashboard view for a modernization job.
    The actual rendering belongs to the UI; this is the data contract.
    """

    dashboard_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    job_id: str
    project_id: str
    generated_at: datetime = Field(default_factory=_utc_now)

    job: ModernizationDashboardJob
    time: ModernizationDashboardTime = Field(default_factory=ModernizationDashboardTime)
    progress: ModernizationDashboardProgress = Field(default_factory=ModernizationDashboardProgress)
    health: ModernizationDashboardHealth = Field(default_factory=ModernizationDashboardHealth)
    checkpoint: ModernizationDashboardCheckpoint = Field(default_factory=ModernizationDashboardCheckpoint)

    operating_mode: str = "normal"
    lockdown_active: bool = False


# ── Event Contracts ────────────────────────────────────────────────────────────


class ModernizationEventType(str, Enum):
    """Event types emitted by the modernization engine."""

    PHASE_ADVANCED = "modernization.phase_advanced"
    WAVE_STARTED = "modernization.wave_started"
    WAVE_COMPLETE = "modernization.wave_complete"
    UNIT_STARTED = "modernization.unit_started"
    UNIT_COMPLETE = "modernization.unit_complete"
    UNIT_FAILED = "modernization.unit_failed"
    CHECKPOINT_CREATED = "modernization.checkpoint_created"
    CAPABILITY_GAP_DETECTED = "modernization.capability_gap_detected"
    CAPABILITY_GAP_RESOLVED = "modernization.capability_gap_resolved"
    GATE_DECISION = "modernization.gate_decision"
    FINDING_APPROVED = "modernization.finding_approved"
    FINDING_REJECTED = "modernization.finding_rejected"
    LOCKDOWN_ENABLED = "modernization.lockdown_enabled"
    LOCKDOWN_DISABLED = "modernization.lockdown_disabled"


class ModernizationEvent(BaseModel):
    """
    An event emitted by the modernization engine.

    Subscribers (observability, audit, etc.) consume these via
    the canonical event bus (autoforge_events).
    """

    event_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    event_type: ModernizationEventType
    project_id: str
    job_id: str | None = None
    unit_id: str | None = None
    timestamp: datetime = Field(default_factory=_utc_now)

    payload: dict[str, Any] = Field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialize for event bus transport."""
        return {
            "event_id": self.event_id,
            "event_type": self.event_type.value,
            "project_id": self.project_id,
            "job_id": self.job_id,
            "unit_id": self.unit_id,
            "timestamp": self.timestamp.isoformat(),
            "payload": self.payload,
        }
