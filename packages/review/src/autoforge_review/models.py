"""Review Platform domain models — Phase 11.

Defines the review value objects, enums, finding, evidence, quality off, results,
and repair hand-off used across the Review Engine, Review Policies, Specialized
Reviewers, and Quality Gates.

Design rules
------------
- Review is a QUALITY CONTROL subsystem: it consumes existing evidence
  (artifacts, evaluations, diffs, provenance) and NEVER creates a second
  artifact / execution / event system.
- Findings are structured, reproducible, and traceable (section 14).
- Severity is a deterministic model (section 15); the LLM may recommend but
  the Policy finalizes classification.
- Quality gates are only PASS / FAIL / BLOCKED / REQUIRES_HITL (section 16).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

# Existing Phase 3 execution contracts reused as-is (reuse over reinvent).
from autoforge_execution.models import (
    CommandResult,
    DiagnosisReport,
    EvaluationResult,
    TestResultSummary,
)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _new_uuid() -> uuid.UUID:
    return uuid.uuid4()


# ── Enumerations ───────────────────────────────────────────────────────────


class ReviewCategory(str, Enum):
    """The five canonical review domains (sections 8, 30)."""

    ARCHITECTURE = "architecture"
    CODE = "code"
    SECURITY = "security"
    PERFORMANCE = "performance"
    DOCUMENTATION = "documentation"


class Severity(str, Enum):
    """Deterministic severity. An LLM may recommend but never redefine."""

    INFO = "info"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


_SEVERITY_RANK: dict[Severity, int] = {
    Severity.INFO: 0,
    Severity.LOW: 1,
    Severity.MEDIUM: 2,
    Severity.HIGH: 3,
    Severity.CRITICAL: 4,
}


def severity_rank(severity: Severity) -> int:
    """Deterministic ordinal rank of a severity."""
    return _SEVERITY_RANK[severity]


def is_at_least(*, severity: Severity, threshold: Severity) -> bool:
    """True when ``severity`` is at least as serious as ``threshold``."""
    return severity_rank(severity) >= severity_rank(threshold)


class FindingClassification(str, Enum):
    """Whether a finding came from deterministic rules or AI reasoning."""

    DETERMINISTIC = "deterministic"
    AI_ASSISTED = "ai_assisted"


class FindingKind(str, Enum):
    """Machine-readable finding kind supporting governance and future workers.

    Stable across future surfaces (section 20): BACKEND findings, SECURITY
    findings etc. are routable by category — workers are never hardcoded here.
    """

    DEFECT = "defect"
    POLICY_VIOLATION = "policy_violation"
    SECURITY_VULNERABILITY = "security_vulnerability"
    SECURITY_EXCEPTION = "security_exception"
    ARCHITECTURE_EXCEPTION = "architecture_exception"
    TECH_STACK_FINALIZATION = "tech_stack_finalization"
    PERFORMANCE_REGRESSION = "performance_regression"
    DOCUMENTATION_GAP = "documentation_gap"
    QUALITY = "quality_issue"


# ── AI / provenance metadata ───────────────────────────────────────────────


class AISourceMetadata(BaseModel):
    """Record of an AI-reasoning call so AI-assisted review is reproducible.

    Satisfies section 32: model/provider abstraction identity, capability,
    routing policy, prompt version, and execution status are recorded.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    capability_id: str | None = Field(default=None)
    provider_id: str | None = Field(default=None)
    model_id: str | None = Field(default=None)
    routing_policy: str | None = Field(default=None)
    prompt_version: str | None = Field(default=None)
    executed: bool = Field(default=False)
    error_message: str | None = Field(default=None)


