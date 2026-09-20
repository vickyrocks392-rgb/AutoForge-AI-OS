"""AutoForge Runtime — Runtime State Manager.

Implements the Runtime State Manager Specification v1.0.
"""

from __future__ import annotations

from autoforge_runtime.checkpoint_manager import (
    CheckpointCleaner,
    CheckpointCreator,
    CheckpointManager,
    CheckpointRestorer,
)
from autoforge_runtime.concurrency import ConcurrencyController, ResolutionResult
from autoforge_runtime.event_publisher import EventFormatter, EventPublisher, EventRouter
from autoforge_runtime.exceptions import (
    CheckpointError,
    DuplicateEntityError,
    EntityNotFoundError,
    InvalidEntityTypeError,
    InvalidStateError,
    InvalidTransitionError,
    LifecycleError,
    PersistenceError,
    RecoveryError,
    RuntimeError,
    SnapshotError,
    StateError,
    ValidationError,
    VersionConflictError,
)
from autoforge_runtime.execution_store import (
    EXECUTION_ID_NAMESPACE,
    DurableExecutionStore,
    ExecutionReconstruction,
    default_owner_id,
    execution_id_for_key,
    execution_key_for_task,
)
from autoforge_runtime.workflow_store import (
    DurableWorkflowStore,
    default_workflow_owner_id,
)
from autoforge_runtime.idempotency import (
    IDEMPOTENT_OPERATION_NAMESPACE,
    AmbiguousSideEffectError,
    ClaimResult,
    ConcurrentOperationError,
    DurableIdempotencyStore,
    FingerprintConflictError,
    IdempotencyError,
    OperationFailedError,
    compute_request_fingerprint,
    default_operation_owner_id,
    derive_idempotency_key,
    derive_task_idempotency_key,
    operation_id_for_key,
    sanitize_payload,
)
from autoforge_runtime.side_effects import SideEffectExecutor
from autoforge_runtime.interfaces import (
    EventSubscriptionInterface,
    QueryInterface,
    StateReadInterface,
    StateWriteInterface,
)
from autoforge_runtime.lifecycle import RuntimeLifecycle
from autoforge_runtime.models import (
    ApprovalRecord,
    CheckpointState,
    CheckpointStatus,
    CheckpointType,
    EngineeringLoopState,
    EntityType,
    FailureRecord,
    FailureRecoverability,
    FailureSeverity,
    FailureSource,
    LoopStatus,
    LoopType,
    ProgressMetrics,
    ProjectState,
    ProjectStatus,
    RecoveryState,
    RecoveryStatus,
    RestoreType,
    RuntimeMetadata,
    RuntimeStatus,
    StateModel,
    StateTransition,
    TaskState,
    TimeRange,
    TransitionResult,
    WorkerState,
    WorkerStatus,
    WorkflowState,
    WorkflowStatus,
    ExecutionStatus,
    AttemptStatus,
    OperationStatus,
    IdempotentOperationState,
    OPERATION_RECORD_VERSION,
)
from autoforge_runtime.persistence import (
    CacheLayer,
    HistoryStore,
    PersistenceLayer,
    PersistentStore,
    SQLiteStorage,
)
from autoforge_runtime.query_engine import (
    AggregationEngine,
    FilterEngine,
    QueryEngine,
    QueryParser,
)
from autoforge_runtime.recovery_manager import RecoveryManager
from autoforge_runtime.snapshots import (
    RuntimeSnapshot,
    create_snapshot,
    restore_snapshot,
)
from autoforge_runtime.state_manager import RuntimeStateManager
from autoforge_runtime.transition_engine import StateTransitionEngine
from autoforge_runtime.validation import (
    ValidationErrorCode,
    ValidationResult,
    get_allowed_checkpoint_transitions,
    get_allowed_loop_transitions,
    get_allowed_project_transitions,
    get_allowed_task_transitions,
    get_allowed_worker_transitions,
    get_allowed_workflow_transitions,
    is_checkpoint_terminal,
    is_loop_terminal,
    is_project_terminal,
    is_task_terminal,
    is_workflow_terminal,
    validate_checkpoint_transition,
    validate_loop_transition,
    validate_project_transition,
    validate_task_transition,
    validate_worker_transition,
    validate_workflow_transition,
    validate_operation_transition,
    get_allowed_operation_transitions,
    is_operation_terminal,
    is_operation_recoverable,
)

__all__ = [
    "RuntimeStateManager",
    "ProjectState", "ProjectStatus", "WorkflowState", "WorkflowStatus",
    "ExecutionStatus", "AttemptStatus",
    "EngineeringLoopState", "LoopStatus", "LoopType", "TaskState",
    "WorkerState", "WorkerStatus", "CheckpointState", "CheckpointStatus",
    "CheckpointType", "RecoveryState", "RecoveryStatus", "RuntimeMetadata",
    "RuntimeStatus", "StateModel", "StateTransition", "TransitionResult",
    "ProgressMetrics", "TimeRange", "EntityType", "RestoreType",
    "ApprovalRecord", "FailureRecord", "FailureSource", "FailureSeverity",
    "FailureRecoverability",
    "StateTransitionEngine",
    "ValidationResult", "ValidationErrorCode",
    "validate_project_transition", "validate_workflow_transition",
    "validate_loop_transition", "validate_task_transition",
    "validate_worker_transition", "validate_checkpoint_transition",
    "get_allowed_project_transitions", "get_allowed_workflow_transitions",
    "get_allowed_loop_transitions", "get_allowed_task_transitions",
    "get_allowed_worker_transitions", "get_allowed_checkpoint_transitions",
    "is_project_terminal", "is_workflow_terminal", "is_loop_terminal",
    "is_task_terminal", "is_checkpoint_terminal",
    "ConcurrencyController", "ResolutionResult",
    "PersistenceLayer", "CacheLayer", "PersistentStore", "HistoryStore", "SQLiteStorage",
    "CheckpointManager", "CheckpointCreator", "CheckpointRestorer", "CheckpointCleaner",
    "QueryEngine", "QueryParser", "FilterEngine", "AggregationEngine",
    "EventPublisher", "EventFormatter", "EventRouter",
    "RuntimeLifecycle", "RecoveryManager",
    "RuntimeSnapshot", "create_snapshot", "restore_snapshot",
    "StateWriteInterface", "StateReadInterface", "QueryInterface", "EventSubscriptionInterface",
    "RuntimeError", "StateError", "InvalidTransitionError", "SnapshotError",
    "EntityNotFoundError", "DuplicateEntityError", "VersionConflictError",
    "ValidationError", "PersistenceError", "InvalidStateError",
    "InvalidEntityTypeError", "CheckpointError", "RecoveryError", "LifecycleError",
    "DurableExecutionStore", "ExecutionReconstruction", "default_owner_id",
    "execution_id_for_key", "execution_key_for_task", "EXECUTION_ID_NAMESPACE",
    "DurableWorkflowStore", "default_workflow_owner_id",
    "OperationStatus", "IdempotentOperationState", "OPERATION_RECORD_VERSION",
    "DurableIdempotencyStore", "ClaimResult", "SideEffectExecutor",
    "IDEMPOTENT_OPERATION_NAMESPACE", "default_operation_owner_id",
    "derive_idempotency_key", "derive_task_idempotency_key", "operation_id_for_key",
    "compute_request_fingerprint", "sanitize_payload",
    "IdempotencyError", "FingerprintConflictError", "ConcurrentOperationError",
    "AmbiguousSideEffectError", "OperationFailedError",
    "validate_operation_transition", "get_allowed_operation_transitions",
    "is_operation_terminal", "is_operation_recoverable",
]