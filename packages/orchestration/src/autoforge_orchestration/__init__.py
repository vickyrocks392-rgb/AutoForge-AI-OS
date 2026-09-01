"""AutoForge Orchestration Platform — Phase 18.

Composes the existing AutoForge subsystems (workforce, workflows, execution,
review, artifacts, ai_infrastructure, security, knowledge_platform, event
platform, observability) into a durable, observable, bounded autonomous
engineering orchestration engine.

Public API:

- :class:`OrchestrationEngine` — the main entry point.
- :class:`GREENFIELD_WORKFLOW_DEFINITION` / :class:`LEGACY_WORKFLOW_DEFINITION`
  -- canonical workflow definitions.
- State machine: :func:`validate_stage_transition`, :func:`is_stage_terminal`.
- Domain models: stage definitions, execution state, contracts, verdicts.
- Exceptions: :class:`OrchestrationError` and subclasses.
"""

from autoforge_orchestration.models import (
    # Enums
    RunMode,
    StageKind,
    StageStatus,
    WorkflowStatus,
    Verdict,
    ReviewVerdict,
    FailureType,
    HITLStatus,
    DeploymentStatus,
    # Definition-time
    HITLGateSpec,
    StageDefinition,
    WorkflowDefinition,
    # Contracts
    WorkerAssignment,
    ModelDecision,
    WorkerContractInput,
    WorkerContractOutput,
    StageEvaluationVerdict,
    StructuredFailureContext,
    DiagnosisOutcome,
    ReviewGateResult,
    HITLGateRecord,
    DeploymentResult,
    # Execution state
    ProjectExecutionMetrics,
    StageExecutionState,
    ProjectExecutionState,
)
from autoforge_orchestration.states import (
    validate_stage_transition,
    get_allowed_stage_transitions,
    is_stage_terminal,
    is_stage_successful_terminal,
    is_stage_failed_terminal,
    transition_stage,
)
from autoforge_orchestration.workflow_definitions import (
    GREENFIELD_WORKFLOW_DEFINITION,
    LEGACY_WORKFLOW_DEFINITION,
    STAGE_KIND_TO_WORKER_TYPE,
    STAGE_KIND_TO_CAPABILITIES,
    GREENFIELD_STAGE_ORDER,
    LEGACY_STAGE_ORDER,
)
from autoforge_orchestration.persistence import (
    StatePersistence,
    SnapshotStore,
)
from autoforge_orchestration.security import (
    SecurityBoundaryGuard,
    VerificationCommandError,
)
from autoforge_orchestration.errors import (
    OrchestrationError,
    WorkflowStateError,
    StageStateError,
    WorkerAssignmentError,
    ModelRoutingError,
    RectificationLimitError,
    HITLGateError,
    DeploymentUnavailableError,
    PersistenceError,
    SecurityBoundaryError,
)
from autoforge_orchestration.governance_service import (
    GovernanceReportService,
    GovernanceReport,
    GovernanceEvidence,
    GovernanceDecision,
    StageEvidence,
    ReviewEvidence,
    HITLEvidence,
    AuditEvidence,
)


from autoforge_orchestration.orchestrator import OrchestrationEngine

__all__ = [
    # Enums
    "RunMode",
    "StageKind",
    "StageStatus",
    "WorkflowStatus",
    "Verdict",
    "ReviewVerdict",
    "FailureType",
    "HITLStatus",
    "DeploymentStatus",
    # Definition-time
    "HITLGateSpec",
    "StageDefinition",
    "WorkflowDefinition",
    "GREENFIELD_WORKFLOW_DEFINITION",
    "LEGACY_WORKFLOW_DEFINITION",
    "STAGE_KIND_TO_WORKER_TYPE",
    "STAGE_KIND_TO_CAPABILITIES",
    "GREENFIELD_STAGE_ORDER",
    "LEGACY_STAGE_ORDER",
    # Contracts
    "WorkerAssignment",
    "ModelDecision",
    "WorkerContractInput",
    "WorkerContractOutput",
    "StageEvaluationVerdict",
    "StructuredFailureContext",
    "DiagnosisOutcome",
    "ReviewGateResult",
    "HITLGateRecord",
    "DeploymentResult",
    # Execution state
    "ProjectExecutionMetrics",
    "StageExecutionState",
    "ProjectExecutionState",
    # State machine
    "validate_stage_transition",
    "get_allowed_stage_transitions",
    "is_stage_terminal",
    "is_stage_successful_terminal",
    "is_stage_failed_terminal",
    "transition_stage",
    # Orchestration
    "OrchestrationEngine",
    # Governance
    "GovernanceReportService",
    "GovernanceReport",
    "GovernanceEvidence",
    "GovernanceDecision",
    "StageEvidence",
    "ReviewEvidence",
    "HITLEvidence",
    "AuditEvidence",
    # Persistence
    "StatePersistence",
    "SnapshotStore",
    # Security
    "SecurityBoundaryGuard",
    "VerificationCommandError",
    # Errors
    "OrchestrationError",
    "WorkflowStateError",
    "StageStateError",
    "WorkerAssignmentError",
    "ModelRoutingError",
    "RectificationLimitError",
    "HITLGateError",
    "DeploymentUnavailableError",
    "PersistenceError",
    "SecurityBoundaryError",
]
