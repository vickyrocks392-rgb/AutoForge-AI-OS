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
"""

from autoforge_learning.evidence import EvidenceCollector
from autoforge_learning.gateway import (
    GatewayDenialReason,
    ProposalDecision,
    ProposalGateway,
    ProposalOutcome,
)
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
from autoforge_learning.signals import (
    derive_confidence,
    disqualifying_signal,
    negative_signal,
    positive_signal,
)

__all__ = [
    "SCHEMA_VERSION",
    "ApprovalState",
    "EvidenceCollector",
    "EvidenceQuality",
    "EvidenceRef",
    "EvidenceSource",
    "ExperienceRecord",
    "GatewayDenialReason",
    "LearningAuthority",
    "LearningBase",
    "LearningCandidate",
    "LearningScope",
    "LearningScopeKind",
    "LearningSignal",
    "ProposalDecision",
    "ProposalGateway",
    "ProposalOutcome",
    "SignalPolarity",
    "TestOutcome",
    "ValidationState",
    "ValidationSummary",
    "ValidationTruth",
    "derive_confidence",
    "disqualifying_signal",
    "negative_signal",
    "positive_signal",
]