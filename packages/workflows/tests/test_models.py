"""
Phase 9 Workflow Platform — test suite.

Tests cover:
- WorkflowDefinition and TaskDefinition model validation
- RetryPolicy factories
- ExecutionPolicy defaults
- ApprovalGatePolicy validation
- DependencyEdge model
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from autoforge_workflows.models import (
    ApprovalGatePolicy,
    BackoffStrategy,
    DependencyEdge,
    DependencyPolicy,
    ExecutionPolicy,
    FailureAction,
    RetryPolicy,
    TaskDefinition,
    WorkflowDefinition,
    WorkflowTaskStatus,
)


class TestRetryPolicy:
    """Tests for RetryPolicy value object."""

    def test_default_factory(self) -> None:
        policy = RetryPolicy.default()
        assert policy.max_attempts == 3
        assert policy.backoff_strategy == BackoffStrategy.EXPONENTIAL
        assert policy.base_delay_seconds == 1.0

    def test_no_retry_factory(self) -> None:
        policy = RetryPolicy.no_retry()
        assert policy.max_attempts == 1

    def test_frozen(self) -> None:
        policy = RetryPolicy.default()
        with pytest.raises((TypeError, ValidationError)):
            policy.max_attempts = 10  # type: ignore[misc]

    def test_retryable_codes_default_empty(self) -> None:
        policy = RetryPolicy()
        assert len(policy.retryable_error_codes) == 0

    def test_non_retryable_codes(self) -> None:
        policy = RetryPolicy(non_retryable_error_codes=frozenset({"AUTH_FAILURE"}))
        assert "AUTH_FAILURE" in policy.non_retryable_error_codes

    def test_max_attempts_bounds(self) -> None:
        with pytest.raises(ValidationError):
            RetryPolicy(max_attempts=0)
        with pytest.raises(ValidationError):
            RetryPolicy(max_attempts=21)


class TestExecutionPolicy:
    """Tests for ExecutionPolicy value object."""

    def test_defaults(self) -> None:
        policy = ExecutionPolicy()
        assert policy.max_concurrent_tasks == 4
        assert policy.dependency_policy == DependencyPolicy.REQUIRE_ALL_SUCCESS
        assert policy.failure_action == FailureAction.FAIL_WORKFLOW
        assert policy.timeout_seconds is None

    def test_concurrent_tasks_bounds(self) -> None:
        with pytest.raises(ValidationError):
            ExecutionPolicy(max_concurrent_tasks=0)
        with pytest.raises(ValidationError):
            ExecutionPolicy(max_concurrent_tasks=65)

    def test_frozen(self) -> None:
        policy = ExecutionPolicy()
        with pytest.raises((TypeError, ValidationError)):
            policy.max_concurrent_tasks = 2  # type: ignore[misc]


class TestApprovalGatePolicy:
    """Tests for ApprovalGatePolicy value object."""

    def test_basic_creation(self) -> None:
        gate = ApprovalGatePolicy(gate_id="gate-1", description="Deploy to prod")
        assert gate.gate_id == "gate-1"
        assert gate.required_approvers == 1

    def test_empty_gate_id_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ApprovalGatePolicy(gate_id="")


class TestTaskDefinition:
    """Tests for TaskDefinition value object."""

    def test_minimal_definition(self) -> None:
        task = TaskDefinition(task_id="task-1", name="Write tests")
        assert task.task_id == "task-1"
        assert task.priority == "medium"
        assert task.approval_gate is None

    def test_invalid_priority_rejected(self) -> None:
        with pytest.raises(ValidationError):
            TaskDefinition(task_id="t1", name="t1", priority="ultra")

    def test_all_priorities_accepted(self) -> None:
        for p in ("low", "medium", "high", "critical"):
            task = TaskDefinition(task_id=f"t-{p}", name=p, priority=p)
            assert task.priority == p

    def test_task_type_default(self) -> None:
        task = TaskDefinition(task_id="t1", name="t1")
        assert task.task_type == "general"

    def test_with_approval_gate(self) -> None:
        gate = ApprovalGatePolicy(gate_id="deploy-gate")
        task = TaskDefinition(task_id="deploy", name="Deploy", approval_gate=gate)
        assert task.approval_gate is not None
        assert task.approval_gate.gate_id == "deploy-gate"

    def test_frozen(self) -> None:
        task = TaskDefinition(task_id="t1", name="t1")
        with pytest.raises((TypeError, ValidationError)):
            task.task_id = "different"  # type: ignore[misc]


class TestDependencyEdge:
    """Tests for DependencyEdge value object."""

    def test_basic_edge(self) -> None:
        edge = DependencyEdge(
            upstream_task_id="a",
            downstream_task_id="b",
        )
        assert edge.policy == DependencyPolicy.REQUIRE_ALL_SUCCESS

    def test_continue_on_failure_policy(self) -> None:
        edge = DependencyEdge(
            upstream_task_id="a",
            downstream_task_id="b",
            policy=DependencyPolicy.CONTINUE_ON_FAILURE,
        )
        assert edge.policy == DependencyPolicy.CONTINUE_ON_FAILURE


class TestWorkflowDefinition:
    """Tests for WorkflowDefinition value object."""

    def _make_task(self, task_id: str) -> TaskDefinition:
        return TaskDefinition(task_id=task_id, name=task_id)

    def test_minimal_definition(self) -> None:
        wf = WorkflowDefinition(
            name="My workflow",
            tasks=[self._make_task("t1"), self._make_task("t2")],
        )
        assert wf.name == "My workflow"
        assert len(wf.tasks) == 2
        assert wf.version == "1.0.0"

    def test_empty_tasks_rejected(self) -> None:
        with pytest.raises(ValidationError):
            WorkflowDefinition(name="Empty", tasks=[])

    def test_unique_workflow_ids(self) -> None:
        wf1 = WorkflowDefinition(name="A", tasks=[self._make_task("t1")])
        wf2 = WorkflowDefinition(name="B", tasks=[self._make_task("t1")])
        assert wf1.workflow_id != wf2.workflow_id

    def test_frozen(self) -> None:
        wf = WorkflowDefinition(name="A", tasks=[self._make_task("t1")])
        with pytest.raises((TypeError, ValidationError)):
            wf.name = "B"  # type: ignore[misc]

    def test_with_dependencies(self) -> None:
        wf = WorkflowDefinition(
            name="Chained",
            tasks=[self._make_task("t1"), self._make_task("t2")],
            dependencies=[
                DependencyEdge(upstream_task_id="t1", downstream_task_id="t2")
            ],
        )
        assert len(wf.dependencies) == 1
        assert wf.dependencies[0].upstream_task_id == "t1"


class TestWorkflowTaskStatus:
    """Tests for WorkflowTaskStatus enum."""

    def test_all_values_accessible(self) -> None:
        statuses = [s.value for s in WorkflowTaskStatus]
        assert "pending" in statuses
        assert "ready" in statuses
        assert "running" in statuses
        assert "succeeded" in statuses
        assert "failed" in statuses
        assert "retrying" in statuses
        assert "blocked" in statuses
        assert "waiting_approval" in statuses
        assert "cancelled" in statuses

    def test_str_enum_equality(self) -> None:
        assert WorkflowTaskStatus.PENDING == "pending"
        assert WorkflowTaskStatus.SUCCEEDED == "succeeded"
