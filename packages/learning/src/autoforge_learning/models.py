"""Immutable learning domain models — Phase 19B-1.

Architecture basis: ``phase19/EXPERIENCE_MODEL.md`` (Gate 3),
``phase19/LEARNING_AUTHORITY_MODEL.md`` (Gate 5),
``phase19/LEARNING_SIGNAL_MODEL.md`` (Gate 4),
``phase19/LEARNING_ISOLATION_AND_OBSERVABILITY.md`` (Gate 9).

Design rules enforced here — each is a testable property:

1. **Immutable.** Every model is ``frozen=True``. A learning artifact that can
   be mutated after the fact is not auditable.
2. **Explicit schema identity.** Every model carries ``schema_version`` so a
   stored record can be interpreted without guessing.
3. **No fabricated values.** Absence of evidence is modelled explicitly
   (``ValidationTruth.UNAVAILABLE``, ``None`` counts) and is never substituted
   with a plausible default. This is the structural fix for the tautological
   ``confidence >= 0.90`` promotion gate found in Gate 19A.
4. **Project/workflow scope is mandatory.** Every record carries a scope. There
   is no "global learning" construct.
5. **Non-authoritative text cannot become authority.** Model-generated text is
   confined to ``model_annotation``, typed so it can never contribute to a
   signal, a score, or an authority claim.
6. **Deterministic serialization.** ``canonical_json()`` is stable so content
   hashes are reproducible.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

#: Bumped only for a breaking change to the on-disk shape.
SCHEMA_VERSION = "1.0.0"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _canonical(value: Any) -> str:
    """Deterministic JSON: sorted keys, no insignificant whitespace."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


