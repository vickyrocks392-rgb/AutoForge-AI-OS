"""
AutoForge Workflow Platform — Phase 9

Provides DAG-based workflow orchestration, dependency resolution, task scheduling,
retry policies, recovery, and HITL (Human-In-The-Loop) approval gate support.

Public API
----------
Workflow definitions:
    WorkflowDefinition, TaskDefinition, DependencyEdge
    ExecutionPolicy, RetryPolicy, RecoveryPolicy, ApprovalGatePolicy

DAG engine:
    WorkflowDAG, DAGNode, DAGValidationError, CycleDetectedError

Task state machine:
    WorkflowTaskStatus, WorkflowTaskState
    WorkflowStatus (see runtime; re-exported here for convenience)
    validate_workflow_task_transition

Queue:
    TaskQueue, QueueEntry, TaskPriority (from autoforge_models)

Scheduler:
    WorkflowScheduler, SchedulerConfig, SchedulingDecision

Workflow engine:
    WorkflowEngine, WorkflowHandle, WorkflowEngineConfig

Retry:
    RetryContext, BackoffStrategy, should_retry, compute_backoff

Recovery:
    WorkflowRecovery, RecoveryContext, WorkflowSnapshot

Approval gates:
    ApprovalGate, ApprovalDecision, ApprovalStatus

Errors:
    WorkflowError, WorkflowValidationError, WorkflowNotFoundError
    DependencyError, SchedulerError, QueueError, RetryLimitExceeded
    RecoveryError, ApprovalError
"""

from __future__ import annotations

from autoforge_workflows.approval import (
    ApprovalDecision,
    ApprovalGate,
    ApprovalOutcome,
    ApprovalStatus,
)
from autoforge_workflows.dag import (
    DAGNode,
    WorkflowDAG,
)
from autoforge_workflows.engine import (
    WorkflowEngine,
    WorkflowEngineConfig,
    WorkflowHandle,
)
from autoforge_workflows.errors import (
    ApprovalError,
    CycleDetectedError,
    DAGValidationError,
    DependencyError,
    QueueError,
    RecoveryError,
    RetryLimitExceeded,
    SchedulerError,
    WorkflowError,
    WorkflowNotFoundError,
    WorkflowValidationError,
)
from autoforge_workflows.models import (
    ApprovalGatePolicy,
    DependencyEdge,
    DependencyPolicy,
    ExecutionPolicy,
    FailureAction,
    RecoveryPolicy,
    RetryPolicy,
    TaskDefinition,
    WorkflowDefinition,
    WorkflowTaskState,
    WorkflowTaskStatus,
)
from autoforge_workflows.queue import QueueEntry, TaskQueue
from autoforge_workflows.recovery import (
    RecoveryContext,
    WorkflowRecovery,
    WorkflowSnapshot,
)
from autoforge_workflows.retry import (
    BackoffStrategy,
    RetryContext,
    compute_backoff,
    should_retry,
)
from autoforge_workflows.scheduler import (
    SchedulerConfig,
    SchedulingDecision,
    WorkflowScheduler,
)
from autoforge_workflows.reconstruction import WorkflowReconstructor
from autoforge_workflows.supervisor import StartupReconciliationReport, WorkflowSupervisor

__version__ = "0.1.0"

__all__ = [
    # Models
    "WorkflowDefinition",
    "TaskDefinition",
    "DependencyEdge",
    "DependencyPolicy",
    "ExecutionPolicy",
    "RetryPolicy",
    "RecoveryPolicy",
    "ApprovalGatePolicy",
    "FailureAction",
    "WorkflowTaskStatus",
    "WorkflowTaskState",
    # DAG
    "WorkflowDAG",
    "DAGNode",
    "DAGValidationError",
    "CycleDetectedError",
    # State machine
    "validate_workflow_task_transition",
    # Queue
    "TaskQueue",
    "QueueEntry",
    # Scheduler
    "WorkflowScheduler",
    "SchedulerConfig",
    "SchedulingDecision",
    # Engine
    "WorkflowEngine",
    "WorkflowEngineConfig",
    "WorkflowHandle",
    # Retry
    "RetryContext",
    "BackoffStrategy",
    "should_retry",
    "compute_backoff",
    # Recovery & Reconstruction (Phase 18-J.3)
    "WorkflowRecovery",
    "RecoveryContext",
    "WorkflowSnapshot",
    "WorkflowReconstructor",
    "WorkflowSupervisor",
    "StartupReconciliationReport",
    # Approval
    "ApprovalGate",
    "ApprovalDecision",
    "ApprovalStatus",
    "ApprovalOutcome",
    # Errors
    "WorkflowError",
    "WorkflowValidationError",
    "WorkflowNotFoundError",
    "DependencyError",
    "SchedulerError",
    "QueueError",
    "RetryLimitExceeded",
    "RecoveryError",
    "ApprovalError",
]
