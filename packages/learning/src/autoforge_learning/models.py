"""Immutable learning domain models — Phase 19B-1 / 19B-3.

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

Phase 19B-3 extends this module with the complete closed-loop system model
(Gate 1): experience, signal classes, hypothesis, experiment, experiment run,
activation, observation, regression report, lineage, and reward. Every added
type inherits rules 1–6 unchanged; none of them is a duplicate of a 19B type,
and every one is enforced by a test rather than a comment.
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


# ── Phase 19B-3: the complete closed-loop system model (Gate 1) ───────────────
#
# Everything below is *additive*. No 19B-1/19B-2 type is renamed, re-scoped or
# duplicated: ``ExperienceRecord``, ``LearningSignal``, ``LearningCandidate``,
# ``EvaluationReport``, ``ApprovalRecord``, ``PromotionRecord``,
# ``RollbackHandle``/``RollbackRecord`` and ``ActiveLearningState`` are reused
# exactly as 19B defined them. What is new are the objects 19A specified
# architecturally but for which no model yet existed.


class SignalClass(str, Enum):
    """The twelve learning-signal classes required by 19B-3 Gate 3.

    ``REGRESSION`` and ``IMPROVEMENT`` are *directional*; the rest name the
    phenomenon. Hard constraints are deliberately **not** a class: 19A §1
    forbids scoring a security violation even negatively, because doing so
    teaches the optimizer that the boundary is negotiable.
    """

    SUCCESS = "success"
    FAILURE = "failure"
    REGRESSION = "regression"
    IMPROVEMENT = "improvement"
    INEFFICIENCY = "inefficiency"
    REPAIR_PATTERN = "repair_pattern"
    REPEATED_ERROR = "repeated_error"
    USER_FEEDBACK = "user_feedback"
    VALIDATION_RESULT = "validation_result"
    REVIEW_RESULT = "review_result"
    RESOURCE_PATTERN = "resource_pattern"
    TOOL_PATTERN = "tool_pattern"

    @property
    def is_directional(self) -> bool:
        return self in (SignalClass.REGRESSION, SignalClass.IMPROVEMENT)


class ExperienceSource(str, Enum):
    """Real AutoForge execution sources an experience may come from (Gate 2).

    The enum *is* the enforcement: an observation naming a source outside this
    set cannot be constructed, so "experience" can never quietly mean
    "something the learning system invented".
    """

    TASK_EXECUTION = "task_execution"
    VALIDATION = "validation"
    REVIEW = "review"
    ARTIFACT_GENERATION = "artifact_generation"
    REPAIR_ATTEMPT = "repair_attempt"
    FAILURE = "failure"
    RETRY = "retry"
    EXECUTION_LATENCY = "execution_latency"
    RESOURCE_BEHAVIOUR = "resource_behaviour"
    TOOL_OUTCOME = "tool_outcome"
    MODEL_OUTCOME = "model_outcome"
    USER_FEEDBACK = "user_feedback"
    PROJECT_OUTCOME = "project_outcome"
    MODERNIZATION = "modernization"
    MIGRATION = "migration"
    RAG_RETRIEVAL = "rag_retrieval"
    AGENT_TASK_OUTCOME = "agent_task_outcome"
    AUTOMATION_OUTCOME = "automation_outcome"


class ExecutionObservation(LearningBase):
    """One real, hashed observation of something that happened (Gate 2).

    Deliberately the narrowest representation the pipeline accepts: a source, a
    subject identity, a content hash and an outcome. It carries no
    interpretation, so a model explanation cannot be smuggled in as evidence.
    Model text lands in ``model_annotation``, typed so it can never contribute
    to a score (CR-05).
    """

    observation_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    scope: LearningScope
    source: ExperienceSource
    #: Stable identity of the observed thing. Never free text, never a payload.
    subject_ref: str
    observed_at: datetime = Field(default_factory=_utc_now)
    #: SHA-256 over the authoritative record this observation summarises.
    content_hash: str = Field(..., min_length=8)
    outcome: str
    #: Present only when the source actually measured it. Never ``0.0`` as a
    #: stand-in for "not measured".
    duration_ms: Optional[float] = None
    resource_units: Optional[float] = None
    correlation_id: Optional[str] = None
    model_annotation: Optional[str] = None
    model_annotation_authoritative: Literal[False] = False


class Hypothesis(LearningBase):
    """A falsifiable proposal arising from real experience (Gate 4).

    A hypothesis is **inert**. It names an observation, its supporting
    evidence, a proposed change, an expected effect, a *measurable* success
    criterion, a risk, a scope, an authority level and a rollback strategy — and
    can do none of those things itself. Only a ``LearningCandidate`` that passed
    the security boundary, evaluation and human approval may affect behaviour.
    """

    hypothesis_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    scope: LearningScope
    observation: str
    supporting_evidence: tuple[EvidenceRef, ...] = ()
    proposed_change: str
    expected_effect: str
    #: Machine-checkable. A hypothesis whose criterion cannot be evaluated is
    #: not falsifiable and is rejected at construction.
    success_metric: str
    success_threshold: float
    success_direction: Literal["increase", "decrease"] = "increase"
    risk: str
    authority: LearningAuthority = LearningAuthority.L1_INSIGHT
    rollback_strategy: str
    created_at: datetime = Field(default_factory=_utc_now)
    created_by: str = "autoforge.learning"
    #: Competing hypotheses are a set, not a queue. The generator is forbidden
    #: from treating the first hypothesis it produced as the answer.
    competing_with: tuple[uuid.UUID, ...] = ()
    model_annotation: Optional[str] = None
    model_annotation_authoritative: Literal[False] = False

    @field_validator("supporting_evidence", "competing_with", mode="before")
    @classmethod
    def _freeze_hypothesis_sequences(cls, v: Any) -> Any:
        return tuple(v) if v is not None else ()

    @field_validator("authority")
    @classmethod
    def _no_l5_hypothesis(cls, v: LearningAuthority) -> LearningAuthority:
        if v.is_security_authority:
            raise ValueError(
                "a hypothesis cannot carry Level 5 security/policy authority"
            )
        return v

    @model_validator(mode="after")
    def _hypothesis_must_be_falsifiable(self) -> "Hypothesis":
        if not self.success_metric.strip():
            raise ValueError("a hypothesis requires a measurable success_metric")
        if not self.supporting_evidence:
            raise ValueError(
                "a hypothesis requires supporting evidence; an unsupported "
                "hypothesis is a guess, not a hypothesis"
            )
        return self

    @property
    def is_inert(self) -> bool:
        return self.authority is not LearningAuthority.L4_OPERATIONAL


class ExperimentCapability(str, Enum):
    """Capabilities an experiment sandbox may hold — declared, never implied.

    Gate 6: "undeclared capabilities are denied". The set is deliberately tiny.
    Note what is *absent*: unrestricted filesystem, network, production
    credentials, deployment authority, security-policy modification. They are not
    configurable — they are not members of the enumeration.
    """

    CPU_TIME = "cpu_time"
    MEMORY = "memory"
    DISK = "disk"
    DETERMINISTIC_VALIDATION = "deterministic_validation"
    REPLAY_FIXTURES = "replay_fixtures"


class Experiment(LearningBase):
    """A pre-registered, bounded experiment design (19B-3 Gates 5–7, 30).

    Everything needed to *judge* the experiment is fixed **before** the first
    observation. Post-hoc selection of success criteria is the central
    anti-gaming property of 19A §2.1, so the criteria are part of this
    immutable record and a run can never rewrite them.
    """

    experiment_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    scope: LearningScope
    hypothesis: Hypothesis
    #: Pinned baseline. Immutable for the duration of the run.
    baseline_version_id: Optional[uuid.UUID] = None
    treatment_candidate_id: Optional[uuid.UUID] = None
    evaluation_metric: str
    success_threshold: float
    success_direction: Literal["increase", "decrease"] = "increase"
    #: Non-regression floors inherited from the nine protected invariants.
    non_regression_floors: dict[str, float] = Field(default_factory=dict)
    dataset_input_ids: tuple[str, ...] = ()
    max_duration_seconds: float = Field(gt=0.0)
    max_iterations: int = Field(ge=1)
    max_cost_units: float = Field(ge=0.0)
    declared_capabilities: tuple[ExperimentCapability, ...] = ()
    #: Pre-registered deterministic rollback target. Mandatory.
    rollback_target_version_id: Optional[uuid.UUID] = None
    created_at: datetime = Field(default_factory=_utc_now)
    created_by: str = "autoforge.learning"
    #: Identity of the model that GENERATED the hypothesis, kept so the
    #: generator can be excluded from being the sole evaluator (Gate 24).
    generator_identity: str = ""
    seed: Optional[int] = None
    correlation_id: Optional[str] = None

    @field_validator("declared_capabilities", "dataset_input_ids", mode="before")
    @classmethod
    def _freeze_experiment_sequences(cls, v: Any) -> Any:
        return tuple(v) if v is not None else ()

    @model_validator(mode="after")
    def _experiment_is_bounded_and_pre_registered(self) -> "Experiment":
        if not self.evaluation_metric.strip():
            raise ValueError("an experiment requires a named evaluation_metric")
        if self.max_duration_seconds <= 0 or self.max_iterations < 1:
            raise ValueError("an experiment must declare time and iteration bounds")
        if self.rollback_target_version_id is None:
            raise ValueError(
                "an experiment must pre-register its deterministic rollback target"
            )
        return self

    @property
    def capability_names(self) -> frozenset[ExperimentCapability]:
        return frozenset(self.declared_capabilities)

    @property
    def is_resource_bounded(self) -> bool:
        return self.max_cost_units >= 0.0 and self.max_duration_seconds > 0.0


class ExperimentOutcome(str, Enum):
    """Terminal outcome of an experiment run.

    ``INCONCLUSIVE`` is first-class (19A §5). Its purpose is to remove the
    incentive to re-run until a favourable result appears.
    """

    SURVIVED = "survived"
    REFUTED = "refuted"
    INCONCLUSIVE = "inconclusive"
    TERMINATED_ON_INVARIANT_BREACH = "terminated_on_invariant_breach"
    TERMINATED_ON_BUDGET = "terminated_on_budget"
    ABORTED = "aborted"


class ExperimentArm(str, Enum):
    """Control versus treatment. Gate 7: "model says better" is not a result."""

    CONTROL = "control"
    TREATMENT = "treatment"


class ArmOutcome(LearningBase):
    """The measured result of one arm.

    Holds *measured values* and their evidence — never a verdict. The verdict is
    computed by comparing the two arms, so neither arm can declare itself
    better, which is exactly Gate 7's prohibition on "model says better".
    """

    arm: ExperimentArm
    metrics: dict[str, float] = Field(default_factory=dict)
    evidence: tuple[EvidenceRef, ...] = ()
    iterations_completed: int = Field(default=0, ge=0)
    cost_units: float = 0.0
    duration_seconds: float = 0.0
    #: Set when the arm could not produce a trustworthy measurement.
    measurement_unavailable_reason: str = ""

    @field_validator("evidence", mode="before")
    @classmethod
    def _freeze_arm_evidence(cls, v: Any) -> Any:
        return tuple(v) if v is not None else ()

    @property
    def is_measured(self) -> bool:
        return not self.measurement_unavailable_reason

    def metric(self, name: str) -> Optional[float]:
        return self.metrics.get(name)


class ExperimentRun(LearningBase):
    """The immutable record of one executed experiment (Gate 5, 30).

    Carries everything another process needs to reproduce the conclusion: the
    design it ran, both arms' measurements, the seed, the environment, the
    code/learning versions, and the resulting verdict.
    """

    run_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    experiment_id: uuid.UUID
    scope: LearningScope
    hypothesis_id: uuid.UUID
    control: ArmOutcome
    treatment: ArmOutcome
    outcome: ExperimentOutcome
    #: Identity of whatever judged the run. Empty is allowed, but then
    #: deterministic validation is the sole authority (Gate 24 minimum).
    evaluator_identity: str = ""
    started_at: datetime = Field(default_factory=_utc_now)
    finished_at: Optional[datetime] = None
    environment: dict[str, str] = Field(default_factory=dict)
    code_version: str = ""
    learning_version: str = ""
    model_provider: str = ""
    prompt_context_version: str = ""
    reproduction_instructions: str = ""
    termination_reason: str = ""
    reward_total: float = 0.0
    #: True when a reward was recorded but deliberately not allowed to decide
    #: the outcome (Gate 8: reward is not authority).
    reward_suppressed: bool = False
    correlation_id: Optional[str] = None

    @model_validator(mode="after")
    def _both_arms_must_be_present(self) -> "ExperimentRun":
        if self.control.arm is not ExperimentArm.CONTROL:
            raise ValueError("the control arm is missing or mislabelled")
        if self.treatment.arm is not ExperimentArm.TREATMENT:
            raise ValueError("the treatment arm is missing or mislabelled")
        return self

    @property
    def measured_delta(self) -> Optional[float]:
        """Treatment minus control on the shared primary metric, or ``None``.

        ``None`` when either arm failed to produce it — an unmeasured
        comparison is reported as absent, never as zero.
        """
        if not (self.control.is_measured and self.treatment.is_measured):
            return None
        shared = set(self.control.metrics) & set(self.treatment.metrics)
        if len(shared) != 1:
            return None
        name = next(iter(shared))
        return self.treatment.metrics[name] - self.control.metrics[name]

    @property
    def is_reproducible(self) -> bool:
        return bool(self.reproduction_instructions) and self.environment != {}


class ActivationMode(str, Enum):
    """How much real traffic an active candidate receives (Gate 14).

    ``SHADOW`` is the important one: the candidate observes what it *would*
    have done while the baseline result stays authoritative. Shadow gains no
    authority precisely because it changes nothing.
    """

    SHADOW = "shadow"
    CANARY = "canary"
    LIMITED = "limited"
    FULL = "full"


class ActivationState(str, Enum):
    """Activation is separate from promotion (Gate 14).

    A ``PROMOTED`` candidate may legitimately be ``INACTIVE`` during a staged
    rollout. Conflating the two is what made "promotion" ambiguous in 19A.
    """

    INACTIVE = "inactive"
    SHADOW = "shadow"
    CANARY = "canary"
    LIMITED = "limited"
    FULL = "full"
    DEACTIVATED = "deactivated"
    ROLLED_BACK = "rolled_back"


class ActivationRecord(LearningBase):
    """One explicit, auditable activation-state transition."""

    activation_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    candidate_id: uuid.UUID
    project_id: uuid.UUID
    kind: str
    key: str
    state: ActivationState
    mode: ActivationMode = ActivationMode.FULL
    #: Fraction of executions receiving the candidate. 0.0 is pure shadow.
    traffic_fraction: float = Field(default=1.0, ge=0.0, le=1.0)
    #: The version actually in force, so rollback is exact.
    version_id: Optional[uuid.UUID] = None
    rollback_handle_id: Optional[uuid.UUID] = None
    activated_at: datetime = Field(default_factory=_utc_now)
    deactivated_at: Optional[datetime] = None
    activated_by: str = "autoforge.learning.activation"
    correlation_id: Optional[str] = None

    @model_validator(mode="after")
    def _shadow_never_carries_traffic(self) -> "ActivationRecord":
        if self.state is ActivationState.SHADOW and self.traffic_fraction > 0.0:
            raise ValueError(
                "shadow activation must receive zero real traffic; a shadow "
                "candidate that affects behaviour is not a shadow"
            )
        return self

    @property
    def affects_behaviour(self) -> bool:
        return (
            self.state
            in (ActivationState.CANARY, ActivationState.LIMITED, ActivationState.FULL)
            and self.traffic_fraction > 0.0
        )


class RegressionSeverity(str, Enum):
    """Severity ladder for an observed regression (Gates 16, 18)."""

    NONE = "none"
    #: A tracked metric moved past its pre-registered threshold.
    MINOR = "minor"
    #: A required protected invariant regressed.
    MAJOR = "major"
    #: A hard-stop condition: security violation, correctness collapse, artifact
    #: corruption, credential leakage, policy or sandbox violation.
    CATASTROPHIC = "catastrophic"


class RegressionReport(LearningBase):
    """The deterministic verdict of post-activation monitoring (Gate 16).

    Every threshold is pre-registered with the activation. This report compares
    measurements against those thresholds; it contains no model judgement and
    cannot invent a threshold.
    """

    report_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    candidate_id: uuid.UUID
    project_id: uuid.UUID
    kind: str
    key: str
    severity: RegressionSeverity
    tripped_metrics: tuple[str, ...] = ()
    tripped_invariants: tuple[str, ...] = ()
    catastrophic_reasons: tuple[str, ...] = ()
    sample_size: int = Field(default=0, ge=0)
    observed_at: datetime = Field(default_factory=_utc_now)
    evidence: tuple[EvidenceRef, ...] = ()
    #: Whether monitoring concluded an automatic rollback is contractually safe.
    auto_rollback_permitted: bool = False
    rollback_handle_id: Optional[uuid.UUID] = None
    correlation_id: Optional[str] = None

    @field_validator(
        "tripped_metrics",
        "tripped_invariants",
        "catastrophic_reasons",
        "evidence",
        mode="before",
    )
    @classmethod
    def _freeze_regression_sequences(cls, v: Any) -> Any:
        return tuple(v) if v is not None else ()

    @property
    def is_regression(self) -> bool:
        return self.severity is not RegressionSeverity.NONE

    @property
    def is_catastrophic(self) -> bool:
        return self.severity is RegressionSeverity.CATASTROPHIC


class LearningLineage(LearningBase):
    """Correlation across the whole loop (Gates 1, 30).

    One immutable record linking which observations produced which signals,
    which signals produced which hypotheses, and so on. This is what makes
    "where did this behaviour come from?" answerable without guessing.
    """

    lineage_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    project_id: uuid.UUID
    correlation_id: str
    experience_ids: tuple[uuid.UUID, ...] = ()
    signal_ids: tuple[uuid.UUID, ...] = ()
    hypothesis_ids: tuple[uuid.UUID, ...] = ()
    candidate_id: Optional[uuid.UUID] = None
    experiment_run_ids: tuple[uuid.UUID, ...] = ()
    evaluation_id: Optional[uuid.UUID] = None
    approval_id: Optional[uuid.UUID] = None
    promotion_id: Optional[uuid.UUID] = None
    activation_ids: tuple[uuid.UUID, ...] = ()
    regression_report_ids: tuple[uuid.UUID, ...] = ()
    parent_lineage_id: Optional[uuid.UUID] = None
    generation: int = Field(default=0, ge=0)
    created_at: datetime = Field(default_factory=_utc_now)

    @field_validator(
        "experience_ids",
        "signal_ids",
        "hypothesis_ids",
        "experiment_run_ids",
        "activation_ids",
        "regression_report_ids",
        mode="before",
    )
    @classmethod
    def _freeze_lineage_sequences(cls, v: Any) -> Any:
        return tuple(v) if v is not None else ()

    @property
    def is_complete_loop(self) -> bool:
        """True when one correlation id traverses observe → promote → observe."""
        return bool(
            self.experience_ids
            and self.signal_ids
            and self.hypothesis_ids
            and self.candidate_id
            and self.experiment_run_ids
            and self.promotion_id
        )


class RewardPolarity(str, Enum):
    POSITIVE = "positive"
    NEGATIVE = "negative"
    #: The system refuses to score this at all (19A §1).
    DISQUALIFYING = "disqualifying"


class Reward(LearningBase):
    """A single reward observation with provenance (Gate 8).

    Reward is **not authority**. This type can express a number; it carries no
    capability, no permission and no gate decision, and the type system makes
    that structural — there is no field through which a reward could be
    exchanged for one.
    """

    reward_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    scope: LearningScope
    objective: str
    polarity: RewardPolarity
    raw_value: float
    normalized_value: float = 0.0
    #: Where the number came from. A reward with no provenance is discarded.
    provenance_ref: str
    provenance_hash: str = Field(..., min_length=8)
    experiment_run_id: Optional[uuid.UUID] = None
    candidate_id: Optional[uuid.UUID] = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    recorded_at: datetime = Field(default_factory=_utc_now)
    model_annotation: Optional[str] = None
    model_annotation_authoritative: Literal[False] = False

    @model_validator(mode="after")
    def _reward_requires_provenance(self) -> "Reward":
        if not self.provenance_ref.strip():
            raise ValueError(
                "a reward without a provenance reference is fabricated and is "
                "rejected at construction"
            )
        return self

    @property
    def is_disqualifying(self) -> bool:
        return self.polarity is RewardPolarity.DISQUALIFYING


class LearningClass(str, Enum):
    """Gate 22: project-specific vs. explicitly generalized learning.

    There is no implicit path from ``PROJECT_SPECIFIC`` to ``GLOBAL_VALIDATED``.
    Changing class is an explicit, separately governed act with stronger
    validation — never a side effect of promotion.
    """

    PROJECT_SPECIFIC = "project_specific"
    GLOBAL_VALIDATED = "global_validated"


class ResourceBudget(LearningBase):
    """Bounded resource envelope for autonomous learning (Gate 31).

    Learning is optional relative to the critical path, so every budget here is
    a *ceiling on learning's own consumption* — never a reservation taken from
    the core engineering path.
    """

    budget_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    project_id: uuid.UUID
    max_experiments: int = Field(ge=0)
    max_recursion_depth: int = Field(ge=0)
    max_wall_clock_seconds: float = Field(ge=0.0)
    max_model_calls: int = Field(ge=0)
    max_concurrent_experiments: int = Field(ge=0)
    max_disk_bytes: int = Field(ge=0)
    max_memory_bytes: int = Field(ge=0)
    max_network_bytes: int = Field(ge=0)
    created_at: datetime = Field(default_factory=_utc_now)

    @property
    def denies_everything_by_default(self) -> bool:
        """A zero budget is an honest deny, never an accidental unlimited one."""
        return self.max_experiments == 0


class BudgetExhausted(RuntimeError):
    """Raised when a learning operation exceeds its pre-registered budget.

    Fail-safe by construction: the caller cannot proceed without the budget, and
    the outcome is a deterministic exception rather than a silent degradation.
    """


__all__ = [
    "SCHEMA_VERSION",
    "ActivationMode",
    "ActivationRecord",
    "ActivationState",
    "ApprovalState",
    "ArmOutcome",
    "BudgetExhausted",
    "EvidenceQuality",
    "EvidenceRef",
    "EvidenceSource",
    "ExecutionObservation",
    "ExperienceRecord",
    "ExperienceSource",
    "Experiment",
    "ExperimentArm",
    "ExperimentCapability",
    "ExperimentOutcome",
    "ExperimentRun",
    "Hypothesis",
    "LearningAuthority",
    "LearningBase",
    "LearningCandidate",
    "LearningClass",
    "LearningLineage",
    "LearningScope",
    "LearningScopeKind",
    "LearningSignal",
    "RegressionReport",
    "RegressionSeverity",
    "ResourceBudget",
    "Reward",
    "RewardPolarity",
    "SignalClass",
    "SignalPolarity",
    "TestOutcome",
    "TIER_OF_SOURCE",
    "ValidationState",
    "ValidationSummary",
    "ValidationTruth",
    "quality_for",
]