class FindingProvenance(BaseModel):
    """Provenance + correlation metadata on every finding."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    policy_version: str = Field(default="1.0.0")
    rule_id: str | None = Field(default=None)
    ai_source: AISourceMetadata | None = Field(default=None)
    review_id: str | None = Field(default=None)
    correlation_id: uuid.UUID | None = Field(default=None)


# ── Finding ────────────────────────────────────────────────────────────────


class ReviewFinding(BaseModel):
    """A single structured review finding (section 14)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    finding_id: uuid.UUID = Field(default_factory=_new_uuid)
    review_id: str = Field(default="")
    category: ReviewCategory = Field(...)
    severity: Severity = Field(...)
    title: str = Field(..., min_length=1)
    description: str = Field(default="")
    evidence: list[str] = Field(default_factory=list)
    source_artifact: str | None = Field(default=None)
    file: str | None = Field(default=None)
    start_line: int | None = Field(default=None, ge=1)
    end_line: int | None = Field(default=None, ge=1)
    classification: FindingClassification = Field(
        default=FindingClassification.DETERMINISTIC,
    )
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    blocking: bool = Field(default=False)
    kind: FindingKind = Field(default=FindingKind.DEFECT)
    requires_hitl: bool = Field(default=False)
    remediation: str = Field(default="")
    provenance: FindingProvenance | None = Field(default=None)
    correlation_id: uuid.UUID | None = Field(default=None)

    @property
    def is_deterministic(self) -> bool:
        return self.classification == FindingClassification.DETERMINISTIC


# ── Evidence ───────────────────────────────────────────────────────────────


class ReviewEvidence(BaseModel):
    """Evidence bundle consumed by a review (reuse existing contracts)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    source_files: dict[str, str] = Field(default_factory=dict)
    changed_files: list[str] = Field(default_factory=list)
    diff: str = Field(default="")
    test_results: TestResultSummary | None = Field(default=None)
    evaluation: EvaluationResult | None = Field(default=None)
    command_results: list[CommandResult] = Field(default_factory=list)
    diagnostics: list[DiagnosisReport] = Field(default_factory=list)
    artifact_ids: list[str] = Field(default_factory=list)
    build_exit_code: int | None = Field(default=None)
    stdout: str = Field(default="")
    stderr: str = Field(default="")
    metrics: dict[str, float] = Field(default_factory=dict)

    @property
    def review_files(self) -> dict[str, str]:
        """Source files relevant to the review (changed files when known)."""
        if not self.changed_files:
            return dict(self.source_files)
        return {p: c for p, c in self.source_files.items() if p in self.changed_files}


# ── Request & Result ───────────────────────────────────────────────────────


class ReviewRequest(BaseModel):
    """A review request submitted to the Review Engine (section 5)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    review_id: str = Field(default_factory=lambda: str(_new_uuid()))
    project_id: uuid.UUID | None = Field(default=None)
    workflow_id: uuid.UUID | None = Field(default=None)
    task_id: str | None = Field(default=None)
    execution_id: str | None = Field(default=None)
    worker_id: str | None = Field(default=None)
    attempt_number: int = Field(default=1, ge=1)
    correlation_id: uuid.UUID | None = Field(default=None)

    #: Requested categories. Empty means the policy's enabled categories are used.
    categories: frozenset[ReviewCategory] = Field(default_factory=frozenset)

    evidence: ReviewEvidence = Field(default_factory=ReviewEvidence)
    policy_version: str | None = Field(default=None)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @property
    def has_scope(self) -> bool:
        return self.categories != frozenset()
# ── Quality gates & decision ───────────────────────────────────────────────


class GateStatus(str, Enum):
    """Deterministic review quality-gate outcome (section 16)."""

    PASS = "pass"
    FAIL = "fail"
    BLOCKED = "blocked"
    REQUIRES_HITL = "requires_hitl"


