"""
Runtime State Models — define the structure and semantics of all runtime state entities.

This module implements the state models defined in the Runtime State Manager
Specification v1.0, Section 8-14. It defines the structure for:

    - Project State
    - Workflow State
    - Engineering Loop State
    - Task State
    - Worker State
    - Checkpoint State
    - Recovery State
    - Runtime Metadata
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


def _utc_now() -> datetime:
    """Return the current UTC datetime with timezone awareness."""
    return datetime.now(timezone.utc)


def _new_uuid() -> uuid.UUID:
    """Return a new UUID v4."""
    return uuid.uuid4()


# ── Enumerations ─────────────────────────────────────────────────────────


class ProjectStatus(str, Enum):
    """Project lifecycle status."""

    CREATED = "created"
    PLANNING = "planning"
    RUNNING = "running"
    REVIEWING = "reviewing"
    PAUSED = "paused"
    COMPLETING = "completing"
    FINISHED = "finished"
    FAILED = "failed"
    CANCELLED = "cancelled"


class WorkflowStatus(str, Enum):
    """Workflow execution status."""

    CREATED = "created"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETING = "completing"
    FINISHED = "finished"
    FAILED = "failed"
    CANCELLED = "cancelled"
    INTERRUPTED = "interrupted"


class LoopStatus(str, Enum):
    """Engineering loop lifecycle status."""

    IDLE = "idle"
    PLAN = "plan"
    EXECUTE = "execute"
    REVIEW = "review"
    COMPLETE = "complete"
    REMEDIATE = "remediate"
    ESCALATE = "escalate"
    RESUME = "resume"
    FAILED = "failed"


class LoopType(str, Enum):
    """Engineering loop type."""

    RESEARCH = "research"
    ARCHITECTURE = "architecture"
    CODING = "coding"
    REVIEW = "review"
    TESTING = "testing"
    DEPLOYMENT = "deployment"
    LEARNING = "learning"


class WorkerStatus(str, Enum):
    """Worker availability status."""

    IDLE = "idle"
    BUSY = "busy"
    DRAINING = "draining"
    OFFLINE = "offline"


class CheckpointStatus(str, Enum):
    """Checkpoint lifecycle status."""

    ACTIVE = "active"
    RESTORED = "restored"
    OBSOLETE = "obsolete"


class CheckpointType(str, Enum):
    """Checkpoint type."""

    AUTOMATIC = "automatic"
    MANUAL = "manual"
    RECOVERY = "recovery"
    ROLLBACK = "rollback"
    RESUME = "resume"


class RestoreType(str, Enum):
    """Checkpoint restoration type."""

    FULL = "full"
    PARTIAL = "partial"


class EntityType(str, Enum):
    """Runtime state entity types."""

    PROJECT = "project"
    WORKFLOW = "workflow"
    LOOP = "loop"
    TASK = "task"
    WORKER = "worker"
    CHECKPOINT = "checkpoint"
    RECOVERY = "recovery"
    EXECUTION = "execution"
    EXECUTION_ATTEMPT = "execution_attempt"
    EXECUTION_CHECKPOINT = "execution_checkpoint"


# ── Durable execution identity (Phase 18-J.2) ─────────────────────────────

#: Revision of the durable execution record layout (Phase 18-J.2).
EXECUTION_RECORD_VERSION = 1


class ExecutionStatus(str, Enum):
    """Durable lifecycle status of one logical execution.

    A *logical execution* is the durable unit of work (for example one task of
    one workflow instance). Retries do **not** create a new logical execution;
    each retry is recorded as a new :class:`ExecutionAttemptState` of the same
    execution.

    Deterministic transitions (Section 18.7 — execution rules):

        created     -> running | cancelled
        running     -> completed | failed | cancelled | interrupted
        interrupted -> running | failed | cancelled   (running = controlled resume)
        completed   (terminal)
        failed      (terminal)
        cancelled   (terminal)

    ``interrupted`` is deliberately *not* ``failed``: an execution that was
    running when its process died must stay recoverable so that a later phase
    (18-J.3) can attempt a controlled resume instead of blind re-dispatch.
    """

    CREATED = "created"
    """Recorded durably; no attempt has started yet."""

    RUNNING = "running"
    """At least one attempt has started; the execution is in flight."""

    COMPLETED = "completed"
    """An attempt committed success (terminal)."""

    FAILED = "failed"
    """The execution exhausted its attempts and is terminally failed."""

    CANCELLED = "cancelled"
    """The execution was cancelled (terminal)."""

    INTERRUPTED = "interrupted"
    """The owning process disappeared while the execution was in flight.

    Recoverable: a later phase may resume it. It is never reported as
    completed and is never silently re-dispatched.
    """


class AttemptStatus(str, Enum):
    """Durable lifecycle status of one execution attempt.

    Deterministic transitions:

        started   -> completed | failed | interrupted | cancelled
        completed (terminal)
        failed    (terminal)
        interrupted (terminal for this attempt; the *execution* may resume)
        cancelled (terminal)
    """

    STARTED = "started"
    """The attempt was durably recorded before any work started."""

    COMPLETED = "completed"
    """The attempt committed success (terminal)."""

    FAILED = "failed"
    """The attempt committed failure (terminal)."""

    INTERRUPTED = "interrupted"
    """The attempt was in flight when its owning process disappeared."""

    CANCELLED = "cancelled"
    """The attempt was cancelled (terminal)."""


class RuntimeStatus(str, Enum):
    """Runtime State Manager lifecycle status."""

    CREATED = "created"
    STARTING = "starting"
    READY = "ready"
    PROCESSING = "processing"
    PAUSED = "paused"
    STOPPING = "stopping"
    STOPPED = "stopped"


class RecoveryStatus(str, Enum):
    """Recovery operation status."""

    NORMAL = "normal"
    FAILURE_DETECTED = "failure_detected"
    FAILURE_CLASSIFIED = "failure_classified"
    RECOVERABLE = "recoverable"
    NON_RECOVERABLE = "non_recoverable"
    UNKNOWN = "unknown"
    FATAL = "fatal"
    CHECKPOINT_RESTORED = "checkpoint_restored"
    RESUMED = "resumed"
    HUMAN_INTERVENTION = "human_intervention"
    HUMAN_NOTIFIED = "human_notified"
    RETRY = "retry"
    EXECUTION_RESUMED = "execution_resumed"


class FailureSeverity(str, Enum):
    """Failure severity classification."""

    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"
    FATAL = "fatal"


class FailureSource(str, Enum):
    """Failure source classification."""

    PERSISTENCE = "persistence"
    EVENT_BUS = "event_bus"
    INTERNAL = "internal"
    RESOURCE_EXHAUSTION = "resource_exhaustion"
    NETWORK = "network"


class FailureRecoverability(str, Enum):
    """Failure recoverability classification."""

    RECOVERABLE = "recoverable"
    NON_RECOVERABLE = "non_recoverable"
    UNKNOWN = "unknown"


# ── Base State Model ─────────────────────────────────────────────────────


class StateModel(BaseModel):
    """Base class for all runtime state models."""

    model_config = ConfigDict(
        extra="forbid",
        populate_by_name=True,
        frozen=True,
        use_enum_values=False,
    )

    version: int = Field(
        default=1,
        ge=1,
        description="State version for optimistic concurrency control.",
    )
    created_at: datetime = Field(
        default_factory=_utc_now,
        description="When this state was created.",
    )
    updated_at: datetime = Field(
        default_factory=_utc_now,
        description="When this state was last modified.",
    )


# ── Project State ────────────────────────────────────────────────────────


class ApprovalRecord(BaseModel):
    """A record of an approval decision."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    approval_id: uuid.UUID = Field(default_factory=_new_uuid)
    decision: str = Field(..., min_length=1)
    decided_by: str | None = Field(default=None)
    decided_at: datetime = Field(default_factory=_utc_now)
    reason: str | None = Field(default=None, max_length=4096)
    metadata: dict[str, Any] = Field(default_factory=dict)


