"""
AutoForge Execution Platform — Phase 10.

Autonomous engineering execution platform coordinating workers, engineering loops,
command execution, deterministic evaluation, failure diagnosis, repair, artifact
pipelines, and HITL governance.

Public API
----------
Engine:
    ExecutionEngine, ExecutionEngineConfig

Worker & Dispatcher:
    EngineeringWorker, WorkerDispatcher, WorkerState, WorkerStatus, WorkerType

Environment & Commands:
    WorkspaceEnvironment, CommandSpec, CommandResult

Engineering Loop & Evaluation:
    EngineeringLoop, LoopConfig, LoopStatus, LoopIterationRecord
    EvaluationEngine, EvaluationResult, EvaluationStatus, DeterministicCheckResult, TestResultSummary

Diagnosis & AI:
    FailureDiagnoser, DiagnosisReport, RepairStrategy
    AIEngineeringProvider, AIInfrastructureAdapter

Artifacts:
    ArtifactPipeline, ArtifactRecord, ArtifactType, ArtifactProvenance

Governance:
    ExecutionGovernance, GovernancePolicy, ConsequentialActionType

Events & Recovery:
    ExecutionEvents, ExecutionRecovery

Errors:
    ExecutionError, WorkerError, WorkerNotFoundError, WorkerCancelledError
    DispatchError, ConcurrencyLimitExceededError, EnvironmentError
    CommandTimeoutError, SecurityViolationError, EvaluationError
    LoopError, LoopIterationLimitExceededError, LoopTimeoutError
    ArtifactError, GovernanceError, GovernanceApprovalRequired
"""

from __future__ import annotations

from autoforge_execution.ai_adapter import AIEngineeringProvider, AIInfrastructureAdapter
from autoforge_execution.artifacts import ArtifactPipeline
from autoforge_execution.context import ExecutionContext
from autoforge_execution.diagnosis import FailureDiagnoser
from autoforge_execution.dispatcher import WorkerDispatcher
from autoforge_execution.engine import ExecutionEngine, ExecutionEngineConfig
from autoforge_execution.environment import WorkspaceEnvironment
from autoforge_execution.errors import (
    ArtifactError,
    CommandTimeoutError,
    ConcurrencyLimitExceededError,
    DispatchError,
    EnvironmentError,
    EvaluationError,
    ExecutionError,
    GovernanceApprovalRequired,
    GovernanceError,
    LoopError,
    LoopIterationLimitExceededError,
    LoopTimeoutError,
    SecurityViolationError,
    WorkerCancelledError,
    WorkerError,
    WorkerNotFoundError,
)
from autoforge_execution.evaluation import EvaluationEngine, parse_test_output
from autoforge_execution.events import ExecutionEvents
from autoforge_execution.governance import ExecutionGovernance
from autoforge_execution.loop import EngineeringLoop
from autoforge_execution.models import (
    ArtifactProvenance,
    ArtifactRecord,
    ArtifactType,
    CommandResult,
    CommandSpec,
    ConsequentialActionType,
    DeterministicCheckResult,
    DiagnosisReport,
    EvaluationResult,
    EvaluationStatus,
    GovernancePolicy,
    LoopConfig,
    LoopIterationRecord,
    LoopStatus,
    RepairStrategy,
    TestResultSummary,
    WorkerState,
    WorkerStatus,
    WorkerType,
)
from autoforge_execution.recovery import ExecutionRecovery
from autoforge_execution.worker import EngineeringWorker

__version__ = "0.1.0"

from autoforge_execution.sandbox import (
    CleanupPolicy,
    CleanupReport,
    CleanupStatus,
    ContainerSandboxProvider,
    DockerSandboxProvider,
    FilesystemPolicy,
    LocalRestrictedSandboxProvider,
    NetworkMode,
    NetworkPolicy,
    PodmanSandboxProvider,
    PolicyValidator,
    PolicyViolationError,
    ProcessPolicy,
    ResourceLimits,
    ResourceUsage,
    SandboxLifecycleManager,
    SandboxProvider,
    SandboxRuntimeUnavailableError,
    SandboxedWorkspaceEnvironment,
    SecretPolicy,
    SecurityProfile,
    TerminationReason,
    VerificationState,
    WorkloadLifecycleState,
    WorkloadReaper,
    WorkloadResult,
    WorkloadSandboxManager,
    WorkloadSpec,
)

__all__ = [
    # Engine
    "ExecutionEngine",
    "ExecutionEngineConfig",
    # Worker & Dispatcher
    "EngineeringWorker",
    "WorkerDispatcher",
    "WorkerState",
    "WorkerStatus",
    "WorkerType",
    # Environment & Commands
    "WorkspaceEnvironment",
    "CommandSpec",
    "CommandResult",
    # Context
    "ExecutionContext",
    # Engineering Loop & Evaluation
    "EngineeringLoop",
    "LoopConfig",
    "LoopStatus",
    "LoopIterationRecord",
    "EvaluationEngine",
    "EvaluationResult",
    "EvaluationStatus",
    "DeterministicCheckResult",
    "TestResultSummary",
    "parse_test_output",
    # Diagnosis & AI
    "FailureDiagnoser",
    "DiagnosisReport",
    "RepairStrategy",
    "AIEngineeringProvider",
    "AIInfrastructureAdapter",
    # Artifacts
    "ArtifactPipeline",
    "ArtifactRecord",
    "ArtifactType",
    "ArtifactProvenance",
    # Governance
    "ExecutionGovernance",
    "GovernancePolicy",
    "ConsequentialActionType",
    # Events & Recovery
    "ExecutionEvents",
    "ExecutionRecovery",
    # Errors
    "ExecutionError",
    "WorkerError",
    "WorkerNotFoundError",
    "WorkerCancelledError",
    "DispatchError",
    "ConcurrencyLimitExceededError",
    "EnvironmentError",
    "CommandTimeoutError",
    "SecurityViolationError",
    "EvaluationError",
    "LoopError",
    "LoopIterationLimitExceededError",
    "LoopTimeoutError",
    "ArtifactError",
    "GovernanceError",
    "GovernanceApprovalRequired",
    # Sandbox (Phase 18-I)
    "WorkloadSandboxManager",
    "WorkloadSpec",
    "WorkloadResult",
    "WorkloadReaper",
    "SandboxLifecycleManager",
    "SandboxedWorkspaceEnvironment",
    "SandboxProvider",
    "LocalRestrictedSandboxProvider",
    "ContainerSandboxProvider",
    "PodmanSandboxProvider",
    "DockerSandboxProvider",
    "SandboxRuntimeUnavailableError",
    "PolicyValidator",
    "PolicyViolationError",
    "SecurityProfile",
    "FilesystemPolicy",
    "NetworkPolicy",
    "NetworkMode",
    "ProcessPolicy",
    "ResourceLimits",
    "SecretPolicy",
    "CleanupPolicy",
    "CleanupReport",
    "CleanupStatus",
    "ResourceUsage",
    "TerminationReason",
    "VerificationState",
    "WorkloadLifecycleState",
]