class QualityGateResult(BaseModel):
    """Outcome of the deterministic quality gate."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    status: GateStatus = Field(...)
    reasons: list[str] = Field(default_factory=list)
    satisfied_gates: list[str] = Field(default_factory=list)
    violated_gates: list[str] = Field(default_factory=list)

    @property
    def passed(self) -> bool:
        return self.status == GateStatus.PASS


class ReviewDecision(str, Enum):
    """Final human-readable review decision."""

    APPROVED = "approved"
    REJECTED = "rejected"
    CHANGES_REQUESTED = "changes_requested"
    REQUIRES_HITL = "requires_hitl"


# ── Repair hand-off (section 18) ───────────────────────────────────────────


class RepairRequest(BaseModel):
    """Structured hand-off from Review into the Phase 10 engineering loop.

    Carries findings ONLY.  Repair logic is executed by Phase 10 — Review must
    not duplicate repair responsibility.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    request_id: str = Field(default_factory=lambda: str(_new_uuid()))
    review_id: str = Field(...)
    task_id: str | None = Field(default=None)
    workflow_id: uuid.UUID | None = Field(default=None)
    project_id: uuid.UUID | None = Field(default=None)
    correlation_id: uuid.UUID | None = Field(default=None)
    findings: list[ReviewFinding] = Field(default_factory=list)
    findings_by_category: dict[str, list[str]] = Field(default_factory=dict)
    summary: str = Field(default="")
    priority: str = Field(default="medium", pattern=r"^(low|medium|high|critical)$")

    @classmethod
    def build(
        cls,
        *,
        review_id: str,
        findings: list[ReviewFinding],
        task_id: str | None = None,
        workflow_id: uuid.UUID | None = None,
        project_id: uuid.UUID | None = None,
        correlation_id: uuid.UUID | None = None,
    ) -> "RepairRequest":
        """Build a repair hand-off grouped by category."""
        by_category: dict[str, list[str]] = {}
        for f in findings:
            by_category.setdefault(f.category.value, []).append(str(f.finding_id))
        if any(f.severity == Severity.CRITICAL for f in findings):
            priority = "critical"
        elif any(f.severity == Severity.HIGH for f in findings):
            priority = "high"
        else:
            priority = "medium"
        return cls(
            review_id=review_id,
            findings=findings,
            findings_by_category=by_category,
            summary=(
                f"{len(findings)} finding(s) in "
                + ", ".join(sorted(by_category))
            ),
            priority=priority,
            task_id=task_id,
            workflow_id=workflow_id,
            project_id=project_id,
            correlation_id=correlation_id,
        )
# ── Final review result ────────────────────────────────────────────────────


class ReviewResult(BaseModel):
    """Structured, provenance-aware review output (sections 5.9 and 28)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    review_id: str = Field(...)
    project_id: uuid.UUID | None = Field(default=None)
    workflow_id: uuid.UUID | None = Field(default=None)
    task_id: str | None = Field(default=None)
    execution_id: str | None = Field(default=None)
    worker_id: str | None = Field(default=None)
    attempt_number: int = Field(default=1, ge=1)
    correlation_id: uuid.UUID | None = Field(default=None)

    categories_run: list[str] = Field(default_factory=list)
    findings: list[ReviewFinding] = Field(default_factory=list)

    count_by_category: dict[str, int] = Field(default_factory=dict)
    count_by_severity: dict[str, int] = Field(default_factory=dict)
    deterministic_findings: int = Field(default=0, ge=0)
    ai_findings: int = Field(default=0, ge=0)
    blocking_findings: int = Field(default=0, ge=0)

    gate: QualityGateResult = Field(...)
    decision: ReviewDecision = Field(...)
    ai_source: AISourceMetadata = Field(default_factory=AISourceMetadata)
    policy_version: str = Field(default="1.0.0")

    repair: RepairRequest | None = Field(default=None)

    started_at: datetime = Field(default_factory=_utc_now)
    finished_at: datetime = Field(default_factory=_utc_now)
    duration_ms: float = Field(default=0.0)

    @property
    def approved(self) -> bool:
        return self.decision == ReviewDecision.APPROVED

    @property
    def rejected(self) -> bool:
        return self.decision in {ReviewDecision.REJECTED, ReviewDecision.CHANGES_REQUESTED}


# ── Review Loop ────────────────────────────────────────────────────────────


class ReviewLoopStatus(str, Enum):
    """Bounded Review Loop lifecycle (section 29 / 35)."""

    NOT_STARTED = "not_started"
    ANALYZING = "analyzing"
    VALIDATING = "validating"
    REVIEWING = "reviewing"
    REPORTING = "reporting"
    GATING = "gating"
    COMPLETED = "completed"
    REPAIR_REQUESTED = "repair_requested"
    REJECTED = "rejected"
    BLOCKED = "blocked"
    HITL = "hitl"
    LIMIT_EXCEEDED = "limit_exceeded"


class ReviewCycleRecord(BaseModel):
    """One bounded cycle of the review loop."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    cycle: int = Field(..., ge=1)
    review_id: str = Field(...)
    gate: QualityGateResult = Field(...)
    decision: ReviewDecision = Field(...)
    finding_count: int = Field(default=0, ge=0)
    at: datetime = Field(default_factory=_utc_now)


class ReviewLoopResult(BaseModel):
    """Final outcome of a Review Loop."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    status: ReviewLoopStatus = Field(...)
    cycles: list[ReviewCycleRecord] = Field(default_factory=list)
    final_result: ReviewResult | None = Field(default=None)
    repair: RepairRequest | None = Field(default=None)
    summary: str = Field(default="")