class FailureRecord(BaseModel):
    """A record of a failure and its recovery."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    failure_id: uuid.UUID = Field(default_factory=_new_uuid)
    source: FailureSource = Field(...)
    severity: FailureSeverity = Field(...)
    recoverability: FailureRecoverability = Field(...)
    error_code: str | None = Field(default=None, max_length=128)
    error_message: str = Field(..., min_length=1, max_length=8192)
    occurred_at: datetime = Field(default_factory=_utc_now)
    recovered_at: datetime | None = Field(default=None)
    recovery_strategy: str | None = Field(default=None, max_length=256)
    checkpoint_id: uuid.UUID | None = Field(default=None)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ProjectState(StateModel):
    """Project state — the top-level container for all project-related state."""

    project_id: uuid.UUID = Field(default_factory=_new_uuid)
    status: ProjectStatus = Field(default=ProjectStatus.CREATED)
    request: dict[str, Any] = Field(default_factory=dict)
    configuration: dict[str, Any] = Field(default_factory=dict)
    intent_analysis: dict[str, Any] = Field(default_factory=dict)
    strategic_plan: dict[str, Any] = Field(default_factory=dict)
    executable_workflow: dict[str, Any] = Field(default_factory=dict)
    workflow_version: uuid.UUID | None = Field(default=None)
    current_loop: str | None = Field(default=None, max_length=256)
    loop_state: dict[str, Any] = Field(default_factory=dict)
    task_graph_id: uuid.UUID | None = Field(default=None)
    task_count: int = Field(default=0, ge=0)
    completed_count: int = Field(default=0, ge=0)
    failed_count: int = Field(default=0, ge=0)
    running_count: int = Field(default=0, ge=0)
    progress: float = Field(default=0.0, ge=0.0, le=100.0)
    current_checkpoint_id: uuid.UUID | None = Field(default=None)
    started_at: datetime | None = Field(default=None)
    estimated_duration: timedelta | None = Field(default=None)
    actual_duration: timedelta | None = Field(default=None)
    estimated_cost: float = Field(default=0.0, ge=0.0)
    actual_cost: float = Field(default=0.0, ge=0.0)
    acceptance_criteria: dict[str, Any] = Field(default_factory=dict)
    artifacts: list[uuid.UUID] = Field(default_factory=list)
    approval_history: list[ApprovalRecord] = Field(default_factory=list)
    failure_history: list[FailureRecord] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    finished_at: datetime | None = Field(default=None)


# ── Workflow State ───────────────────────────────────────────────────────


class WorkflowState(StateModel):
    """Workflow state — represents the execution state of a workflow."""

    workflow_id: uuid.UUID = Field(default_factory=_new_uuid)
    project_id: uuid.UUID = Field(...)
    status: WorkflowStatus = Field(default=WorkflowStatus.CREATED)
    version: uuid.UUID = Field(default_factory=_new_uuid)
    state_version: int = Field(default=1, ge=1)
    owner_id: str | None = Field(default=None, max_length=256)
    recoverable: bool = Field(default=False)
    definition: dict[str, Any] = Field(default_factory=dict)
    task_graph: dict[str, Any] = Field(default_factory=dict)
    task_count: int = Field(default=0, ge=0)
    completed_count: int = Field(default=0, ge=0)
    failed_count: int = Field(default=0, ge=0)
    running_count: int = Field(default=0, ge=0)
    blocked_count: int = Field(default=0, ge=0)
    progress: float = Field(default=0.0, ge=0.0, le=100.0)
    current_task_id: uuid.UUID | None = Field(default=None)
    queues: dict[str, Any] = Field(default_factory=dict)
    dependencies: dict[str, Any] = Field(default_factory=dict)
    scheduling_policy: dict[str, Any] = Field(default_factory=dict)
    retry_policy: dict[str, Any] = Field(default_factory=dict)
    approval_policies: dict[str, Any] = Field(default_factory=dict)
    started_at: datetime | None = Field(default=None)
    estimated_duration: timedelta | None = Field(default=None)
    actual_duration: timedelta | None = Field(default=None)
    metadata: dict[str, Any] = Field(default_factory=dict)


# ── Engineering Loop State ───────────────────────────────────────────────


class EngineeringLoopState(StateModel):
    """Engineering loop state — represents the state of an engineering loop."""

    loop_id: uuid.UUID = Field(default_factory=_new_uuid)
    workflow_id: uuid.UUID = Field(...)
    project_id: uuid.UUID = Field(...)
    loop_type: LoopType = Field(...)
    status: LoopStatus = Field(default=LoopStatus.IDLE)
    iteration: int = Field(default=0, ge=0)
    max_iterations: int = Field(default=10, ge=1)
    input_artifacts: list[uuid.UUID] = Field(default_factory=list)
    output_artifacts: list[uuid.UUID] = Field(default_factory=list)
    review_findings: dict[str, Any] = Field(default_factory=dict)
    remediation_plan: dict[str, Any] = Field(default_factory=dict)
    assigned_workers: list[str] = Field(default_factory=list)
    assigned_models: dict[str, Any] = Field(default_factory=dict)
    retry_count: int = Field(default=0, ge=0)
    max_retries: int = Field(default=3, ge=0)
    started_at: datetime | None = Field(default=None)
    estimated_duration: timedelta | None = Field(default=None)
    actual_duration: timedelta | None = Field(default=None)
    estimated_cost: float = Field(default=0.0, ge=0.0)
    actual_cost: float = Field(default=0.0, ge=0.0)


# ── Task State ───────────────────────────────────────────────────────────


class TaskState(StateModel):
    """Task state — represents the state of a discrete task."""

    task_id: uuid.UUID = Field(default_factory=_new_uuid)
    project_id: uuid.UUID = Field(...)
    workflow_id: uuid.UUID | None = Field(default=None)
    loop_id: uuid.UUID | None = Field(default=None)
    task_type: str = Field(default="general", min_length=1, max_length=128)
    status: str = Field(default="pending")
    priority: str = Field(default="medium")
    assigned_worker: str | None = Field(default=None, max_length=128)
    assigned_worker_id: uuid.UUID | None = Field(default=None)
    assigned_model: str | None = Field(default=None, max_length=128)
    input_artifacts: list[uuid.UUID] = Field(default_factory=list)
    output_artifacts: list[uuid.UUID] = Field(default_factory=list)
    dependencies: list[uuid.UUID] = Field(default_factory=list)
    dependents: list[uuid.UUID] = Field(default_factory=list)
    retry_count: int = Field(default=0, ge=0)
    max_retries: int = Field(default=3, ge=0)
    approval_required: bool = Field(default=False)
    approval_id: uuid.UUID | None = Field(default=None)
    blocked_by: uuid.UUID | None = Field(default=None)
    error: dict[str, Any] = Field(default_factory=dict)
    result: dict[str, Any] = Field(default_factory=dict)
    started_at: datetime | None = Field(default=None)
    completed_at: datetime | None = Field(default=None)
    estimated_duration: timedelta | None = Field(default=None)
    actual_duration: timedelta | None = Field(default=None)
    estimated_cost: float = Field(default=0.0, ge=0.0)
    actual_cost: float = Field(default=0.0, ge=0.0)
    metadata: dict[str, Any] = Field(default_factory=dict)


# ── Worker State ─────────────────────────────────────────────────────────


class WorkerState(StateModel):
    """Worker state — represents the state of a worker."""

    worker_id: uuid.UUID = Field(default_factory=_new_uuid)
    worker_type: str = Field(..., min_length=1, max_length=128)
    status: WorkerStatus = Field(default=WorkerStatus.IDLE)
    current_task_id: uuid.UUID | None = Field(default=None)
    assigned_model: str | None = Field(default=None, max_length=128)
    capabilities: list[str] = Field(default_factory=list)
    capacity: int = Field(default=1, ge=1)
    current_load: int = Field(default=0, ge=0)
    started_at: datetime | None = Field(default=None)
    task_count: int = Field(default=0, ge=0)
    total_cost: float = Field(default=0.0, ge=0.0)
    success_rate: float = Field(default=1.0, ge=0.0, le=1.0)
    average_duration: timedelta | None = Field(default=None)
    last_heartbeat: datetime | None = Field(default=None)
    metadata: dict[str, Any] = Field(default_factory=dict)


# ── Checkpoint State ─────────────────────────────────────────────────────


class CheckpointState(StateModel):
    """Checkpoint state — represents a state snapshot."""

    checkpoint_id: uuid.UUID = Field(default_factory=_new_uuid)
    project_id: uuid.UUID = Field(...)
    checkpoint_type: CheckpointType = Field(...)
    status: CheckpointStatus = Field(default=CheckpointStatus.ACTIVE)
    label: str = Field(default="", max_length=256)
    description: str = Field(default="", max_length=4096)
    state_snapshot: dict[str, Any] = Field(default_factory=dict)
    parent_checkpoint_id: uuid.UUID | None = Field(default=None)
    child_checkpoint_ids: list[uuid.UUID] = Field(default_factory=list)
    created_by: str = Field(default="system", max_length=128)
    restored_at: datetime | None = Field(default=None)
    restored_by: str | None = Field(default=None, max_length=128)
    size: int = Field(default=0, ge=0)
    metadata: dict[str, Any] = Field(default_factory=dict)


# ── Recovery State ───────────────────────────────────────────────────────


class RecoveryState(StateModel):
    """Recovery state — represents the state of a recovery operation."""

    recovery_id: uuid.UUID = Field(default_factory=_new_uuid)
    project_id: uuid.UUID | None = Field(default=None)
    status: RecoveryStatus = Field(default=RecoveryStatus.NORMAL)
    strategy: str | None = Field(default=None, max_length=256)
    progress: float = Field(default=0.0, ge=0.0, le=100.0)
    source: FailureSource | None = Field(default=None)
    severity: FailureSeverity | None = Field(default=None)
    recoverability: FailureRecoverability | None = Field(default=None)
    error_code: str | None = Field(default=None, max_length=128)
    error_message: str | None = Field(default=None, max_length=8192)
    checkpoint_id: uuid.UUID | None = Field(default=None)
    started_at: datetime | None = Field(default=None)
    completed_at: datetime | None = Field(default=None)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ExecutionAttemptState(StateModel):
    """Durable record of one attempt of one logical execution.

    Attempt identity is distinct from execution identity: retry ``N+1`` of
    execution ``E`` is a new attempt of ``E``, never a new execution.

    The record is written *before* the attempt does any work (``started``) and
    is only advanced when the outcome is durably committed, so after a restart
    the system can answer "was attempt N completed, failed or interrupted?"
    from durable storage alone — never from in-memory worker state.
    """

    attempt_id: uuid.UUID = Field(default_factory=_new_uuid)
    execution_id: uuid.UUID = Field(...)
    attempt_number: int = Field(..., ge=1)
    status: AttemptStatus = Field(default=AttemptStatus.STARTED)

    worker_id: str | None = Field(default=None, max_length=256)
    worker_type: str | None = Field(default=None, max_length=128)
    previous_attempt_id: uuid.UUID | None = Field(default=None)
    """Attempt that this attempt retries, when retry metadata is available."""

    max_attempts: int | None = Field(default=None, ge=1)
    """Retry budget in force for this work unit, when the caller knows it."""

    last_checkpoint_id: uuid.UUID | None = Field(default=None)
    last_checkpoint_sequence: int | None = Field(default=None, ge=1)

    started_at: datetime | None = Field(default=None)
    completed_at: datetime | None = Field(default=None)

    failure: FailureRecord | None = Field(default=None)
    result: dict[str, Any] = Field(default_factory=dict)
    """Structured, inspectable outcome summary (never an opaque object blob)."""

    schema_version: int = Field(default=EXECUTION_RECORD_VERSION, ge=1)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ExecutionCheckpointState(StateModel):
    """Durable execution boundary (checkpoint) of one attempt.

    A boundary is a *committed truth edge*: it is written only on a meaningful
    recovery boundary (a work step whose result is durably known), never on a
    timer. ``sequence`` is monotonic per execution, so the system can always
    answer "what was the last known durable boundary of execution E?".

    What a boundary guarantees: the facts recorded here were committed before
    the crash, so recovery may treat everything up to it as done.

    What a boundary does **not** guarantee: that external side effects
    performed before it are reversible or exactly-once. J.2 makes no
    exactly-once claim; idempotent replay is 18-J.4 work.

    Boundaries live in the same runtime persistence foundation as every other
    runtime entity (``EntityType.EXECUTION_CHECKPOINT``). They are *not* the
    project-level :class:`CheckpointState` snapshots: a recovery boundary is
    linked to an execution/attempt/work unit, whereas a project checkpoint
    captures a whole project state snapshot.
    """

    checkpoint_id: uuid.UUID = Field(default_factory=_new_uuid)
    execution_id: uuid.UUID = Field(...)
    attempt_id: uuid.UUID = Field(...)
    attempt_number: int = Field(..., ge=1)
    workflow_id: uuid.UUID | None = Field(default=None)
    task_id: str | None = Field(default=None, max_length=256)

    sequence: int = Field(..., ge=1)
    """Monotonic per execution, starting at 1."""

    label: str = Field(default="", max_length=256)
    status: ExecutionStatus = Field(default=ExecutionStatus.RUNNING)
    """Execution status committed at the boundary."""

    boundary_state: dict[str, Any] = Field(default_factory=dict)
    """Structured, inspectable facts reached at the boundary."""

    previous_checkpoint_id: uuid.UUID | None = Field(default=None)
    created_by: str = Field(default="system", max_length=128)
    schema_version: int = Field(default=EXECUTION_RECORD_VERSION, ge=1)
    metadata: dict[str, Any] = Field(default_factory=dict)


# ── Durable Execution State (Phase 18-J.2) ───────────────────────────────


class ExecutionState(StateModel):
    """Durable record of one logical execution.

    Phase 18-J.2 — canonical execution identity
    -------------------------------------------
    ``execution_id`` is the canonical, durable identity of *one logical
    execution* (e.g. one task of one workflow instance). It stays stable
    across retries and across process restarts; a retry adds an
    :class:`ExecutionAttemptState`, it never mints a new ``execution_id``.

    ``execution_key`` is the work-unit key the identity was derived from
    (see :func:`~autoforge_runtime.execution_store.execution_key_for_task`).
    It makes the canonical identity reproducible after a restart, so a new
    process can find the execution it must resume instead of starting a
    duplicate one.

    ``owner_id`` records *which process last owned* the execution. It is the
    durable evidence used to tell "running because I am running it" from
    "running because the process that ran it disappeared".

    The record is authoritative: it is written before work starts and after
    work commits, so a crash can never make in-flight work look committed.
    """

    execution_id: uuid.UUID = Field(default_factory=_new_uuid)
    execution_key: str | None = Field(default=None, max_length=512)
    workflow_id: uuid.UUID | None = Field(default=None)
    task_id: str | None = Field(default=None, max_length=256)
    correlation_id: uuid.UUID | None = Field(default=None)
    status: ExecutionStatus = Field(default=ExecutionStatus.CREATED)

    attempt_count: int = Field(default=0, ge=0)
    """Number of attempts durably recorded for this execution."""

    current_attempt_id: uuid.UUID | None = Field(default=None)
    """Most recently started attempt (in flight when that attempt is STARTED)."""

    current_attempt_number: int | None = Field(default=None, ge=1)

    last_checkpoint_id: uuid.UUID | None = Field(default=None)
    """Last durable boundary committed for this execution."""

    last_checkpoint_sequence: int | None = Field(default=None, ge=1)

    owner_id: str | None = Field(default=None, max_length=256)
    """Identity of the process that owns (or last owned) the execution."""

    started_at: datetime | None = Field(default=None)
    completed_at: datetime | None = Field(default=None)
    interrupted_at: datetime | None = Field(default=None)

    failure: FailureRecord | None = Field(default=None)
    """Most recent committed failure; attempt-level failures are also recorded
    on the attempt record itself."""

    recoverable: bool = Field(default=False)
    """Whether a later phase may resume this execution instead of re-running it."""

    schema_version: int = Field(default=EXECUTION_RECORD_VERSION, ge=1)
    metadata: dict[str, Any] = Field(default_factory=dict)


# ── Runtime Metadata ─────────────────────────────────────────────────────


class RuntimeMetadata(StateModel):
    """Runtime metadata — platform-wide runtime metadata."""

    runtime_id: uuid.UUID = Field(default_factory=_new_uuid)
    status: RuntimeStatus = Field(default=RuntimeStatus.CREATED)
    version: str = Field(default="1.0.0", max_length=32)
    started_at: datetime | None = Field(default=None)
    uptime: timedelta | None = Field(default=None)
    configuration: dict[str, Any] = Field(default_factory=dict)
    metrics: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


# ── State Transition Record ──────────────────────────────────────────────


class StateTransition(BaseModel):
    """A record of a state transition for history/audit."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    transition_id: uuid.UUID = Field(default_factory=_new_uuid)
    entity_type: EntityType = Field(...)
    entity_id: uuid.UUID = Field(...)
    from_state: str = Field(...)
    to_state: str = Field(...)
    actor: str = Field(default="system", max_length=128)
    timestamp: datetime = Field(default_factory=_utc_now)
    metadata: dict[str, Any] = Field(default_factory=dict)


