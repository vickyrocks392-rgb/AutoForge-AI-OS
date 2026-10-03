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

from autoforge_learning.activation import (
    ActivationError,
    ActivationService,
    ShadowComparison,
)
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
from autoforge_learning.codemod import (
    MANDATORY_GATES,
    PROTECTED_PATHS,
    CodeChangeGatekeeper,
    CodeChangeProposal,
    CodeChangeRefused,
    GatekeeperVerdict,
    GateStatus,
)
from autoforge_learning.continual import (
    CandidateLifecycle,
    CandidateLifecycleState,
    CapabilityCase,
    CapabilitySuite,
    check_preservation,
)
from autoforge_learning.effectiveness import (
    EFFECTIVENESS_DIMENSIONS,
    PI8_CONTRACT,
    CustomerOutcomeEvidence,
    EffectivenessMeasurement,
    EffectivenessReport,
    measure_effectiveness,
)
from autoforge_learning.evaluation import (
    EvaluationOutcome,
    EvaluationReport,
    InvariantResult,
    RegressionEvaluator,
)
from autoforge_learning.evidence import EvidenceCollector
from autoforge_learning.experience import ExperienceCollector
from autoforge_learning.experiments import (
    ENFORCED_PROHIBITIONS,
    ExperimentEngine,
    ExperimentError,
)
from autoforge_learning.extraction import SignalExtractor
from autoforge_learning.gateway import (
    GatewayDenialReason,
    ProposalDecision,
    ProposalGateway,
    ProposalOutcome,
)
from autoforge_learning.governance import LearningTelemetry19B3, ResourceGovernor
from autoforge_learning.hypothesis import HypothesisGenerator
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
from autoforge_learning.learning_system import AutonomousLearningSystem, LearningCycle
from autoforge_learning.lifecycle import LearningLifecycleService
from autoforge_learning.models import (
    SCHEMA_VERSION,
    ActivationMode,
    ActivationRecord,
    ActivationState,
    ApprovalState,
    ArmOutcome,
    BudgetExhausted,
    EvidenceQuality,
    EvidenceRef,
    EvidenceSource,
    ExecutionObservation,
    ExperienceRecord,
    ExperienceSource,
    Experiment,
    ExperimentArm,
    ExperimentCapability,
    ExperimentOutcome,
    ExperimentRun,
    Hypothesis,
    LearningAuthority,
    LearningBase,
    LearningCandidate,
    LearningClass,
    LearningLineage,
    LearningScope,
    LearningScopeKind,
    LearningSignal,
    RegressionReport,
    RegressionSeverity,
    ResourceBudget,
    Reward,
    RewardPolarity,
    SignalClass,
    SignalPolarity,
    TestOutcome,
    ValidationState,
    ValidationSummary,
    ValidationTruth,
)
from autoforge_learning.monitoring import (
    CATASTROPHIC_CONDITIONS,
    RegressionMonitor,
    RegressionPolicy,
    RollbackOutcome,
)
from autoforge_learning.optimization import (
    NEVER_OPTIMIZABLE,
    OPTIMIZABLE_TARGETS,
    BoundedOptimizer,
    OptimizationRefused,
)
from autoforge_learning.promotion import (
    PromotionConflict,
    PromotionError,
    PromotionService,
    RollbackError,
)
from autoforge_learning.recursion import (
    AuthorityExpansionAttempted,
    RecursiveImprovement,
    assert_no_authority_expansion,
)
from autoforge_learning.recovery import (
    RecoveryAction,
    RecoveryReconciler,
    RecoveryReport,
    RecoveryState,
)
from autoforge_learning.rewards import (
    PROTECTED_METRICS,
    RewardLedger,
    RewardRejected,
)
from autoforge_learning.runtime import LearningOverlay, OverlayResolution
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
from autoforge_learning.transfer import (
    TransferEvaluator,
    TransferPolicy,
    TransferRefused,
    TransferRequest,
    TransferVerdict,
    assert_no_implicit_generalization,
)

