"""
Workflow Platform domain models — Phase 9.

Defines all immutable value objects used to describe a workflow before and
during execution.  These models are **definition-time** objects (what a
workflow is) rather than **execution-time** objects (what state a workflow
is in).  Runtime state lives in autoforge_runtime.WorkflowState /
WorkflowTaskState (local to this module).

Design principles
-----------------
- All definition models are frozen Pydantic BaseModel instances so that
  accidental mutation during execution is impossible.
- Execution-time task state is a mutable dataclass to allow in-process
  state transitions without re-creating large objects.
- This module has NO imports from autoforge_runtime to keep the dependency
  direction clean (workflow_engine → runtime, not the other way).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _new_uuid() -> uuid.UUID:
    return uuid.uuid4()


# ── Enumerations ──────────────────────────────────────────────────────────


class WorkflowTaskStatus(str, Enum):
    """
    Lifecycle status for a task within the Workflow Platform.

    This is distinct from the Runtime TaskStatus so that the Workflow
    Engine can own its own state machine without coupling to Runtime's
    internal representation.  The Workflow Engine projects its state into
    Runtime via the composition boundary.

    Allowed transitions (deterministic):
        PENDING  → READY | CANCELLED
        READY    → RUNNING | BLOCKED | CANCELLED
        RUNNING  → SUCCEEDED | FAILED | WAITING_APPROVAL | CANCELLED
        BLOCKED  → READY | CANCELLED
        WAITING_APPROVAL → RUNNING | CANCELLED
        RETRYING → RUNNING | FAILED
        FAILED   → RETRYING | CANCELLED   (if retry policy allows)
        SUCCEEDED  (terminal)
        CANCELLED  (terminal — irrecoverable)
    """

    PENDING = "pending"
    """Task created; dependencies not yet evaluated."""

    READY = "ready"
    """All dependencies satisfied; eligible for scheduling."""

    RUNNING = "running"
    """Task has been dispatched to an executor."""

    SUCCEEDED = "succeeded"
    """Task completed successfully (terminal)."""

    FAILED = "failed"
    """Task failed; may transition to RETRYING if policy allows."""

    RETRYING = "retrying"
    """Task is waiting for the retry backoff delay before RUNNING again."""

    BLOCKED = "blocked"
    """A dependency task has failed and the failure policy blocks this task."""

    WAITING_APPROVAL = "waiting_approval"
    """Task is paused at an HITL approval gate."""

    WAITING_FOR_HUMAN = "waiting_approval"
    """Alias for WAITING_APPROVAL adhering to Phase 18-J.5 specification."""

    CANCELLED = "cancelled"
    """Task was cancelled (terminal)."""


class DependencyPolicy(str, Enum):
    """
    Policy that governs how a task responds when one of its dependencies fails.
    """

    REQUIRE_ALL_SUCCESS = "require_all_success"
    """Task only becomes READY when ALL dependencies SUCCEEDED."""

    REQUIRE_ANY_SUCCESS = "require_any_success"
    """Task becomes READY when AT LEAST ONE dependency SUCCEEDED."""

    CONTINUE_ON_FAILURE = "continue_on_failure"
    """Task becomes READY even if some dependencies FAILED."""


class FailureAction(str, Enum):
    """What the workflow does when a task reaches terminal FAILED state."""

    FAIL_WORKFLOW = "fail_workflow"
    """Immediately fail the entire workflow."""

    CONTINUE = "continue"
    """Mark the task failed and continue with remaining tasks."""

    CANCEL_DEPENDENTS = "cancel_dependents"
    """Cancel all downstream tasks that depend on this task."""


class BackoffStrategy(str, Enum):
    """Backoff algorithm for retry delays."""

    FIXED = "fixed"
    """Constant delay between retries."""

    LINEAR = "linear"
    """Delay increases linearly: base * attempt_number."""

    EXPONENTIAL = "exponential"
    """Delay doubles each retry: base * 2^(attempt-1)."""


# ── Retry Policy ─────────────────────────────────────────────────────────


class RetryPolicy(BaseModel):
    """
    Deterministic retry policy for a task.

    All retry decisions are made by deterministic logic — not model judgment.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    max_attempts: int = Field(
        default=3,
        ge=1,
        le=20,
        description="Maximum total execution attempts (including the first).",
    )
    backoff_strategy: BackoffStrategy = Field(
        default=BackoffStrategy.EXPONENTIAL,
        description="Backoff algorithm for retry delays.",
    )
    base_delay_seconds: float = Field(
        default=1.0,
        ge=0.0,
        le=3600.0,
        description="Base delay in seconds before the first retry.",
    )
    max_delay_seconds: float = Field(
        default=300.0,
        ge=0.0,
        description="Maximum delay cap in seconds regardless of backoff.",
    )
    retryable_error_codes: frozenset[str] = Field(
        default_factory=frozenset,
        description="Explicit set of error codes that are retryable. "
        "Empty set means ALL errors are considered retryable.",
    )
    non_retryable_error_codes: frozenset[str] = Field(
        default_factory=frozenset,
        description="Error codes that are never retried regardless of other policy.",
    )
    timeout_seconds: float | None = Field(
        default=None,
        ge=1.0,
        description="Per-attempt timeout. None means no timeout.",
    )

    @classmethod
    def no_retry(cls) -> RetryPolicy:
        """Factory: a policy that never retries (max_attempts=1)."""
        return cls(max_attempts=1)

    @classmethod
    def default(cls) -> RetryPolicy:
        """Factory: sensible defaults for most tasks."""
        return cls()


