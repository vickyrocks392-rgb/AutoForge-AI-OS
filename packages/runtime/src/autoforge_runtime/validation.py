"""Validation Engine — validates state transition requests against defined rules.

Implements transition validation rules from Runtime State Manager Specification v1.0, Section 18.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from autoforge_runtime.models import (
    AttemptStatus,
    CheckpointStatus,
    DurableApprovalStatus,
    ExecutionStatus,
    LoopStatus,
    OperationStatus,
    ProjectStatus,
    WorkerStatus,
    WorkflowStatus,
)


@dataclass(frozen=True)
class ValidationResult:
    """Result of a transition validation."""

    valid: bool
    error_code: str | None = None
    error_message: str | None = None
    details: dict[str, Any] = field(default_factory=dict)


class ValidationErrorCode:
    """Validation error codes from Specification Section 18.7."""

    INVALID_TRANSITION = "INVALID_TRANSITION"
    TERMINAL_STATE = "TERMINAL_STATE"
    PRECONDITION_FAILED = "PRECONDITION_FAILED"
    POSTCONDITION_FAILED = "POSTCONDITION_FAILED"
    VERSION_CONFLICT = "VERSION_CONFLICT"
    ENTITY_NOT_FOUND = "ENTITY_NOT_FOUND"
    INVALID_STATE = "INVALID_STATE"
    MISSING_METADATA = "MISSING_METADATA"


# ── Project State Transition Rules (Section 18.1) ────────────────────────

_PROJECT_TRANSITIONS: dict[ProjectStatus, set[ProjectStatus]] = {
    ProjectStatus.CREATED: {ProjectStatus.PLANNING, ProjectStatus.CANCELLED},
    ProjectStatus.PLANNING: {ProjectStatus.RUNNING, ProjectStatus.FAILED, ProjectStatus.CANCELLED},
    ProjectStatus.RUNNING: {ProjectStatus.REVIEWING, ProjectStatus.PAUSED, ProjectStatus.COMPLETING, ProjectStatus.FAILED, ProjectStatus.CANCELLED},
    ProjectStatus.REVIEWING: {ProjectStatus.RUNNING, ProjectStatus.PAUSED, ProjectStatus.FAILED, ProjectStatus.CANCELLED},
    ProjectStatus.PAUSED: {ProjectStatus.RUNNING, ProjectStatus.CANCELLED},
    ProjectStatus.COMPLETING: {ProjectStatus.FINISHED, ProjectStatus.FAILED},
    ProjectStatus.FINISHED: set(),
    ProjectStatus.FAILED: set(),
    ProjectStatus.CANCELLED: set(),
}

_PROJECT_TERMINAL: set[ProjectStatus] = {ProjectStatus.FINISHED, ProjectStatus.FAILED, ProjectStatus.CANCELLED}


# ── Workflow State Transition Rules (Section 18.2) ───────────────────────

_WORKFLOW_TRANSITIONS: dict[WorkflowStatus, set[WorkflowStatus]] = {
    WorkflowStatus.CREATED: {WorkflowStatus.RUNNING, WorkflowStatus.CANCELLED},
    WorkflowStatus.RUNNING: {
        WorkflowStatus.PAUSED,
        WorkflowStatus.COMPLETING,
        WorkflowStatus.FINISHED,
        WorkflowStatus.FAILED,
        WorkflowStatus.CANCELLED,
        WorkflowStatus.INTERRUPTED,
    },
    WorkflowStatus.PAUSED: {WorkflowStatus.RUNNING, WorkflowStatus.CANCELLED},
    WorkflowStatus.COMPLETING: {WorkflowStatus.FINISHED, WorkflowStatus.FAILED},
    WorkflowStatus.INTERRUPTED: {
        WorkflowStatus.RUNNING,
        WorkflowStatus.FAILED,
        WorkflowStatus.CANCELLED,
    },
    WorkflowStatus.FINISHED: set(),
    WorkflowStatus.FAILED: set(),
    WorkflowStatus.CANCELLED: set(),
}

_WORKFLOW_TERMINAL: set[WorkflowStatus] = {WorkflowStatus.FINISHED, WorkflowStatus.FAILED, WorkflowStatus.CANCELLED}
_WORKFLOW_RECOVERABLE: set[WorkflowStatus] = {
    WorkflowStatus.CREATED,
    WorkflowStatus.RUNNING,
    WorkflowStatus.PAUSED,
    WorkflowStatus.INTERRUPTED,
}


# ── Engineering Loop State Transition Rules (Section 18.3) ───────────────

_LOOP_TRANSITIONS: dict[LoopStatus, set[LoopStatus]] = {
    LoopStatus.IDLE: {LoopStatus.PLAN},
    LoopStatus.PLAN: {LoopStatus.EXECUTE},
    LoopStatus.EXECUTE: {LoopStatus.REVIEW},
    LoopStatus.REVIEW: {LoopStatus.COMPLETE, LoopStatus.REMEDIATE, LoopStatus.ESCALATE, LoopStatus.FAILED},
    LoopStatus.COMPLETE: set(),
    LoopStatus.REMEDIATE: {LoopStatus.EXECUTE},
    LoopStatus.ESCALATE: {LoopStatus.RESUME},
    LoopStatus.RESUME: {LoopStatus.EXECUTE},
    LoopStatus.FAILED: set(),
}

_LOOP_TERMINAL: set[LoopStatus] = {LoopStatus.COMPLETE, LoopStatus.FAILED}


# ── Task State Transition Rules (Section 18.4) ───────────────────────────

_TASK_TRANSITIONS: dict[str, set[str]] = {
    "pending": {"ready", "cancelled"},
    "ready": {"running", "blocked", "cancelled"},
    "running": {"completed", "failed", "waiting", "retrying"},
    "completed": set(),
    "failed": {"retrying", "cancelled"},
    "waiting": {"running", "cancelled"},
    "blocked": {"ready", "cancelled"},
    "retrying": {"running", "failed"},
}

_TASK_TERMINAL: set[str] = {"completed"}


# ── Worker State Transition Rules (Section 18.5) ─────────────────────────

_WORKER_TRANSITIONS: dict[WorkerStatus, set[WorkerStatus]] = {
    WorkerStatus.IDLE: {WorkerStatus.BUSY, WorkerStatus.OFFLINE},
    WorkerStatus.BUSY: {WorkerStatus.IDLE, WorkerStatus.DRAINING, WorkerStatus.OFFLINE},
    WorkerStatus.DRAINING: {WorkerStatus.IDLE, WorkerStatus.OFFLINE},
    WorkerStatus.OFFLINE: {WorkerStatus.IDLE},
}


# ── Checkpoint State Transition Rules (Section 18.6) ─────────────────────

_CHECKPOINT_TRANSITIONS: dict[CheckpointStatus, set[CheckpointStatus]] = {
    CheckpointStatus.ACTIVE: {CheckpointStatus.RESTORED, CheckpointStatus.OBSOLETE},
    CheckpointStatus.RESTORED: {CheckpointStatus.OBSOLETE},
    CheckpointStatus.OBSOLETE: set(),
}

_CHECKPOINT_TERMINAL: set[CheckpointStatus] = {CheckpointStatus.OBSOLETE}


def _check_base(current: Any, transitions: dict, terminal: set, entity: str) -> ValidationResult | None:
    """Check base validation conditions. Returns error result or None if valid."""
    if current not in transitions:
        return ValidationResult(False, ValidationErrorCode.INVALID_STATE, f"Invalid {entity} state: {current!r}", {"current": str(current)})
    if current in terminal:
        return ValidationResult(False, ValidationErrorCode.TERMINAL_STATE, f"{entity.capitalize()} is in terminal state {current!r}", {"current": str(current)})
    return None


def _check_allowed(current: Any, target: Any, transitions: dict, entity: str) -> ValidationResult | None:
    """Check if target is in allowed transitions. Returns error result or None if valid."""
    allowed = transitions[current]
    if target not in allowed:
        return ValidationResult(
            False,
            ValidationErrorCode.INVALID_TRANSITION,
            f"Invalid {entity} transition: {current!r} -> {target!r}",
            {"current": str(current), "target": str(target), "allowed": sorted(str(s) for s in allowed)},
        )
    return None


def validate_project_transition(current: ProjectStatus, target: ProjectStatus, *, metadata: dict[str, Any] | None = None) -> ValidationResult:
    """Validate a project state transition (Section 18.1)."""
    err = _check_base(current, _PROJECT_TRANSITIONS, _PROJECT_TERMINAL, "project")
    if err:
        return err
    err = _check_allowed(current, target, _PROJECT_TRANSITIONS, "project")
    if err:
        return err

    # Pre-condition checks
    if target == ProjectStatus.RUNNING and current == ProjectStatus.PLANNING:
        if not metadata or not metadata.get("strategic_plan") or not metadata.get("executable_workflow"):
            return ValidationResult(False, ValidationErrorCode.PRECONDITION_FAILED,
                "Strategic plan and executable workflow must be complete for transition to Running",
                {"current": current.value, "target": target.value})
    if target == ProjectStatus.RUNNING and current == ProjectStatus.REVIEWING:
        if not metadata or not metadata.get("approval"):
            return ValidationResult(False, ValidationErrorCode.PRECONDITION_FAILED,
                "Human approval required for transition from Reviewing to Running",
                {"current": current.value, "target": target.value})
    if target == ProjectStatus.FINISHED:
        if not metadata or not metadata.get("acceptance_criteria_met"):
            return ValidationResult(False, ValidationErrorCode.PRECONDITION_FAILED,
                "All acceptance criteria must be met for transition to Finished",
                {"current": current.value, "target": target.value})
    return ValidationResult(True)


def validate_workflow_transition(current: WorkflowStatus, target: WorkflowStatus, *, metadata: dict[str, Any] | None = None) -> ValidationResult:
    """Validate a workflow state transition (Section 18.2)."""
    err = _check_base(current, _WORKFLOW_TRANSITIONS, _WORKFLOW_TERMINAL, "workflow")
    if err:
        return err
    err = _check_allowed(current, target, _WORKFLOW_TRANSITIONS, "workflow")
    if err:
        return err
    if target == WorkflowStatus.FINISHED:
        if not metadata or not metadata.get("all_tasks_completed"):
            return ValidationResult(False, ValidationErrorCode.PRECONDITION_FAILED,
                "All tasks must be completed for transition to Finished",
                {"current": current.value, "target": target.value})
    if current == WorkflowStatus.INTERRUPTED and target == WorkflowStatus.RUNNING:
        if not metadata or not metadata.get("resume"):
            return ValidationResult(
                False,
                ValidationErrorCode.PRECONDITION_FAILED,
                "An interrupted workflow may only return to Running through an explicit controlled resume",
                {"current": current.value, "target": target.value},
            )
    return ValidationResult(True)


def validate_loop_transition(current: LoopStatus, target: LoopStatus, *, metadata: dict[str, Any] | None = None) -> ValidationResult:
    """Validate an engineering loop state transition (Section 18.3)."""
    err = _check_base(current, _LOOP_TRANSITIONS, _LOOP_TERMINAL, "loop")
    if err:
        return err
    err = _check_allowed(current, target, _LOOP_TRANSITIONS, "loop")
    if err:
        return err

    if target == LoopStatus.EXECUTE and current == LoopStatus.PLAN:
        if not metadata or not metadata.get("plan_complete"):
            return ValidationResult(False, ValidationErrorCode.PRECONDITION_FAILED,
                "Plan must be complete for transition to EXECUTE", {"current": current.value, "target": target.value})
    if target == LoopStatus.REVIEW and current == LoopStatus.EXECUTE:
        if not metadata or not metadata.get("execution_complete"):
            return ValidationResult(False, ValidationErrorCode.PRECONDITION_FAILED,
                "Execution must be complete for transition to REVIEW", {"current": current.value, "target": target.value})
    if target == LoopStatus.EXECUTE and current == LoopStatus.REMEDIATE:
        if not metadata or not metadata.get("remediation_plan"):
            return ValidationResult(False, ValidationErrorCode.PRECONDITION_FAILED,
                "Remediation plan must be defined for transition to EXECUTE", {"current": current.value, "target": target.value})
    if target == LoopStatus.RESUME and current == LoopStatus.ESCALATE:
        if not metadata or not metadata.get("human_decision"):
            return ValidationResult(False, ValidationErrorCode.PRECONDITION_FAILED,
                "Human decision required for transition from ESCALATE to RESUME", {"current": current.value, "target": target.value})
    return ValidationResult(True)


def validate_task_transition(current: str, target: str, *, metadata: dict[str, Any] | None = None) -> ValidationResult:
    """Validate a task state transition (Section 18.4)."""
    err = _check_base(current, _TASK_TRANSITIONS, _TASK_TERMINAL, "task")
    if err:
        return err
    err = _check_allowed(current, target, _TASK_TRANSITIONS, "task")
    if err:
        return err

    if target == "ready" and current == "pending":
        if not metadata or not metadata.get("dependencies_satisfied"):
            return ValidationResult(False, ValidationErrorCode.PRECONDITION_FAILED,
                "Dependencies must be satisfied for transition to Ready", {"current": current, "target": target})
    if target == "running" and current == "waiting":
        if not metadata or not metadata.get("approval_decision"):
            return ValidationResult(False, ValidationErrorCode.PRECONDITION_FAILED,
                "Approval decision required for transition from Waiting to Running", {"current": current, "target": target})
    if target == "ready" and current == "blocked":
        if not metadata or not metadata.get("dependencies_resolved"):
            return ValidationResult(False, ValidationErrorCode.PRECONDITION_FAILED,
                "Dependencies must be resolved for transition from Blocked to Ready", {"current": current, "target": target})
    if target in ("retrying", "running") and current in ("failed", "retrying"):
        retry_count = (metadata or {}).get("retry_count", 0)
        max_retries = (metadata or {}).get("max_retries", 3)
        if retry_count >= max_retries:
            return ValidationResult(False, ValidationErrorCode.PRECONDITION_FAILED,
                "Retry count exceeds max retries", {"current": current, "target": target, "retry_count": retry_count, "max_retries": max_retries})
    return ValidationResult(True)


def validate_worker_transition(current: WorkerStatus, target: WorkerStatus, *, metadata: dict[str, Any] | None = None) -> ValidationResult:
    """Validate a worker state transition (Section 18.5)."""
    err = _check_base(current, _WORKER_TRANSITIONS, set(), "worker")
    if err:
        return err
    err = _check_allowed(current, target, _WORKER_TRANSITIONS, "worker")
    if err:
        return err

    if target == WorkerStatus.BUSY and current == WorkerStatus.IDLE:
        if not metadata or not metadata.get("available"):
            return ValidationResult(False, ValidationErrorCode.PRECONDITION_FAILED,
                "Worker must be available for transition to Busy", {"current": current.value, "target": target.value})
    if target == WorkerStatus.IDLE and current == WorkerStatus.DRAINING:
        if not metadata or not metadata.get("current_task_completed"):
            return ValidationResult(False, ValidationErrorCode.PRECONDITION_FAILED,
                "Current task must be completed for transition from Draining to Idle", {"current": current.value, "target": target.value})
    if target == WorkerStatus.IDLE and current == WorkerStatus.OFFLINE:
        if not metadata or not metadata.get("online"):
            return ValidationResult(False, ValidationErrorCode.PRECONDITION_FAILED,
                "Worker must be online for transition from Offline to Idle", {"current": current.value, "target": target.value})
    return ValidationResult(True)


def validate_checkpoint_transition(current: CheckpointStatus, target: CheckpointStatus, *, metadata: dict[str, Any] | None = None) -> ValidationResult:
    """Validate a checkpoint state transition (Section 18.6)."""
    err = _check_base(current, _CHECKPOINT_TRANSITIONS, _CHECKPOINT_TERMINAL, "checkpoint")
    if err:
        return err
    err = _check_allowed(current, target, _CHECKPOINT_TRANSITIONS, "checkpoint")
    if err:
        return err
    return ValidationResult(True)


def get_allowed_project_transitions(status: ProjectStatus) -> frozenset[ProjectStatus]:
    """Return allowed target statuses from a given ProjectStatus."""
    return frozenset(_PROJECT_TRANSITIONS.get(status, set()))


def get_allowed_workflow_transitions(status: WorkflowStatus) -> frozenset[WorkflowStatus]:
    """Return allowed target statuses from a given WorkflowStatus."""
    return frozenset(_WORKFLOW_TRANSITIONS.get(status, set()))


def get_allowed_loop_transitions(status: LoopStatus) -> frozenset[LoopStatus]:
    """Return allowed target statuses from a given LoopStatus."""
    return frozenset(_LOOP_TRANSITIONS.get(status, set()))


def get_allowed_task_transitions(status: str) -> frozenset[str]:
    """Return allowed target statuses from a given task status."""
    return frozenset(_TASK_TRANSITIONS.get(status, set()))


def get_allowed_worker_transitions(status: WorkerStatus) -> frozenset[WorkerStatus]:
    """Return allowed target statuses from a given WorkerStatus."""
    return frozenset(_WORKER_TRANSITIONS.get(status, set()))


def get_allowed_checkpoint_transitions(status: CheckpointStatus) -> frozenset[CheckpointStatus]:
    """Return allowed target statuses from a given CheckpointStatus."""
    return frozenset(_CHECKPOINT_TRANSITIONS.get(status, set()))


def is_project_terminal(status: ProjectStatus) -> bool:
    """Check whether a project status is terminal."""
    return status in _PROJECT_TERMINAL


def is_workflow_terminal(status: WorkflowStatus) -> bool:
    """Check whether a workflow status is terminal."""
    return status in _WORKFLOW_TERMINAL


def is_loop_terminal(status: LoopStatus) -> bool:
    """Check whether a loop status is terminal."""
    return status in _LOOP_TERMINAL


def is_task_terminal(status: str) -> bool:
    """Check whether a task status is terminal."""
    return status in _TASK_TERMINAL


def is_checkpoint_terminal(status: CheckpointStatus) -> bool:
    """Check whether a checkpoint status is terminal."""
    return status in _CHECKPOINT_TERMINAL


# ── Durable Execution Rules (Phase 18-J.2) ───────────────────────────────
#
# Section 18.7 extension: the durable execution lifecycle and the attempt
# lifecycle. Keeping these tables next to the other entity rules means the
# durable execution model is validated by the same deterministic validation
# engine as every other runtime entity — no competing state machine.

_EXECUTION_TRANSITIONS: dict[ExecutionStatus, set[ExecutionStatus]] = {
    ExecutionStatus.CREATED: {
        ExecutionStatus.RUNNING,
        ExecutionStatus.CANCELLED,
    },
    ExecutionStatus.RUNNING: {
        ExecutionStatus.COMPLETED,
        ExecutionStatus.FAILED,
        ExecutionStatus.CANCELLED,
        ExecutionStatus.INTERRUPTED,
    },
    # A controlled resume (18-J.3) may return an interrupted execution to
    # RUNNING; it must pass ``metadata={"resume": True}`` so that no code path
    # can accidentally "resume" an interrupted execution.
    ExecutionStatus.INTERRUPTED: {
        ExecutionStatus.RUNNING,
        ExecutionStatus.FAILED,
        ExecutionStatus.CANCELLED,
    },
    ExecutionStatus.COMPLETED: set(),
    ExecutionStatus.FAILED: set(),
    ExecutionStatus.CANCELLED: set(),
}

_EXECUTION_TERMINAL: set[ExecutionStatus] = {
    ExecutionStatus.COMPLETED,
    ExecutionStatus.FAILED,
    ExecutionStatus.CANCELLED,
}

#: Statuses that a later phase may resume (never terminal, never "done").
_EXECUTION_RECOVERABLE: set[ExecutionStatus] = {
    ExecutionStatus.CREATED,
    ExecutionStatus.RUNNING,
    ExecutionStatus.INTERRUPTED,
}

_ATTEMPT_TRANSITIONS: dict[AttemptStatus, set[AttemptStatus]] = {
    AttemptStatus.STARTED: {
        AttemptStatus.COMPLETED,
        AttemptStatus.FAILED,
        AttemptStatus.INTERRUPTED,
        AttemptStatus.CANCELLED,
    },
    AttemptStatus.COMPLETED: set(),
    AttemptStatus.FAILED: set(),
    AttemptStatus.INTERRUPTED: set(),
    AttemptStatus.CANCELLED: set(),
}

_ATTEMPT_TERMINAL: set[AttemptStatus] = {
    AttemptStatus.COMPLETED,
    AttemptStatus.FAILED,
    AttemptStatus.INTERRUPTED,
    AttemptStatus.CANCELLED,
}


def validate_execution_transition(
    current: ExecutionStatus,
    target: ExecutionStatus,
    *,
    metadata: dict[str, Any] | None = None,
) -> ValidationResult:
    """Validate a durable execution state transition."""
    err = _check_base(current, _EXECUTION_TRANSITIONS, _EXECUTION_TERMINAL, "execution")
    if err:
        return err
    err = _check_allowed(current, target, _EXECUTION_TRANSITIONS, "execution")
    if err:
        return err
    if current == ExecutionStatus.INTERRUPTED and target == ExecutionStatus.RUNNING:
        if not metadata or not metadata.get("resume"):
            return ValidationResult(
                False,
                ValidationErrorCode.PRECONDITION_FAILED,
                "An interrupted execution may only return to Running through an explicit controlled resume",
                {"current": current.value, "target": target.value},
            )
    return ValidationResult(True)


def validate_attempt_transition(
    current: AttemptStatus,
    target: AttemptStatus,
    *,
    metadata: dict[str, Any] | None = None,
) -> ValidationResult:
    """Validate an execution attempt state transition."""
    err = _check_base(current, _ATTEMPT_TRANSITIONS, _ATTEMPT_TERMINAL, "attempt")
    if err:
        return err
    err = _check_allowed(current, target, _ATTEMPT_TRANSITIONS, "attempt")
    if err:
        return err
    return ValidationResult(True)


def get_allowed_execution_transitions(status: ExecutionStatus) -> frozenset[ExecutionStatus]:
    """Return allowed target statuses from a given ExecutionStatus."""
    return frozenset(_EXECUTION_TRANSITIONS.get(status, set()))


def get_allowed_attempt_transitions(status: AttemptStatus) -> frozenset[AttemptStatus]:
    """Return allowed target statuses from a given AttemptStatus."""
    return frozenset(_ATTEMPT_TRANSITIONS.get(status, set()))


def is_execution_terminal(status: ExecutionStatus) -> bool:
    """Check whether an execution status is terminal (never resumable)."""
    return status in _EXECUTION_TERMINAL


def is_attempt_terminal(status: AttemptStatus) -> bool:
    """Check whether an attempt status is terminal for that attempt."""
    return status in _ATTEMPT_TERMINAL


def is_execution_recoverable(status: ExecutionStatus) -> bool:
    """Check whether a later phase may resume an execution in this status."""
    return status in _EXECUTION_RECOVERABLE


def is_workflow_terminal(status: WorkflowStatus) -> bool:
    """Check whether a workflow status is terminal (never resumable)."""
    return status in _WORKFLOW_TERMINAL


def is_workflow_recoverable(status: WorkflowStatus) -> bool:
    """Check whether a workflow in this status is recoverable / resumable."""
    return status in _WORKFLOW_RECOVERABLE


def get_allowed_workflow_transitions(status: WorkflowStatus) -> frozenset[WorkflowStatus]:
    """Return allowed target statuses from a given WorkflowStatus."""
    return frozenset(_WORKFLOW_TRANSITIONS.get(status, set()))


# ── Idempotent Operation State Transition Rules (Phase 18-J.4) ────────────

_OPERATION_TRANSITIONS: dict[OperationStatus, set[OperationStatus]] = {
    OperationStatus.PENDING: {
        OperationStatus.RUNNING,
        OperationStatus.CANCELLED,
    },
    OperationStatus.RUNNING: {
        OperationStatus.COMPLETED,
        OperationStatus.FAILED,
        OperationStatus.INTERRUPTED,
        OperationStatus.CANCELLED,
    },
    OperationStatus.INTERRUPTED: {
        OperationStatus.RUNNING,
        OperationStatus.FAILED,
        OperationStatus.CANCELLED,
    },
    OperationStatus.FAILED: {
        OperationStatus.RUNNING,
    },
    OperationStatus.COMPLETED: set(),
    OperationStatus.CANCELLED: set(),
}

_OPERATION_TERMINAL: set[OperationStatus] = {
    OperationStatus.COMPLETED,
    OperationStatus.CANCELLED,
}

_OPERATION_RECOVERABLE: set[OperationStatus] = {
    OperationStatus.PENDING,
    OperationStatus.RUNNING,
    OperationStatus.INTERRUPTED,
    OperationStatus.FAILED,
}


def validate_operation_transition(
    current: OperationStatus,
    target: OperationStatus,
    *,
    metadata: dict[str, Any] | None = None,
) -> ValidationResult:
    """Validate an idempotent operation state transition."""
    err = _check_base(current, _OPERATION_TRANSITIONS, _OPERATION_TERMINAL, "operation")
    if err:
        return err
    err = _check_allowed(current, target, _OPERATION_TRANSITIONS, "operation")
    if err:
        return err
    if current == OperationStatus.INTERRUPTED and target == OperationStatus.RUNNING:
        if not metadata or not (metadata.get("resume") or metadata.get("recover")):
            return ValidationResult(
                False,
                ValidationErrorCode.PRECONDITION_FAILED,
                "An interrupted operation may only return to Running through an explicit controlled resume/recovery",
                {"current": current.value, "target": target.value},
            )
    return ValidationResult(True)


def get_allowed_operation_transitions(status: OperationStatus) -> frozenset[OperationStatus]:
    """Return allowed target statuses from a given OperationStatus."""
    return frozenset(_OPERATION_TRANSITIONS.get(status, set()))


def is_operation_terminal(status: OperationStatus) -> bool:
    """Check whether an operation status is terminal (never resumable)."""
    return status in _OPERATION_TERMINAL


def is_operation_recoverable(status: OperationStatus) -> bool:
    """Check whether an operation in this status is recoverable."""
    return status in _OPERATION_RECOVERABLE


# ── Durable Approval State Transition Rules (Phase 18-J.5) ───────────────

_APPROVAL_TRANSITIONS: dict[DurableApprovalStatus, set[DurableApprovalStatus]] = {
    DurableApprovalStatus.PENDING: {
        DurableApprovalStatus.APPROVED,
        DurableApprovalStatus.REJECTED,
        DurableApprovalStatus.CANCELLED,
        DurableApprovalStatus.EXPIRED,
    },
    DurableApprovalStatus.APPROVED: set(),
    DurableApprovalStatus.REJECTED: set(),
    DurableApprovalStatus.CANCELLED: set(),
    DurableApprovalStatus.EXPIRED: set(),
}

_APPROVAL_TERMINAL: set[DurableApprovalStatus] = {
    DurableApprovalStatus.APPROVED,
    DurableApprovalStatus.REJECTED,
    DurableApprovalStatus.CANCELLED,
    DurableApprovalStatus.EXPIRED,
}

_APPROVAL_RECOVERABLE: set[DurableApprovalStatus] = {
    DurableApprovalStatus.PENDING,
}


def validate_approval_transition(
    current: DurableApprovalStatus,
    target: DurableApprovalStatus,
    *,
    metadata: dict[str, Any] | None = None,
) -> ValidationResult:
    """Validate a durable approval request state transition."""
    err = _check_base(current, _APPROVAL_TRANSITIONS, _APPROVAL_TERMINAL, "approval")
    if err:
        return err
    err = _check_allowed(current, target, _APPROVAL_TRANSITIONS, "approval")
    if err:
        return err
    return ValidationResult(True)


def get_allowed_approval_transitions(status: DurableApprovalStatus) -> frozenset[DurableApprovalStatus]:
    """Return allowed target statuses from a given DurableApprovalStatus."""
    return frozenset(_APPROVAL_TRANSITIONS.get(status, set()))


def is_approval_terminal(status: DurableApprovalStatus) -> bool:
    """Check whether an approval status is terminal (never mutable)."""
    return status in _APPROVAL_TERMINAL


def is_approval_recoverable(status: DurableApprovalStatus) -> bool:
    """Check whether an approval in this status is active/recoverable."""
    return status in _APPROVAL_RECOVERABLE