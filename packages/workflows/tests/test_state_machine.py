"""
Phase 9 — Task state machine tests.

Covers:
- All valid transitions are accepted.
- All invalid transitions are rejected.
- Terminal states have no allowed outgoing transitions.
- is_terminal() predicate.
- is_failed_terminal() predicate.
"""

from __future__ import annotations

import pytest

from autoforge_workflows.errors import WorkflowValidationError
from autoforge_workflows.models import WorkflowTaskStatus
from autoforge_workflows.state import (
    get_allowed_transitions,
    is_terminal,
    is_failed_terminal,
    is_successful_terminal,
    validate_workflow_task_transition,
)

# All transitions that SHOULD be valid.
VALID_TRANSITIONS = [
    (WorkflowTaskStatus.PENDING, WorkflowTaskStatus.READY),
    (WorkflowTaskStatus.PENDING, WorkflowTaskStatus.CANCELLED),
    (WorkflowTaskStatus.READY, WorkflowTaskStatus.RUNNING),
    (WorkflowTaskStatus.READY, WorkflowTaskStatus.BLOCKED),
    (WorkflowTaskStatus.READY, WorkflowTaskStatus.CANCELLED),
    (WorkflowTaskStatus.RUNNING, WorkflowTaskStatus.SUCCEEDED),
    (WorkflowTaskStatus.RUNNING, WorkflowTaskStatus.FAILED),
    (WorkflowTaskStatus.RUNNING, WorkflowTaskStatus.WAITING_APPROVAL),
    (WorkflowTaskStatus.RUNNING, WorkflowTaskStatus.CANCELLED),
    (WorkflowTaskStatus.BLOCKED, WorkflowTaskStatus.READY),
    (WorkflowTaskStatus.BLOCKED, WorkflowTaskStatus.CANCELLED),
    (WorkflowTaskStatus.WAITING_APPROVAL, WorkflowTaskStatus.RUNNING),
    (WorkflowTaskStatus.WAITING_APPROVAL, WorkflowTaskStatus.CANCELLED),
    (WorkflowTaskStatus.RETRYING, WorkflowTaskStatus.RUNNING),
    (WorkflowTaskStatus.RETRYING, WorkflowTaskStatus.FAILED),
    (WorkflowTaskStatus.FAILED, WorkflowTaskStatus.RETRYING),
    (WorkflowTaskStatus.FAILED, WorkflowTaskStatus.CANCELLED),
]

# Sample invalid transitions.
INVALID_TRANSITIONS = [
    (WorkflowTaskStatus.PENDING, WorkflowTaskStatus.RUNNING),
    (WorkflowTaskStatus.PENDING, WorkflowTaskStatus.SUCCEEDED),
    (WorkflowTaskStatus.PENDING, WorkflowTaskStatus.FAILED),
    (WorkflowTaskStatus.SUCCEEDED, WorkflowTaskStatus.RUNNING),
    (WorkflowTaskStatus.SUCCEEDED, WorkflowTaskStatus.PENDING),
    (WorkflowTaskStatus.CANCELLED, WorkflowTaskStatus.RUNNING),
    (WorkflowTaskStatus.CANCELLED, WorkflowTaskStatus.PENDING),
    (WorkflowTaskStatus.RUNNING, WorkflowTaskStatus.PENDING),
    (WorkflowTaskStatus.RUNNING, WorkflowTaskStatus.BLOCKED),
    (WorkflowTaskStatus.FAILED, WorkflowTaskStatus.RUNNING),  # must go via RETRYING
]


class TestValidTransitions:
    """All valid state transitions are accepted."""

    @pytest.mark.parametrize("current, target", VALID_TRANSITIONS)
    def test_valid_transition_accepted(
        self, current: WorkflowTaskStatus, target: WorkflowTaskStatus
    ) -> None:
        # Should not raise.
        validate_workflow_task_transition(current, target)

    @pytest.mark.parametrize("current, target", VALID_TRANSITIONS)
    def test_with_task_id(
        self, current: WorkflowTaskStatus, target: WorkflowTaskStatus
    ) -> None:
        validate_workflow_task_transition(current, target, task_id="task-99")


