"""
Migration Strategy and Plan Models.

Defines the canonical 6 R's of migration (retain, rehost, replatform,
refactor, rewrite, replace) and the migration plan structure that
binds them to the components being modernized.

The MigrationPlan is the authoritative artifact produced by the
StrategyEngine (G.2) and consumed by the TransformationEngine (G.3).
A plan is GATED by the PlanningGate (G.1 contract).

Reuses:
- business: FixRecommendation, RecommendationAction
- units: MigrationUnit (defined in units.py)
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class MigrationStrategy(str, Enum):
    """The 6 R's of migration (plus RETIRE)."""

    RETAIN = "retain"
    """Keep the legacy system as-is. No change required."""

    REHOST = "rehost"
    """Lift-and-shift to new infrastructure. No code change."""

    REPLATFORM = "replatform"
    """Move to new runtime with minimal code change."""

    REFACTOR = "refactor"
    """Restructure code without changing external behavior."""

    REWRITE = "rewrite"
    """Replace legacy code with new implementation."""

    REPLACE = "replace"
    """Replace with commercial off-the-shelf product or service."""

    RE_ARCHITECT = "re_architect"
    """Fundamental architectural change (e.g., monolith to microservices)."""

    RETIRE = "retire"
    """Decommission. Remove the system."""


class PlanStatus(str, Enum):
    """Status of a migration plan."""

    DRAFT = "draft"
    UNDER_REVIEW = "under_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXECUTING = "executing"
    COMPLETE = "complete"
    FAILED = "failed"


class StrategyJustification(BaseModel):
    """Justification for choosing a particular strategy for a component."""

    component_id: str
    strategy: MigrationStrategy
    rationale: str
    alternatives_considered: list[MigrationStrategy] = Field(default_factory=list)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    evidence_ids: list[str] = Field(default_factory=list)
    selected_by: str = "autoforge-strategy"
    selected_at: datetime = Field(default_factory=_utc_now)


class MigrationUnitSpec(BaseModel):
    """
    Specification of a single migration unit within a plan.

    Each unit is an atomic, addressable, verifiable piece of work.
    """

    unit_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    wave_id: str  # References the wave this unit belongs to
    component_id: str

    strategy: MigrationStrategy
    description: str

    # Source / target
    source_technology: str | None = None  # Discovered source technology (from G.2/G.3)
    source_language: str | None = None  # Optional override of detected source

    # Boundaries
    source_files: list[str] = Field(default_factory=list)
    target_files: list[str] = Field(default_factory=list)
    dependencies: list[str] = Field(default_factory=list)  # Other unit_ids

    # Targets
    target_language: str | None = None
    target_framework: str | None = None
    target_architecture: str | None = None

    # Effort
    estimated_loc: int | None = None
    estimated_effort_hours: float | None = None
    estimated_risk: str = "medium"

    # Verification requirements
    verification_requirements: list[str] = Field(default_factory=list)

    # Approval
    approved: bool = False
    approved_by: str | None = None
    approved_at: datetime | None = None


class MigrationPlan(BaseModel):
    """
    The authoritative migration plan.

    A MigrationPlan is the gate output — it represents the approved
    strategy for modernizing the project. The TransformationEngine (G.3)
    consumes this plan, not the legacy system directly.
    """

    plan_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    project_id: str

    name: str
    description: str = ""

    # Strategy decisions
    strategy_justifications: list[StrategyJustification] = Field(default_factory=list)
    strategy_summary: dict[str, int] = Field(default_factory=dict)  # strategy -> count

    # Migration units
    units: list[MigrationUnitSpec] = Field(default_factory=list)
    total_units: int = 0

    # Status and approval
    status: PlanStatus = PlanStatus.DRAFT
    approved: bool = False
    approved_by: str | None = None
    approved_at: datetime | None = None

    # Provenance
    based_on_findings: list[str] = Field(default_factory=list)  # gap finding IDs
    based_on_recommendations: list[str] = Field(default_factory=list)
    based_on_requirements: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    rag_query_ids: list[str] = Field(default_factory=list)

    # Governance
    governance_report_id: str | None = None
    hitl_required: bool = True  # Default: modernization plans require HITL
    hitl_approved: bool = False

    # Effort summary
    total_estimated_loc: int = 0
    total_estimated_hours: float = 0.0

    # Risk
    overall_risk: str = "medium"
    risk_factors: list[str] = Field(default_factory=list)

    # Lifecycle
    created_at: datetime = Field(default_factory=_utc_now)
    updated_at: datetime = Field(default_factory=_utc_now)

    def is_executable(self) -> bool:
        """Return True if the plan can be executed."""
        return (
            self.status == PlanStatus.APPROVED
            and self.approved
            and (not self.hitl_required or self.hitl_approved)
        )

    def units_by_strategy(self) -> dict[MigrationStrategy, list[MigrationUnitSpec]]:
        """Group units by strategy."""
        result: dict[MigrationStrategy, list[MigrationUnitSpec]] = {}
        for u in self.units:
            result.setdefault(u.strategy, []).append(u)
        return result

    def units_by_wave(self) -> dict[str, list[MigrationUnitSpec]]:
        """Group units by wave."""
        result: dict[str, list[MigrationUnitSpec]] = {}
        for u in self.units:
            result.setdefault(u.wave_id, []).append(u)
        return result