# ── Progress Metrics ─────────────────────────────────────────────────────


class ProgressMetrics(BaseModel):
    """Execution progress metrics."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    project_id: uuid.UUID = Field(...)
    total_tasks: int = Field(default=0, ge=0)
    completed_tasks: int = Field(default=0, ge=0)
    running_tasks: int = Field(default=0, ge=0)
    failed_tasks: int = Field(default=0, ge=0)
    blocked_tasks: int = Field(default=0, ge=0)
    pending_tasks: int = Field(default=0, ge=0)
    progress_percentage: float = Field(default=0.0, ge=0.0, le=100.0)
    estimated_cost: float = Field(default=0.0, ge=0.0)
    actual_cost: float = Field(default=0.0, ge=0.0)
    estimated_duration: timedelta | None = Field(default=None)
    actual_duration: timedelta | None = Field(default=None)


# ── Time Range ───────────────────────────────────────────────────────────


class TimeRange(BaseModel):
    """Time range filter for queries."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    start: datetime | None = Field(default=None)
    end: datetime | None = Field(default=None)


# ── Transition Result ────────────────────────────────────────────────────


class TransitionResult(BaseModel):
    """Result of a state transition operation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    success: bool = Field(...)
    entity_type: EntityType = Field(...)
    entity_id: uuid.UUID = Field(...)
    from_state: str = Field(...)
    to_state: str = Field(...)
    version: int = Field(...)
    error_code: str | None = Field(default=None)
    error_message: str | None = Field(default=None)
    metadata: dict[str, Any] = Field(default_factory=dict)