class TestInvalidTransitions:
    """Invalid state transitions raise WorkflowValidationError."""

    @pytest.mark.parametrize("current, target", INVALID_TRANSITIONS)
    def test_invalid_transition_rejected(
        self, current: WorkflowTaskStatus, target: WorkflowTaskStatus
    ) -> None:
        with pytest.raises(WorkflowValidationError) as exc_info:
            validate_workflow_task_transition(current, target, task_id="t1")
        err = exc_info.value
        assert "t1" in str(err)
        assert err.details["current"] == current.value
        assert err.details["target"] == target.value


class TestTerminalStates:
    """SUCCEEDED and CANCELLED are terminal — no outgoing transitions."""

    def test_succeeded_is_terminal(self) -> None:
        assert is_terminal(WorkflowTaskStatus.SUCCEEDED) is True

    def test_cancelled_is_terminal(self) -> None:
        assert is_terminal(WorkflowTaskStatus.CANCELLED) is True

    def test_failed_not_terminal(self) -> None:
        # FAILED can transition to RETRYING or CANCELLED.
        assert is_terminal(WorkflowTaskStatus.FAILED) is False

    def test_non_terminal_states(self) -> None:
        for s in [
            WorkflowTaskStatus.PENDING,
            WorkflowTaskStatus.READY,
            WorkflowTaskStatus.RUNNING,
            WorkflowTaskStatus.BLOCKED,
            WorkflowTaskStatus.WAITING_APPROVAL,
            WorkflowTaskStatus.RETRYING,
            WorkflowTaskStatus.FAILED,
        ]:
            assert is_terminal(s) is False, f"{s} should not be terminal"

    def test_succeeded_has_no_allowed_transitions(self) -> None:
        allowed = get_allowed_transitions(WorkflowTaskStatus.SUCCEEDED)
        assert len(allowed) == 0

    def test_cancelled_has_no_allowed_transitions(self) -> None:
        allowed = get_allowed_transitions(WorkflowTaskStatus.CANCELLED)
        assert len(allowed) == 0


class TestSuccessfulTerminal:
    """is_successful_terminal() identifies SUCCEEDED."""

    def test_succeeded_is_successful(self) -> None:
        assert is_successful_terminal(WorkflowTaskStatus.SUCCEEDED) is True

    def test_cancelled_not_successful(self) -> None:
        assert is_successful_terminal(WorkflowTaskStatus.CANCELLED) is False

    def test_failed_not_successful(self) -> None:
        assert is_successful_terminal(WorkflowTaskStatus.FAILED) is False


class TestFailedTerminal:
    """is_failed_terminal() is True when FAILED and retries exhausted."""

    def test_failed_with_no_retries(self) -> None:
        assert is_failed_terminal(WorkflowTaskStatus.FAILED, attempt=3, max_attempts=3) is True

    def test_failed_with_retries_remaining(self) -> None:
        assert is_failed_terminal(WorkflowTaskStatus.FAILED, attempt=1, max_attempts=3) is False

    def test_succeeded_not_failed_terminal(self) -> None:
        assert is_failed_terminal(WorkflowTaskStatus.SUCCEEDED, attempt=1, max_attempts=3) is False


class TestGetAllowedTransitions:
    """get_allowed_transitions() returns correct sets."""

    def test_pending_can_go_to_ready_or_cancelled(self) -> None:
        allowed = get_allowed_transitions(WorkflowTaskStatus.PENDING)
        assert WorkflowTaskStatus.READY in allowed
        assert WorkflowTaskStatus.CANCELLED in allowed

    def test_running_can_succeed_fail_or_wait(self) -> None:
        allowed = get_allowed_transitions(WorkflowTaskStatus.RUNNING)
        assert WorkflowTaskStatus.SUCCEEDED in allowed
        assert WorkflowTaskStatus.FAILED in allowed
        assert WorkflowTaskStatus.WAITING_APPROVAL in allowed
