"""
Business-Aware Modernization Models.

Defines the contracts for the business-aware planning gate:
- Requirements (what the business needs)
- BusinessRules (rules extracted from current system / requirements)
- CurrentBehavior (what the existing system does)
- BusinessIntent (what the business wants the system to do)
- TargetBehavior (what the modernized system should do)
- GapFindings (mismatches between current/intent/target)
- FixRecommendations (proposed remediations)
- RecommendationAction (KEEP, MODERNIZE, FIX, REFACTOR, REPLACE, etc.)

This is the core contract for the Planning Layer — it ensures that
transformation is gated by an approved business plan, not by the
transformation engine independently inventing business changes.

Reuses:
- autoforge_workforce: BusinessRule, LegacyEvidence, FactState
- autoforge_models: Artifact (via artifact IDs)
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


# ── Requirement Source / Status ───────────────────────────────────────────────


class RequirementSource(str, Enum):
    """Where a requirement was captured from."""

    STAKEHOLDER = "stakeholder"
    DOCUMENTATION = "documentation"
    INFERRED = "inferred"
    COMPLIANCE = "compliance"
    DERIVED = "derived"


class RequirementStatus(str, Enum):
    """Lifecycle status of a requirement."""

    DRAFT = "draft"
    UNDER_REVIEW = "under_review"
    CONFIRMED = "confirmed"
    AMBIGUOUS = "ambiguous"
    CONFLICTING = "conflicting"
    SUPERSEDED = "superseded"


# ── Recommendation Action ──────────────────────────────────────────────────────




# ── Requirement ──────────────────────────────────────────────────────────────


class Requirement(BaseModel):
    """
    A single business or technical requirement.

    Requirements can come from stakeholders, documentation, inference
    from current behavior, or compliance/regulatory sources. They are
    the canonical input to the business-aware planning gate.
    """

    requirement_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    project_id: str

    title: str
    description: str
    rationale: str = ""

    source: RequirementSource = RequirementSource.STAKEHOLDER
    source_artifact_id: str | None = None
    stakeholder: str | None = None

    status: RequirementStatus = RequirementStatus.DRAFT
    is_ambiguous: bool = False
    ambiguity_reason: str | None = None
    conflicting_with: list[str] = Field(default_factory=list)

    acceptance_criteria: list[str] = Field(default_factory=list)
    verification_method: str = ""

    priority: int = 3
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)

    affected_components: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)

    created_at: datetime = Field(default_factory=_utc_now)
    updated_at: datetime = Field(default_factory=_utc_now)


# ── Current Behavior Model ──────────────────────────────────────────────────


class CurrentBehavior(BaseModel):
    """
    What the existing legacy system actually does.

    This is extracted from analysis of the source code, traces, and
    documentation. Each behavior is evidence-backed.
    """

    behavior_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    project_id: str
    component_id: str

    description: str
    trigger: str = ""
    inputs: list[str] = Field(default_factory=list)
    outputs: list[str] = Field(default_factory=list)
    side_effects: list[str] = Field(default_factory=list)

    error_paths: list[str] = Field(default_factory=list)
    edge_cases: list[str] = Field(default_factory=list)


# ── Business Intent Model ──────────────────────────────────────────────────────


class BusinessIntent(BaseModel):
    """
    What the business wants the system to do.

    This is the contract the target system must satisfy. BusinessIntent
    is the link between Requirements and the target behavior.
    """

    intent_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    project_id: str
    component_id: str

    description: str
    rationale: str = ""

    requirement_ids: list[str] = Field(default_factory=list)
    stakeholder: str | None = None

    is_resolved: bool = True
    resolution_notes: str = ""
    blocking_question: str | None = None

    acceptance_criteria: list[str] = Field(default_factory=list)

    confidence: float = Field(default=0.0, ge=0.0, le=1.0)

    created_at: datetime = Field(default_factory=_utc_now)
    updated_at: datetime = Field(default_factory=_utc_now)


# ── Target Behavior Model ──────────────────────────────────────────────────────


class TargetBehavior(BaseModel):
    """What the modernized system should do."""

    target_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    project_id: str
    component_id: str

    description: str
    rationale: str = ""

    intent_id: str | None = None
    current_behavior_id: str | None = None

    inputs: list[str] = Field(default_factory=list)
    outputs: list[str] = Field(default_factory=list)
    side_effects: list[str] = Field(default_factory=list)
    invariants: list[str] = Field(default_factory=list)

    verification_requirements: list[str] = Field(default_factory=list)
    acceptance_criteria: list[str] = Field(default_factory=list)

    suggested_target_language: str | None = None
    suggested_target_framework: str | None = None
    suggested_target_architecture: str | None = None

    confidence: float = Field(default=0.0, ge=0.0, le=1.0)

    created_at: datetime = Field(default_factory=_utc_now)


# ── Gap Finding ──────────────────────────────────────────────────────────────


class RecommendationAction(str, Enum):
    KEEP = "keep"
    MODERNIZE = "modernize"
    FIX = "fix"
    REFACTOR = "refactor"
    REPLACE = "replace"
    RE_ARCHITECT = "re_architect"
    REMOVE = "remove"
    DEFER = "defer"
    REVIEW_REQUIRED = "review_required"


class GapSeverity(str, Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"


class ApprovalState(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    NEEDS_INFO = "needs_info"


class GapFinding(BaseModel):
    """A finding of mismatch between current behavior, business intent, and target behavior.

    This is the central artifact of the planning gate. A finding can be:
    - Current behavior violates business intent
    - Business intent is ambiguous
    - Target behavior is unclear
    - Conflicting business rules
    """

    finding_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    project_id: str
    component_id: str

    finding_type: str
    severity: GapSeverity = GapSeverity.MEDIUM

    current_behavior_id: str | None = None
    business_intent_id: str | None = None
    target_behavior_id: str | None = None
    rule_id: str | None = None

    title: str
    description: str
    impact: str = ""

    evidence_ids: list[str] = Field(default_factory=list)

    approval_state: ApprovalState = ApprovalState.PENDING
    approved_by: str | None = None
    approved_at: datetime | None = None
    rejection_reason: str | None = None

    discovered_at: datetime = Field(default_factory=_utc_now)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)


# ── Fix Recommendation ──────────────────────────────────────────────────────


class FixRecommendation(BaseModel):
    """
    A proposed remediation for a gap finding.

    Each recommendation is actioned, evidence-backed, and has an
    explicit approval state before transformation can proceed.
    """

    recommendation_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    project_id: str
    gap_id: str  # References the GapFinding

    action: RecommendationAction
    description: str

    affected_components: list[str] = Field(default_factory=list)

    effort_estimate_tokens: int | None = None
    estimated_loc_change: int | None = None

    risk: str = "medium"
    priority: int = 3

    verification_requirements: list[str] = Field(default_factory=list)

    dependencies: list[str] = Field(default_factory=list)

    confidence: float = Field(default=0.0, ge=0.0, le=1.0)

    approval_state: ApprovalState = ApprovalState.PENDING
    approved_by: str | None = None
    approved_at: datetime | None = None
    rejection_reason: str | None = None

    evidence_ids: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=_utc_now)


class BusinessRuleReference(BaseModel):
    reference_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    project_id: str
    rule_id: str
    component_id: str
    role: str = "constraint"
    evidence_ids: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    captured_at: datetime = Field(default_factory=_utc_now)


__all__ = [
    "RequirementSource",
    "RequirementStatus",
    "RecommendationAction",
    "GapSeverity",
    "ApprovalState",
    "Requirement",
    "CurrentBehavior",
    "BusinessIntent",
    "TargetBehavior",
    "GapFinding",
    "FixRecommendation",
    "BusinessRuleReference",
]
