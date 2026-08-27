"""
WorkflowTaskStatus state machine — Phase 9.

Defines the deterministic transition table for workflow task lifecycle states
and validates all transitions at the boundary.

This is COMPLETELY deterministic — no AI judgment, no model inference.
Every decision is a pure table lookup with an explicit error on violation.

Transition table
----------------
PENDING          -> READY | CANCELLED
READY            -> RUNNING | BLOCKED | CANCELLED
RUNNING          -> SUCCEEDED | FAILED | WAITING_APPROVAL | CANCELLED
BLOCKED          -> READY | CANCELLED
WAITING_APPROVAL -> RUNNING | CANCELLED
RETRYING         -> RUNNING | FAILED
FAILED           -> RETRYING | CANCELLED   (caller checks retry eligibility first)
SUCCEEDED        (terminal — no outgoing transitions)
CANCELLED        (terminal — no outgoing transitions)
"""

from __future__ import annotations

from autoforge_workflows.errors import WorkflowValidationError
from autoforge_workflows.models import WorkflowTaskStatus

# ── Deterministic Transition Table ────────────────────────────────────────

_TASK_TRANSITIONS: dict[WorkflowTaskStatus, frozenset[WorkflowTaskStatus]] = {
    WorkflowTaskStatus.PENDING: frozenset({
        WorkflowTaskStatus.READY,
        WorkflowTaskStatus.BLOCKED,
        WorkflowTaskStatus.CANCELLED,
    }),
    WorkflowTaskStatus.READY: frozenset({
        WorkflowTaskStatus.RUNNING,
        WorkflowTaskStatus.BLOCKED,
        WorkflowTaskStatus.CANCELLED,
    }),
    WorkflowTaskStatus.RUNNING: frozenset({
        WorkflowTaskStatus.SUCCEEDED,
        WorkflowTaskStatus.FAILED,
        WorkflowTaskStatus.WAITING_APPROVAL,
        WorkflowTaskStatus.CANCELLED,
    }),
    WorkflowTaskStatus.BLOCKED: frozenset({
        WorkflowTaskStatus.READY,
        WorkflowTaskStatus.CANCELLED,
    }),
    WorkflowTaskStatus.WAITING_APPROVAL: frozenset({
        WorkflowTaskStatus.RUNNING,
        WorkflowTaskStatus.CANCELLED,
    }),
    WorkflowTaskStatus.RETRYING: frozenset({
        WorkflowTaskStatus.RUNNING,
        WorkflowTaskStatus.FAILED,
    }),
    WorkflowTaskStatus.FAILED: frozenset({
        WorkflowTaskStatus.RETRYING,
        WorkflowTaskStatus.CANCELLED,
    }),
    WorkflowTaskStatus.SUCCEEDED: frozenset(),   # terminal
    WorkflowTaskStatus.CANCELLED: frozenset(),   # terminal
}

_TERMINAL_STATES: frozenset[WorkflowTaskStatus] = frozenset({
    WorkflowTaskStatus.SUCCEEDED,
    WorkflowTaskStatus.CANCELLED,
})

# FAILED is terminal when retry limit is exhausted, but the engine handles
# that logic; the transition table still allows FAILED -> RETRYING so the
# engine can record the decision before checking the counter.


def validate_workflow_task_transition(
    current: WorkflowTaskStatus,
    target: WorkflowTaskStatus,
    *,
    task_id: str | None = None,
) -> None:
    """
    Validate a WorkflowTaskStatus transition.

    Args:
        current: Current task status.
        target: Desired target status.
        task_id: Optional task identifier for error messages.

    Raises:
        WorkflowValidationError: If the transition is not permitted.
    """
    allowed = _TASK_TRANSITIONS.get(current, frozenset())
    if target not in allowed:
        label = f" (task_id={task_id!r})" if task_id else ""
        raise WorkflowValidationError(
            f"Invalid task status transition: "
            f"{current.value!r} -> {target.value!r}{label}",
            details={
                "current": current.value,
                "target": target.value,
                "allowed": sorted(s.value for s in allowed),
                "task_id": task_id,
            },
        )


def get_allowed_transitions(
    current: WorkflowTaskStatus,
) -> frozenset[WorkflowTaskStatus]:
    """Return the set of allowed target statuses from current."""
    return _TASK_TRANSITIONS.get(current, frozenset())


def is_terminal(status: WorkflowTaskStatus) -> bool:
    """Return True if the status is a terminal state (no further transitions)."""
    return status in _TERMINAL_STATES


def is_successful_terminal(status: WorkflowTaskStatus) -> bool:
    """Return True if the status represents a successful terminal state."""
    return status == WorkflowTaskStatus.SUCCEEDED


def is_failed_terminal(status: WorkflowTaskStatus, attempt: int, max_attempts: int) -> bool:
    """
    Return True if the task is in a permanently failed terminal state.

    A task is terminally failed when it is in FAILED status AND has
    exhausted all retry attempts (attempt >= max_attempts).
    """
    return status == WorkflowTaskStatus.FAILED and attempt >= max_attempts