# ── Recovery Policy ───────────────────────────────────────────────────────


class RecoveryPolicy(BaseModel):
    """
    Policy that controls how a workflow recovers after interruption.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    resume_from_checkpoint: bool = Field(
        default=True,
        description="Whether to resume from the last checkpoint on recovery.",
    )
    preserve_completed_tasks: bool = Field(
        default=True,
        description="Whether completed tasks are skipped on resume.",
    )
    max_recovery_attempts: int = Field(
        default=3,
        ge=1,
        description="Maximum recovery attempts before marking workflow as unrecoverable.",
    )


# ── Execution Policy ──────────────────────────────────────────────────────


class ExecutionPolicy(BaseModel):
    """
    Controls how a workflow is executed at the scheduler level.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    max_concurrent_tasks: int = Field(
        default=4,
        ge=1,
        le=64,
        description="Maximum number of tasks that may run concurrently.",
    )
    dependency_policy: DependencyPolicy = Field(
        default=DependencyPolicy.REQUIRE_ALL_SUCCESS,
        description="Default dependency satisfaction policy for all tasks.",
    )
    failure_action: FailureAction = Field(
        default=FailureAction.FAIL_WORKFLOW,
        description="Default action taken when any task terminally fails.",
    )
    timeout_seconds: float | None = Field(
        default=None,
        ge=1.0,
        description="Total workflow wall-clock budget. None means no timeout.",
    )


# ── Approval Gate Policy ──────────────────────────────────────────────────


class ApprovalGatePolicy(BaseModel):
    """
    Policy controlling an HITL approval gate attached to a task.

    A task with an ApprovalGatePolicy transitions to WAITING_APPROVAL when
    it finishes its execution phase.  The workflow is PAUSED until an
    explicit decision is submitted via the ApprovalGate API.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    gate_id: str = Field(
        ...,
        min_length=1,
        max_length=128,
        description="Stable identifier for this gate (used in approval requests).",
    )
    description: str = Field(
        default="",
        max_length=2048,
        description="Human-readable description of what requires approval.",
    )
    timeout_seconds: float | None = Field(
        default=None,
        ge=1.0,
        description="How long to wait for approval before timing out. "
        "None means wait indefinitely.",
    )
    required_approvers: int = Field(
        default=1,
        ge=1,
        description="Minimum number of approvals required to proceed.",
    )


# ── Dependency Edge ───────────────────────────────────────────────────────


class DependencyEdge(BaseModel):
    """
    A directed dependency edge between two tasks: ``upstream → downstream``.

    The downstream task cannot enter READY until the upstream task satisfies
    the dependency policy.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    upstream_task_id: str = Field(
        ...,
        min_length=1,
        max_length=256,
        description="Task ID that must complete before the downstream task.",
    )
    downstream_task_id: str = Field(
        ...,
        min_length=1,
        max_length=256,
        description="Task ID that depends on the upstream task.",
    )
    policy: DependencyPolicy = Field(
        default=DependencyPolicy.REQUIRE_ALL_SUCCESS,
        description="Satisfaction policy for this specific edge.",
    )


# ── Task Definition ───────────────────────────────────────────────────────