__all__ = [
    "ALL_AUDIT_ACTIONS",
    "CATASTROPHIC_CONDITIONS",
    "EFFECTIVENESS_DIMENSIONS",
    "ENFORCED_PROHIBITIONS",
    "INVARIANT_IDS",
    "MANDATORY_GATES",
    "NA_PERMITTED_BY_CONTRACT",
    "NEVER_OPTIMIZABLE",
    "OPTIMIZABLE_TARGETS",
    "PI8_CONTRACT",
    "PROMOTION_ACTION",
    "PROTECTED_INVARIANTS",
    "PROTECTED_METRICS",
    "PROTECTED_PATHS",
    "SCHEMA_VERSION",
    "STORE_SCHEMA_VERSION",
    "ActivationError",
    "ActivationMode",
    "ActivationRecord",
    "ActivationService",
    "ActivationState",
    "ActiveLearningState",
    "ApprovalCoordinator",
    "ApprovalError",
    "ApprovalRecord",
    "ApprovalState",
    "ApprovalStatus",
    "ArmOutcome",
    "AutonomousLearningSystem",
    "AuthorityExpansionAttempted",
    "BoundedOptimizer",
    "BudgetExhausted",
    "CandidateLifecycle",
    "CandidateLifecycleState",
    "CandidateRecord",
    "CapabilityCase",
    "CapabilitySuite",
    "CodeChangeGatekeeper",
    "CodeChangeProposal",
    "CodeChangeRefused",
    "CustomerOutcomeEvidence",
    "DurableLearningStore",
    "EffectivenessMeasurement",
    "EffectivenessReport",
    "EvaluationOutcome",
    "EvaluationReport",
    "EvidenceCollector",
    "EvidenceQuality",
    "EvidenceRef",
    "EvidenceSource",
    "ExecutionObservation",
    "ExperienceCollector",
    "ExperienceRecord",
    "ExperienceSource",
    "Experiment",
    "ExperimentArm",
    "ExperimentCapability",
    "ExperimentEngine",
    "ExperimentError",
    "ExperimentOutcome",
    "ExperimentRun",
    "GatewayDenialReason",
    "GatekeeperVerdict",
    "GateStatus",
    "Hypothesis",
    "HypothesisGenerator",
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
    "LearningClass",
    "LearningCycle",
    "LearningLifecycleService",
    "LearningLineage",
    "LearningOverlay",
    "LearningRecordCorrupt",
    "LearningRecordNotFound",
    "LearningScope",
    "LearningScopeKind",
    "LearningSignal",
    "LearningTelemetry",
    "LearningTelemetry19B3",
    "OptimizationRefused",
    "OverlayResolution",
    "PromotionConflict",
    "PromotionError",
    "PromotionRecord",
    "PromotionService",
    "PromotionState",
    "ProtectedInvariant",
    "ProposalDecision",
    "ProposalGateway",
    "ProposalOutcome",
    "RecursiveImprovement",
    "RecoveryAction",
    "RecoveryReconciler",
    "RecoveryReport",
    "RecoveryState",
    "RegressionEvaluator",
    "RegressionMonitor",
    "RegressionPolicy",
    "RegressionReport",
    "RegressionSeverity",
    "ResourceBudget",
    "ResourceGovernor",
    "Reward",
    "RewardLedger",
    "RewardPolarity",
    "RewardRejected",
    "RollbackError",
    "RollbackHandle",
    "RollbackOutcome",
    "RollbackRecord",
    "ShadowComparison",
    "SignalClass",
    "SignalExtractor",
    "SignalPolarity",
    "TelemetryCollector",
    "TestOutcome",
    "TransferEvaluator",
    "TransferPolicy",
    "TransferRefused",
    "TransferRequest",
    "TransferVerdict",
    "ValidationState",
    "ValidationSummary",
    "ValidationTruth",
    "assert_no_authority_expansion",
    "assert_no_implicit_generalization",
    "check_preservation",
    "derive_confidence",
    "disqualifying_signal",
    "measure_effectiveness",
    "negative_signal",
    "positive_signal",
]