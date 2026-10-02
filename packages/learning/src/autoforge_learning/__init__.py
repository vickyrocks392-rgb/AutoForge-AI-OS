"""AutoForge AI — Learning (Phase 19).

Phase 19B-1 establishes the safe foundation for continuous learning:

* **Immutable domain models** (:mod:`autoforge_learning.models`) — frozen,
  schema-versioned, project-scoped, evidence-linked.
* **Authoritative evidence collection** (:mod:`autoforge_learning.evidence`) —
  experience built only from real deterministic/completion/artifact sources.
* **Evidence-derived signals** (:mod:`autoforge_learning.signals`) — confidence
  computed from evidence, never assigned by a branch constant.
* **The ProposalGateway** (:mod:`autoforge_learning.gateway`) — the only
  sanctioned entry point for a learning candidate, routing every proposal
  through the certified ``evaluate_learning_proposal`` security boundary,
  fail-closed.

Scope boundary: this package does **not** promote, activate, or self-modify.
``PERMITTED`` means "may proceed to the next controlled stage", never
"approved" or "activated".

Phase 19B-2 adds the validation/evaluation/promotion path on top of that
foundation, still bound to the existing security architecture:

* **The nine protected invariants** (:mod:`autoforge_learning.invariants`)
  — transcribed from Gate 19A-8, with an explicit result for each.
* **The regression evaluator** (:mod:`autoforge_learning.evaluation`) —
  fails closed; absent evidence is ``UNAVAILABLE``, never ``PASS``.
* **The durable learning store** (:mod:`autoforge_learning.store`) —
  project-scoped, crash-safe, immutable candidate identity, distinct from
  artifact persistence.
* **Approval** (:mod:`autoforge_learning.approval`) — bound to the existing
  ``HITLManager`` + ``GovernancePolicyEngine``. Human-only.
* **Promotion and rollback** (:mod:`autoforge_learning.promotion`) —
  rollback handle before activation, atomic commit, deterministic rollback.
* **Audit** (:mod:`autoforge_learning.audit`) — routed through the certified
  ``AuditEngine``.
* **Truthful telemetry** (:mod:`autoforge_learning.telemetry`).

Promotion still requires a human decision recorded by the security
platform. Nothing in this package grants authority, and Level 5 remains
unreachable by construction.
"""

from autoforge_learning.approval import (
    PROMOTION_ACTION,
    ApprovalCoordinator,
    ApprovalError,
)
from autoforge_learning.audit import (
    ALL_AUDIT_ACTIONS,
    LearningAuditAction,
    LearningAuditError,
    LearningAuditor,
)
from autoforge_learning.evaluation import (
    EvaluationOutcome,
    EvaluationReport,
    InvariantResult,
    RegressionEvaluator,
)
from autoforge_learning.evidence import EvidenceCollector
from autoforge_learning.gateway import (
    GatewayDenialReason,
    ProposalDecision,
    ProposalGateway,
    ProposalOutcome,
)
from autoforge_learning.invariants import (
    INVARIANT_IDS,
    NA_PERMITTED_BY_CONTRACT,
    PROTECTED_INVARIANTS,
    InvariantClass,
    InvariantMetrics,
    InvariantSpec,
    InvariantStatus,
    ProtectedInvariant,
)
from autoforge_learning.lifecycle import LearningLifecycleService
from autoforge_learning.models import (
    SCHEMA_VERSION,
    ApprovalState,
    EvidenceQuality,
    EvidenceRef,
    EvidenceSource,
    ExperienceRecord,
    LearningAuthority,
    LearningBase,
    LearningCandidate,
    LearningScope,
    LearningScopeKind,
    LearningSignal,
    SignalPolarity,
    TestOutcome,
    ValidationState,
    ValidationSummary,
    ValidationTruth,
)
from autoforge_learning.promotion import (
    PromotionConflict,
    PromotionError,
    PromotionService,
    RollbackError,
)
from autoforge_learning.signals import (
    derive_confidence,
    disqualifying_signal,
    negative_signal,
    positive_signal,
)
from autoforge_learning.store import (
    STORE_SCHEMA_VERSION,
    ActiveLearningState,
    ApprovalRecord,
    ApprovalStatus,
    CandidateRecord,
    DurableLearningStore,
    LearningRecordCorrupt,
    LearningRecordNotFound,
    PromotionRecord,
    PromotionState,
    RollbackHandle,
    RollbackRecord,
)
from autoforge_learning.telemetry import LearningTelemetry, TelemetryCollector

__all__ = [
    "ALL_AUDIT_ACTIONS",
    "INVARIANT_IDS",
    "NA_PERMITTED_BY_CONTRACT",
    "PROMOTION_ACTION",
    "PROTECTED_INVARIANTS",
    "SCHEMA_VERSION",
    "STORE_SCHEMA_VERSION",
    "ActiveLearningState",
    "ApprovalCoordinator",
    "ApprovalError",
    "ApprovalRecord",
    "ApprovalState",
    "ApprovalStatus",
    "CandidateRecord",
    "DurableLearningStore",
    "EvaluationOutcome",
    "EvaluationReport",
    "EvidenceCollector",
    "EvidenceQuality",
    "EvidenceRef",
    "EvidenceSource",
    "ExperienceRecord",
    "GatewayDenialReason",
    "InvariantClass",
    "InvariantMetrics",
    "InvariantResult",
    "InvariantSpec",
    "InvariantStatus",
    "LearningAuditAction",
    "LearningAuditError",
    "LearningAuditor",
    "LearningAuthority",
    "LearningBase",
    "LearningCandidate",
    "LearningLifecycleService",
    "LearningRecordCorrupt",
    "LearningRecordNotFound",
    "LearningScope",
    "LearningScopeKind",
    "LearningSignal",
    "LearningTelemetry",
    "ProposalDecision",
    "ProposalGateway",
    "ProposalOutcome",
    "PromotionConflict",
    "PromotionError",
    "PromotionRecord",
    "PromotionService",
    "PromotionState",
    "ProtectedInvariant",
    "RegressionEvaluator",
    "RollbackError",
    "RollbackHandle",
    "RollbackRecord",
    "SignalPolarity",
    "TelemetryCollector",
    "TestOutcome",
    "ValidationState",
    "ValidationSummary",
    "ValidationTruth",
    "derive_confidence",
    "disqualifying_signal",
    "negative_signal",
    "positive_signal",
]