class TaskDefinition(BaseModel):
    """
    Immutable description of a task within a workflow.

    Task definitions are the inputs to the DAG engine and scheduler.
    They carry no mutable execution state — that lives in WorkflowTaskState.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    task_id: str = Field(
        ...,
        min_length=1,
        max_length=256,
        description="Stable, unique identifier for this task within the workflow.",
    )
    name: str = Field(
        ...,
        min_length=1,
        max_length=256,
        description="Human-readable task name.",
    )
    description: str = Field(
        default="",
        max_length=4096,
        description="Optional detailed description.",
    )
    task_type: str = Field(
        default="general",
        min_length=1,
        max_length=128,
        description="Opaque task type string (e.g. 'coding', 'review', 'deploy').",
    )
    priority: str = Field(
        default="medium",
        pattern=r"^(low|medium|high|critical)$",
        description="Scheduling priority.",
    )
    retry_policy: RetryPolicy = Field(
        default_factory=RetryPolicy.default,
        description="Retry policy for this task.",
    )
    approval_gate: ApprovalGatePolicy | None = Field(
        default=None,
        description="If set, the task requires HITL approval after execution.",
    )
    input_data: dict[str, Any] = Field(
        default_factory=dict,
        description="Input data provided to the task executor.",
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Extensible metadata.",
    )
    estimated_duration: timedelta | None = Field(
        default=None,
        description="Optional estimated execution duration.",
    )


# ── Workflow Definition ───────────────────────────────────────────────────


class WorkflowDefinition(BaseModel):
    """
    Immutable definition of a workflow.

    A WorkflowDefinition is the complete, validated specification of a
    workflow: its tasks, dependency edges, execution policy, retry policy,
    and recovery policy.  It is submitted to the WorkflowEngine which
    produces a live WorkflowHandle.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    workflow_id: uuid.UUID = Field(
        default_factory=_new_uuid,
        description="Globally unique workflow instance ID.",
    )
    name: str = Field(
        ...,
        min_length=1,
        max_length=256,
        description="Human-readable workflow name.",
    )
    version: str = Field(
        default="1.0.0",
        max_length=32,
        description="Semantic version of this workflow definition.",
    )
    description: str = Field(
        default="",
        max_length=4096,
        description="Optional description.",
    )
    tasks: list[TaskDefinition] = Field(
        ...,
        min_length=1,
        description="Ordered list of task definitions (ordering is informational only).",
    )
    dependencies: list[DependencyEdge] = Field(
        default_factory=list,
        description="Explicit dependency edges between tasks.",
    )
    execution_policy: ExecutionPolicy = Field(
        default_factory=ExecutionPolicy,
        description="Execution policy for the workflow.",
    )
    retry_policy: RetryPolicy = Field(
        default_factory=RetryPolicy.default,
        description="Default retry policy applied to tasks that do not define their own.",
    )
    recovery_policy: RecoveryPolicy = Field(
        default_factory=RecoveryPolicy,
        description="Recovery policy applied on workflow interruption.",
    )
    correlation_id: uuid.UUID | None = Field(
        default=None,
        description="Correlation ID for tracing across subsystems.",
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Extensible metadata.",
    )
    created_at: datetime = Field(
        default_factory=_utc_now,
        description="When this definition was created.",
    )


# ── Workflow Task State (mutable, execution-time) ─────────────────────────


@dataclass
class WorkflowTaskState:
    """
    Mutable execution-time state for a single task within a workflow.

    This is NOT a Pydantic model because it is updated frequently during
    execution.  It is owned exclusively by the WorkflowEngine and is never
    directly shared with external callers without copying.
    """

    task_id: str
    workflow_id: uuid.UUID
    definition: TaskDefinition

    status: WorkflowTaskStatus = WorkflowTaskStatus.PENDING
    attempt_number: int = 0
    """Current attempt count (0 = not yet started)."""

    started_at: datetime | None = None
    finished_at: datetime | None = None
    last_error_code: str | None = None
    last_error_message: str | None = None
    result: dict[str, Any] = field(default_factory=dict)
    approval_gate_id: str | None = None
    """Set when the task enters WAITING_APPROVAL."""

    retry_scheduled_at: datetime | None = None
    """When the task is scheduled to retry (for backoff tracking)."""

    correlation_id: uuid.UUID | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def is_terminal(self) -> bool:
        """Return True if this task is in a terminal state."""
        return self.status in {
            WorkflowTaskStatus.SUCCEEDED,
            WorkflowTaskStatus.CANCELLED,
        }

    @property
    def is_failed_terminal(self) -> bool:
        """Return True if this task has failed and exhausted all retries."""
        return (
            self.status == WorkflowTaskStatus.FAILED
            and self.attempt_number >= self.definition.retry_policy.max_attempts
        )

    def to_snapshot(self) -> dict[str, Any]:
        """Serialize to a plain dictionary for checkpointing."""
        return {
            "task_id": self.task_id,
            "workflow_id": str(self.workflow_id),
            "status": self.status.value,
            "attempt_number": self.attempt_number,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
            "last_error_code": self.last_error_code,
            "last_error_message": self.last_error_message,
            "result": self.result,
            "approval_gate_id": self.approval_gate_id,
            "retry_scheduled_at": (
                self.retry_scheduled_at.isoformat() if self.retry_scheduled_at else None
            ),
            "correlation_id": str(self.correlation_id) if self.correlation_id else None,
            "metadata": self.metadata,
        }

    @classmethod
    def from_snapshot(
        cls,
        snapshot: dict[str, Any],
        definition: TaskDefinition,
    ) -> WorkflowTaskState:
        """Restore from a checkpoint snapshot."""
        state = cls(
            task_id=snapshot["task_id"],
            workflow_id=uuid.UUID(snapshot["workflow_id"]),
            definition=definition,
            status=WorkflowTaskStatus(snapshot["status"]),
            attempt_number=snapshot.get("attempt_number", 0),
            last_error_code=snapshot.get("last_error_code"),
            last_error_message=snapshot.get("last_error_message"),
            result=snapshot.get("result", {}),
            approval_gate_id=snapshot.get("approval_gate_id"),
            metadata=snapshot.get("metadata", {}),
        )
        if snapshot.get("started_at"):
            state.started_at = datetime.fromisoformat(snapshot["started_at"])
        if snapshot.get("finished_at"):
            state.finished_at = datetime.fromisoformat(snapshot["finished_at"])
        if snapshot.get("retry_scheduled_at"):
            state.retry_scheduled_at = datetime.fromisoformat(
                snapshot["retry_scheduled_at"]
            )
        if snapshot.get("correlation_id"):
            state.correlation_id = uuid.UUID(snapshot["correlation_id"])
        return state