class LearningBase(BaseModel):
    """Common immutability and serialization contract."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: str = SCHEMA_VERSION

    def canonical_json(self) -> str:
        """Deterministic JSON representation (stable across processes)."""
        return _canonical(self.model_dump(mode="json"))

    def record_hash(self) -> str:
        """SHA-256 of :meth:`canonical_json` — tamper evidence.

        Named ``record_hash`` rather than ``content_hash`` so
        :class:`EvidenceRef` can keep its ``content_hash`` *field* (which hashes
        an external payload) without shadowing this method.
        """
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()


# ── Scope ────────────────────────────────────────────────────────────────────


class LearningScopeKind(str, Enum):
    """The four scopes permitted by Gate 19A §2.1.

    ``GLOBAL_SECURITY``, ``GLOBAL_IDENTITY``, ``GLOBAL_AUTHORIZATION`` and
    ``GLOBAL_CREDENTIAL`` are deliberately **absent**. A candidate whose scope
    is not one of these four cannot be constructed — the enum is the
    enforcement, not a comment.
    """

    PROJECT = "project"
    WORKFLOW_TYPE = "workflow_type"
    TASK_TYPE = "task_type"
    GLOBAL_NON_SECURITY = "global_non_security"


class LearningScope(LearningBase):
    """Mandatory project/workflow scope for every learning record."""

    kind: LearningScopeKind
    project_id: uuid.UUID
    workflow_id: Optional[str] = None
    task_type: Optional[str] = None

    @model_validator(mode="after")
    def _workflow_required_for_workflow_scope(self) -> "LearningScope":
        """Cross-field invariant.

        A ``workflow_type`` scope without a workflow id would be an unscoped
        learning record, so it is rejected rather than defaulted.
        """
        if self.kind is LearningScopeKind.WORKFLOW_TYPE and not self.workflow_id:
            raise ValueError("workflow_type scope requires a workflow_id")
        if self.kind is LearningScopeKind.TASK_TYPE and not self.task_type:
            raise ValueError("task_type scope requires a task_type")
        return self

    def matches(self, other: "LearningScope") -> bool:
        """True when a candidate in ``other`` may be applied to ``self``.

        Project scope is the default and is **never** widened implicitly:
        a candidate scoped to project A never applies to project B.
        """
        if self.project_id != other.project_id:
            return False
        if self.kind is LearningScopeKind.PROJECT:
            return other.kind is LearningScopeKind.PROJECT
        if other.kind is not self.kind:
            return False
        if self.kind is LearningScopeKind.WORKFLOW_TYPE:
            return self.workflow_id == other.workflow_id
        if self.kind is LearningScopeKind.TASK_TYPE:
            return self.task_type == other.task_type
        # GLOBAL_NON_SECURITY is non-security by construction: the capability
        # deny-list is the real bound, and it applies within the project.
        return True


# ── Authority ────────────────────────────────────────────────────────────────


class LearningAuthority(str, Enum):
    """Gate 19A §2 authority levels.

    ``L5`` exists so it can be named and rejected. There is **no transition**
    into it from any learning path: :class:`LearningCandidate` refuses to carry
    an L5 value (see its ``_never_security_authority`` validator) and
    :mod:`autoforge_learning.gateway` denies it as well.
    """

    L0_OBSERVATION = "l0_observation"
    L1_INSIGHT = "l1_insight"
    L2_CANDIDATE = "l2_candidate"
    L3_VALIDATED = "l3_validated"
    L4_OPERATIONAL = "l4_operational"
    L5_SECURITY_POLICY = "l5_security_policy"

    @property
    def level(self) -> int:
        return int(self.value[1])

    @property
    def is_security_authority(self) -> bool:
        return self is LearningAuthority.L5_SECURITY_POLICY


# ── Evidence ─────────────────────────────────────────────────────────────────


class EvidenceSource(str, Enum):
    """Authoritative sources, ordered by determinism.

    The tier encodes *how much the signal can be trusted*. Gate 19A Gate 4
    §1.1 ranks D1 (deterministic) above D2 (recorded) above D3 (aggregated).
    ``NON_AUTHORITATIVE`` covers model self-report, which may never produce a
    signal at all.
    """

    DETERMINISTIC_VALIDATION = "deterministic_validation"
    COMPLETION_GATE = "completion_gate"
    DURABLE_ARTIFACT = "durable_artifact"
    REVIEW_ENGINE = "review_engine"
    CANONICAL_EVENT = "canonical_event"
    RUNTIME_STATE = "runtime_state"
    AUDIT_RECORD = "audit_record"
    TELEMETRY = "telemetry"
    NON_AUTHORITATIVE = "non_authoritative"


TIER_OF_SOURCE: dict[EvidenceSource, int] = {
    EvidenceSource.DETERMINISTIC_VALIDATION: 1,
    EvidenceSource.COMPLETION_GATE: 1,
    EvidenceSource.DURABLE_ARTIFACT: 1,
    EvidenceSource.REVIEW_ENGINE: 2,
    EvidenceSource.CANONICAL_EVENT: 2,
    EvidenceSource.RUNTIME_STATE: 2,
    EvidenceSource.AUDIT_RECORD: 2,
    EvidenceSource.TELEMETRY: 3,
    EvidenceSource.NON_AUTHORITATIVE: 4,
}


class EvidenceQuality(str, Enum):
    """Gate 19A Gate 4 §4. Q4 may never be the basis of anything."""

    Q1 = "q1"  # deterministic, content-hashed, reproducible
    Q2 = "q2"  # deterministic record, no direct reproduction
    Q3 = "q3"  # hybrid (contains non-authoritative parts)
    Q4 = "q4"  # model-generated — never a basis


def quality_for(source: EvidenceSource) -> EvidenceQuality:
    tier = TIER_OF_SOURCE[source]
    if tier == 1:
        return EvidenceQuality.Q1
    if tier == 2:
        return EvidenceQuality.Q2
    if tier == 3:
        return EvidenceQuality.Q3
    return EvidenceQuality.Q4


class EvidenceRef(LearningBase):
    """A content-addressed pointer to an authoritative record.

    It embeds a **reference**, never the payload (Gate 14 OS-03), so the
    learning store structurally cannot leak the data it describes.
    """

    evidence_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    source: EvidenceSource
    source_ref: str
    observed_at: datetime = Field(default_factory=_utc_now)
    content_hash: str = Field(..., min_length=8)

    @property
    def quality(self) -> EvidenceQuality:
        return quality_for(self.source)

    @property
    def tier(self) -> int:
        return TIER_OF_SOURCE[self.source]

    @property
    def is_authoritative(self) -> bool:
        return self.quality is not EvidenceQuality.Q4

    @classmethod
    def from_payload(
        cls, source: EvidenceSource, source_ref: str, payload: Any
    ) -> "EvidenceRef":
        """Build a reference by hashing ``payload`` deterministically."""
        return cls(
            source=source,
            source_ref=source_ref,
            content_hash=hashlib.sha256(_canonical(payload).encode("utf-8")).hexdigest(),
        )


# ── Validation ───────────────────────────────────────────────────────────────


class ValidationTruth(str, Enum):
    """Tri-state validation truth.

    ``UNAVAILABLE`` is a first-class outcome and is **not** a pass. Collapsing
    "not applicable" into "passed" is exactly the failure mode Gate 19A
    identified in the 18-LF audit (F-01).
    """

    PASSED = "passed"
    FAILED = "failed"
    NOT_APPLICABLE = "not_applicable"
    UNAVAILABLE = "unavailable"

    @property
    def is_positive(self) -> bool:
        return self is ValidationTruth.PASSED


class TestOutcome(LearningBase):
    """Real, parsed test counts. Unavailable is represented, never invented.

    Named ``TestOutcome`` to match the execution package, so
    ``__test__ = False`` stops pytest trying to collect this data model as a
    test class (it is not one).
    """

    __test__ = False

    total: Optional[int] = None
    passed: Optional[int] = None
    failed: Optional[int] = None
    errors: Optional[int] = None
    skipped: Optional[int] = None

    @property
    def is_available(self) -> bool:
        return self.total is not None

    @classmethod
    def unavailable(cls) -> "TestOutcome":
        return cls()


class ValidationSummary(LearningBase):
    """Deterministic validation truth for one project execution."""

    truth: ValidationTruth = ValidationTruth.UNAVAILABLE
    test_outcome: TestOutcome = Field(default_factory=TestOutcome)
    reason: str = ""
    evidence: tuple[EvidenceRef, ...] = ()

    @field_validator("evidence", mode="before")
    @classmethod
    def _freeze_evidence(cls, v: Any) -> Any:
        return tuple(v) if v is not None else ()

    @property
    def is_available(self) -> bool:
        return self.truth is not ValidationTruth.UNAVAILABLE

    @classmethod
    def unavailable(
        cls, reason: str = "no deterministic validation evidence"
    ) -> "ValidationSummary":
        return cls(truth=ValidationTruth.UNAVAILABLE, reason=reason)


# ── Experience ───────────────────────────────────────────────────────────────


class ExperienceRecord(LearningBase):
    """Immutable, evidence-backed record of one completed execution.

    Constructed only by :mod:`autoforge_learning.evidence` from real
    authoritative systems. Every claim is linked to an :class:`EvidenceRef`.
    """

    experience_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    scope: LearningScope
    created_at: datetime = Field(default_factory=_utc_now)
    created_by: str = "autoforge.learning"

    # Deterministic outcome
    validation: ValidationSummary = Field(default_factory=ValidationSummary.unavailable)
    completion_succeeded: Optional[bool] = None
    review_approved: Optional[bool] = None
    artifact_count: Optional[int] = None
    artifact_hashes: tuple[str, ...] = ()
    duration_seconds: Optional[float] = None

    # Provenance
    correlation_id: Optional[str] = None
    evidence: tuple[EvidenceRef, ...] = ()

    # Non-authoritative model text. Typed so it can never be authoritative.
    model_annotation: Optional[str] = None
    model_annotation_authoritative: Literal[False] = False

    @field_validator("evidence", "artifact_hashes", mode="before")
    @classmethod
    def _freeze_sequences(cls, v: Any) -> Any:
        return tuple(v) if v is not None else ()

    @property
    def authoritative_evidence(self) -> tuple[EvidenceRef, ...]:
        return tuple(e for e in self.evidence if e.is_authoritative)

    @property
    def has_q1_evidence(self) -> bool:
        return any(e.quality is EvidenceQuality.Q1 for e in self.evidence)

    @property
    def is_evidence_backed(self) -> bool:
        """An experience record without authoritative evidence is not evidence."""
        return len(self.authoritative_evidence) > 0


# ── Signals ──────────────────────────────────────────────────────────────────


class SignalPolarity(str, Enum):
    POSITIVE = "positive"
    NEGATIVE = "negative"
    #: Gate 19A Gate 4 §1: security outcomes are NOT scored. They disqualify.
    DISQUALIFYING = "disqualifying"


class LearningSignal(LearningBase):
    """A deterministic signal derived from experience evidence.

    ``confidence`` is **derived** from the evidence actually present (see
    :func:`autoforge_learning.signals.derive_confidence`), never assigned by a
    branch constant. This is the structural replacement for Gate 19A GAP-06.
    """

    signal_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    scope: LearningScope
    polarity: SignalPolarity
    metric: str
    observation: str = ""

    evidence: tuple[EvidenceRef, ...] = ()
    sample_size: int = Field(default=0, ge=0)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)

    #: Hard constraint identifiers tripped (Gate 4 §2.3). A non-empty tuple is
    #: a disqualifier regardless of confidence.
    tripped_constraints: tuple[str, ...] = ()

    @field_validator("evidence", "tripped_constraints", mode="before")
    @classmethod
    def _freeze_signal(cls, v: Any) -> Any:
        return tuple(v) if v is not None else ()

    @property
    def is_disqualifying(self) -> bool:
        """True when the signal voids a candidate regardless of confidence."""
        return (
            self.polarity is SignalPolarity.DISQUALIFYING
            or bool(self.tripped_constraints)
        )

    @property
    def has_q1_evidence(self) -> bool:
        return any(e.quality is EvidenceQuality.Q1 for e in self.evidence)


# ── Candidates ───────────────────────────────────────────────────────────────


class ValidationState(str, Enum):
    UNVALIDATED = "unvalidated"
    VALIDATING = "validating"
    VALIDATED = "validated"
    REJECTED = "rejected"


class ApprovalState(str, Enum):
    UNAPPROVED = "unapproved"
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class LearningCandidate(LearningBase):
    """A bounded, inert proposal to change future behaviour.

    A candidate carries **no execution reference**: it is data. It cannot
    affect behaviour until a later gate (not this one) promotes it to L4 under
    explicit human approval.
    """

    candidate_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    scope: LearningScope
    authority: LearningAuthority = LearningAuthority.L2_CANDIDATE

    #: Must be one of the certified ``LEARNABLE_PROPOSAL_KINDS`` values.
    kind: str
    summary: str
    rationale: str = ""

    #: Capabilities the candidate would need. The gateway denies any overlap
    #: with ``LEARNING_FORBIDDEN_CAPABILITIES``.
    requested_capabilities: tuple[str, ...] = ()

    experience_ids: tuple[uuid.UUID, ...] = ()
    evidence: tuple[EvidenceRef, ...] = ()

    validation_state: ValidationState = ValidationState.UNVALIDATED
    approval_state: ApprovalState = ApprovalState.UNAPPROVED

    created_at: datetime = Field(default_factory=_utc_now)
    created_by: str = "autoforge.learning"

    #: Non-authoritative model text. Never a signal, never authority.
    model_annotation: Optional[str] = None
    model_annotation_authoritative: Literal[False] = False

    @field_validator("experience_ids", "requested_capabilities", "evidence", mode="before")
    @classmethod
    def _freeze(cls, v: Any) -> Any:
        return tuple(v) if v is not None else ()

    @field_validator("authority")
    @classmethod
    def _never_security_authority(cls, v: LearningAuthority) -> LearningAuthority:
        """Level 5 is unrepresentable on a learning candidate.

        This is the structural guarantee behind Gate 19A Gate 6: there is no
        reachable edge into L5 because a candidate cannot even *name* it.
        """
        if v.is_security_authority:
            raise ValueError(
                "LearningCandidate cannot carry L5 security/policy authority; "
                "no learning path may reach Level 5."
            )
        return v

    @property
    def is_inert(self) -> bool:
        """A candidate below L4 has no execution reference and cannot act."""
        return self.authority is not LearningAuthority.L4_OPERATIONAL

    @property
    def capability_names(self) -> frozenset[str]:
        return frozenset(self.requested_capabilities)


__all__ = [
    "SCHEMA_VERSION",
    "ApprovalState",
    "EvidenceQuality",
    "EvidenceRef",
    "EvidenceSource",
    "ExperienceRecord",
    "LearningAuthority",
    "LearningBase",
    "LearningCandidate",
    "LearningScope",
    "LearningScopeKind",
    "LearningSignal",
    "SignalPolarity",
    "TestOutcome",
    "TIER_OF_SOURCE",
    "ValidationState",
    "ValidationSummary",
    "ValidationTruth",
    "quality_for",
]
