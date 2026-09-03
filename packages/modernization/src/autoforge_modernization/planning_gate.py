"""
Business-Aware Planning Gate.

The planning gate is the mandatory decision point before mutation (transformation).
The gate ensures that requirements are confirmed, business rules resolved,
current behavior modeled, business intent resolved, gap findings approved,
fix recommendations approved, capability gaps resolved, and HITL applied.

The modernization lifecycle is NOT: reconnaissance → rewrite → verify.
It IS: reconnaissance → analysis → research → requirements → behavior modeling →
intent modeling → gap analysis → recommendations → governance → transformation.

Transformation is BLOCKED until all gate conditions are satisfied.
This module defines the gate state, rules, and the gate decision record.

Reuses:
- business: Requirement, GapFinding, FixRecommendation, BusinessIntent,
  CurrentBehavior, TargetBehavior, ApprovalState
- capability_gap: CapabilityGapReport
- jobs: ModernizationJob, ModernizationPhase, GateState
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class GateConditionKind(str, Enum):
    """The type of gate condition being evaluated."""

    REQUIREMENTS_CONFIRMED = "requirements_confirmed"
    BUSINESS_RULES_RESOLVED = "business_rules_resolved"
    CURRENT_BEHAVIOR_MODELED = "current_behavior_modeled"
    BUSINESS_INTENT_RESOLVED = "business_intent_resolved"
    GAP_FINDINGS_APPROVED = "gap_findings_approved"
    FIX_RECOMMENDATIONS_APPROVED = "fix_recommendations_approved"
    CAPABILITY_GAPS_RESOLVED = "capability_gaps_resolved"
    HITL_GOVERNANCE_APPLIED = "hitl_governance_applied"
    PLANNING_GATE_MANUAL = "planning_gate_manual"


class GateConditionStatus(str, Enum):
    """Status of a single gate condition."""

    NOT_APPLICABLE = "not_applicable"
    PENDING = "pending"
    SATISFIED = "satisfied"
    BLOCKED = "blocked"
    WAIVED = "waived"


class GateCondition(BaseModel):
    """A single condition that must be satisfied before the gate opens."""

    condition_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    kind: GateConditionKind
    description: str

    # Status / state-machine fields
    status: GateConditionStatus = GateConditionStatus.PENDING
    blocking_reason: str | None = None
    blocking_finding_ids: list[str] = Field(default_factory=list)
    blocking_requirement_ids: list[str] = Field(default_factory=list)

    # Satisfaction
    satisfied_by: str | None = None
    satisfied_at: datetime | None = None

    # Waiver
    waived_by: str | None = None
    waiver_reason: str | None = None

    # HITL
    required_approvers: list[str] = Field(default_factory=list)
    is_hitl_required: bool = False

    def is_satisfied(self) -> bool:
        return self.status == GateConditionStatus.SATISFIED

    def is_blocked(self) -> bool:
        return self.status == GateConditionStatus.BLOCKED



class GateDecision(str, Enum):
    """Outcome of a gate evaluation."""

    APPROVED = "approved"
    BLOCKED = "blocked"
    WAIVED = "waived"
    PENDING = "pending"


class GateDecisionRecord(BaseModel):
    """
    The complete decision record for a planning gate evaluation.

    This is the authoritative record that the transformation engine
    MUST check before proceeding. No transformation without approval.
    """

    decision_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    project_id: str
    wave_index: int | None = None

    decision: GateDecision = GateDecision.PENDING
    evaluated_at: datetime = Field(default_factory=_utc_now)

    conditions: list[GateCondition] = Field(default_factory=list)
    blocked_conditions: list[GateCondition] = Field(default_factory=list)

    total_conditions: int = 0
    satisfied_count: int = 0
    blocked_count: int = 0

    hitl_required: bool = False
    hitl_approved: bool = False
    hitl_approver: str | None = None
    hitl_approved_at: datetime | None = None

    governance_report_id: str | None = None
    decision_notes: str = ""
    decided_by: str = "autoforge-gate"

    def evaluate(self) -> GateDecision:
        """Re-evaluate all conditions and return a decision."""
        self.blocked_conditions = [c for c in self.conditions if c.is_blocked()]
        self.satisfied_count = sum(1 for c in self.conditions if c.is_satisfied())
        self.blocked_count = len(self.blocked_conditions)
        self.total_conditions = len(self.conditions)

        if self.hitl_required and not self.hitl_approved:
            self.decision = GateDecision.BLOCKED
            return self.decision

        if self.blocked_count > 0:
            self.decision = GateDecision.BLOCKED
            return self.decision

        if all(
            c.is_satisfied() or c.status == GateConditionStatus.NOT_APPLICABLE
            for c in self.conditions
        ):
            self.decision = GateDecision.APPROVED
            return self.decision

        self.decision = GateDecision.PENDING
        return self.decision

    def get_blocked_reasons(self) -> list[str]:
        """Return the blocking reasons for all blocked conditions."""
        return [
            f"[{c.kind.value}] {c.blocking_reason or 'unknown'}"
            for c in self.blocked_conditions
        ]
