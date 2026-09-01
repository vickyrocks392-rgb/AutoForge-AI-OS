"""
Modernization Job, Project, and State models.

These are the top-level containers for modernization work. They track
overall project lifecycle, current phase, and governance state.

Reuses:
- autoforge_models: Project (canonical project model)
- autoforge_workforce: LegacySystemModel, LegacyEvidence (existing workforce models)
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


# ── Phase / Status ──────────────────────────────────────────────────────────


class ModernizationPhase(str, Enum):
    """
    Lifecycle phases of a modernization job.

    These map to the workflow stages defined in LEGACY_WORKFLOW_DEFINITION.
    G.1 establishes the contract; later stages implement actual execution.
    """

    INTAKE = "intake"
    RECONNAISSANCE = "reconnaissance"
    TECHNICAL_ANALYSIS = "technical_analysis"
    RESEARCH_RAG = "research_rag"
    BUSINESS_RULES = "business_rules"
    CURRENT_BEHAVIOR_MODEL = "current_behavior_model"
    BUSINESS_INTENT_MODEL = "business_intent_model"
    GAP_ANALYSIS = "gap_analysis"
    FIX_RECOMMENDATIONS = "fix_recommendations"
    TARGET_PLAN = "target_plan"
    GOVERNANCE_REVIEW = "governance_review"
    PLANNING_GATE = "planning_gate"
    TRANSFORMATION = "transformation"

    BLOCKED = "blocked"


class JobStatus(str, Enum):
    """High-level status of a modernization job."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    AT_GATE = "at_gate"
    COMPLETE = "complete"
    FAILED = "failed"
    CANCELLED = "cancelled"


class GateState(str, Enum):
    """State of a planning gate for a migration wave."""

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    BLOCKED_HITL = "blocked_hitl"
    BLOCKED_CAPABILITY = "blocked_capability"
    BLOCKED_BUSINESS_INTENT = "blocked_business_intent"


# ── Lockdown State ──────────────────────────────────────────────────────────
# ── Lockdown State ──────────────────────────────────────────────────────────


class OperatingMode(str, Enum):
    """Operating mode of the modernization engine."""

    NORMAL = "normal"
    """All features enabled including web research when requested."""

    LOCKDOWN = "lockdown"
    """
    No external network access. Only local models, local Qdrant,
    local tooling, local artifacts, local persistence.
    """


class LockdownState(BaseModel):
    """
    Current lockdown configuration and enforcement state.

    When enabled, this blocks all external network operations and
    restricts the engine to local resources only.
    """

    enabled: bool = False
    enforced_at: datetime | None = None
    enforced_by: str | None = None  # "user" | "policy" | "error"
    reason: str = ""

    network_access_blocked: bool = False
    web_research_enabled: bool = True
    competitor_research_enabled: bool = True
    market_research_enabled: bool = True
    local_models_only: bool = False
    local_rag_only: bool = False
    local_artifacts_only: bool = False

    def enable(self, enforced_by: str = "user", reason: str = "") -> None:
        """Enable lockdown mode."""
        self.enabled = True
        self.enforced_at = _utc_now()
        self.enforced_by = enforced_by
        self.reason = reason
        self.network_access_blocked = True
        self.web_research_enabled = False
        self.competitor_research_enabled = False
        self.market_research_enabled = False
        self.local_models_only = True
        self.local_rag_only = True
        self.local_artifacts_only = True

    def disable(self) -> None:
        """Disable lockdown mode."""
        self.enabled = False
        self.enforced_at = None
        self.enforced_by = None
        self.reason = ""
        self.network_access_blocked = False
        self.web_research_enabled = True
        self.competitor_research_enabled = True
        self.market_research_enabled = True
        self.local_models_only = False
        self.local_rag_only = False
        self.local_artifacts_only = False


# ── Modernization Job ────────────────────────────────────────────────────────


class ModernizationJob(BaseModel):
    """
    Top-level container for a single modernization project.

    A job represents the complete lifecycle from intake to completion.
    It contains the project metadata, current phase, job status,
    and references to all artifacts produced during the modernization.
    """

    job_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    project_id: str  # Reference to canonical autoforge_models.Project.project_id
    name: str
    description: str = ""

    # Lifecycle state
    status: JobStatus = JobStatus.PENDING
    current_phase: ModernizationPhase = ModernizationPhase.INTAKE
    phase_started_at: datetime = Field(default_factory=_utc_now)
    completed_phases: list[ModernizationPhase] = Field(default_factory=list)

    # Lockdown
    operating_mode: OperatingMode = OperatingMode.NORMAL

    # Gate state per wave (wave_index -> gate state)
    wave_gate_states: dict[int, GateState] = Field(default_factory=dict)

    # Artifact references (produced by earlier phases; consumed by later phases)
    legacy_system_model_id: str | None = None
    technology_inventory_id: str | None = None
    business_rules_artifact_id: str | None = None
    current_behavior_model_id: str | None = None
    business_intent_model_id: str | None = None
    gap_analysis_id: str | None = None
    fix_recommendations_id: str | None = None
    migration_plan_id: str | None = None
    governance_report_id: str | None = None

    # Provenance chain
    evidence_ids: list[str] = Field(default_factory=list)
    provenance_chain: list[str] = Field(default_factory=list)

    # Error tracking
    last_error: str | None = None
    last_error_at: datetime | None = None

    created_at: datetime = Field(default_factory=_utc_now)
    updated_at: datetime = Field(default_factory=_utc_now)

    # Free-form metadata
    metadata: dict[str, Any] = Field(default_factory=dict)

    def advance_phase(self, next_phase: ModernizationPhase) -> None:
        """Advance to the next phase, recording the completed one."""
        self.completed_phases.append(self.current_phase)
        self.current_phase = next_phase
        self.phase_started_at = _utc_now()
        self.updated_at = _utc_now()

    def is_blocked_at_gate(self) -> bool:
        """Return True if the job is blocked at a planning gate."""
        return self.current_phase == ModernizationPhase.PLANNING_GATE and any(
            s in (
                GateState.BLOCKED_HITL,
                GateState.BLOCKED_CAPABILITY,
                GateState.BLOCKED_BUSINESS_INTENT,
            )
            for s in self.wave_gate_states.values()
        )

    def record_error(self, error_message: str) -> None:
        """Record a job-level error."""
        self.last_error = error_message
        self.last_error_at = _utc_now()
        self.updated_at = _utc_now()


class JobStatus(str, Enum):
    """High-level status of a modernization job."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    AT_GATE = "at_gate"
    COMPLETE = "complete"
    FAILED = "failed"
    CANCELLED = "cancelled"


class GateState(str, Enum):
    """State of a planning gate for a migration wave."""

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    BLOCKED_HITL = "blocked_hitl"
    BLOCKED_CAPABILITY = "blocked_capability"
    BLOCKED_BUSINESS_INTENT = "blocked_business_intent"
