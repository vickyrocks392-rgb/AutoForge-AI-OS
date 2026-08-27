"""
Phase 9 — DAG engine tests.

Covers:
- Building a DAG from a WorkflowDefinition.
- Cycle detection.
- Topological ordering determinism.
- Dependency readiness queries.
- Blocking detection.
- Independent task detection.
- Self-edge rejection.
- Unknown task ID rejection.
"""

from __future__ import annotations

import pytest

from autoforge_workflows.dag import WorkflowDAG
from autoforge_workflows.errors import CycleDetectedError, DependencyError, WorkflowValidationError
from autoforge_workflows.models import (
    DependencyEdge,
    DependencyPolicy,
    TaskDefinition,
    WorkflowDefinition,
    WorkflowTaskStatus,
)


def _task(task_id: str, priority: str = "medium") -> TaskDefinition:
    return TaskDefinition(task_id=task_id, name=task_id, priority=priority)


def _wf(*task_ids: str, deps: list[tuple[str, str]] | None = None) -> WorkflowDefinition:
    tasks = [_task(tid) for tid in task_ids]
    edges = [
        DependencyEdge(upstream_task_id=up, downstream_task_id=down)
        for up, down in (deps or [])
    ]
    return WorkflowDefinition(name="test", tasks=tasks, dependencies=edges)


class TestDAGConstruction:
    """Tests for WorkflowDAG.from_definition()."""

    def test_single_task(self) -> None:
        dag = WorkflowDAG.from_definition(_wf("t1"))
        assert "t1" in dag.task_ids
        assert dag.roots() == ["t1"]
        assert dag.leaves() == ["t1"]

    def test_linear_chain(self) -> None:
        # t1 → t2 → t3
        dag = WorkflowDAG.from_definition(_wf("t1", "t2", "t3", deps=[("t1", "t2"), ("t2", "t3")]))
        order = dag.topological_order
        assert order.index("t1") < order.index("t2")
        assert order.index("t2") < order.index("t3")

    def test_fan_out(self) -> None:
        # t1 → t2, t1 → t3
        dag = WorkflowDAG.from_definition(_wf("t1", "t2", "t3", deps=[("t1", "t2"), ("t1", "t3")]))
        assert "t1" in dag.roots()
        assert set(dag.downstream_of("t1")) == {"t2", "t3"}

    def test_fan_in(self) -> None:
        # t1 → t3, t2 → t3
        dag = WorkflowDAG.from_definition(_wf("t1", "t2", "t3", deps=[("t1", "t3"), ("t2", "t3")]))
        assert set(dag.upstream_of("t3")) == {"t1", "t2"}
        assert dag.leaves() == ["t3"]

    def test_diamond_shape(self) -> None:
        # t1 → t2, t1 → t3, t2 → t4, t3 → t4
        dag = WorkflowDAG.from_definition(_wf(
            "t1", "t2", "t3", "t4",
            deps=[("t1", "t2"), ("t1", "t3"), ("t2", "t4"), ("t3", "t4")]
        ))
        order = dag.topological_order
        assert order[0] == "t1"
        assert order[-1] == "t4"
        # t2 and t3 between t1 and t4 (order between them is lexicographic)
        assert set(order[1:3]) == {"t2", "t3"}

    def test_deterministic_ordering(self) -> None:
        """Same definition should produce the same topological order every time."""
        wf = _wf("t1", "t2", "t3", "t4", deps=[("t1", "t3"), ("t2", "t4")])
        order_a = WorkflowDAG.from_definition(wf).topological_order
        order_b = WorkflowDAG.from_definition(wf).topological_order
        assert order_a == order_b


class TestCycleDetection:
    """Tests for Kahn's cycle detection."""

    def test_direct_cycle(self) -> None:
        with pytest.raises(CycleDetectedError) as exc_info:
            WorkflowDAG.from_definition(_wf("t1", "t2", deps=[("t1", "t2"), ("t2", "t1")]))
        assert "t1" in str(exc_info.value) or "t2" in str(exc_info.value)

    def test_self_cycle_rejected_before_sort(self) -> None:
        # Self-edges are caught before the sort.
        with pytest.raises(WorkflowValidationError):
            WorkflowDAG.from_definition(_wf("t1", deps=[("t1", "t1")]))

    def test_three_node_cycle(self) -> None:
        with pytest.raises(CycleDetectedError):
            WorkflowDAG.from_definition(_wf(
                "a", "b", "c",
                deps=[("a", "b"), ("b", "c"), ("c", "a")]
            ))

    def test_no_false_positive_diamond(self) -> None:
        # Diamond is NOT a cycle.
        dag = WorkflowDAG.from_definition(_wf(
            "t1", "t2", "t3", "t4",
            deps=[("t1", "t2"), ("t1", "t3"), ("t2", "t4"), ("t3", "t4")]
        ))
        assert len(dag.topological_order) == 4


class TestDAGEdgeValidation:
    """Tests for edge validation during DAG construction."""

    def test_unknown_upstream_rejected(self) -> None:
        with pytest.raises(DependencyError):
            WorkflowDAG.from_definition(_wf("t1", deps=[("ghost", "t1")]))

    def test_unknown_downstream_rejected(self) -> None:
        with pytest.raises(DependencyError):
            WorkflowDAG.from_definition(_wf("t1", deps=[("t1", "ghost")]))

    def test_duplicate_task_ids_rejected(self) -> None:
        tasks = [_task("dup"), _task("dup")]
        wf = WorkflowDefinition(name="bad", tasks=tasks)
        with pytest.raises(WorkflowValidationError):
            WorkflowDAG.from_definition(wf)


class TestDependencyReadiness:
    """Tests for is_dependency_satisfied() and get_ready_tasks()."""

    def test_root_task_always_ready(self) -> None:
        dag = WorkflowDAG.from_definition(_wf("t1", "t2", deps=[("t1", "t2")]))
        statuses = {
            "t1": WorkflowTaskStatus.PENDING,
            "t2": WorkflowTaskStatus.PENDING,
        }
        assert dag.is_dependency_satisfied("t1", statuses) is True

    def test_downstream_not_ready_when_upstream_pending(self) -> None:
        dag = WorkflowDAG.from_definition(_wf("t1", "t2", deps=[("t1", "t2")]))
        statuses = {
            "t1": WorkflowTaskStatus.PENDING,
            "t2": WorkflowTaskStatus.PENDING,
        }
        assert dag.is_dependency_satisfied("t2", statuses) is False

    def test_downstream_ready_when_upstream_succeeded(self) -> None:
        dag = WorkflowDAG.from_definition(_wf("t1", "t2", deps=[("t1", "t2")]))
        statuses = {
            "t1": WorkflowTaskStatus.SUCCEEDED,
            "t2": WorkflowTaskStatus.PENDING,
        }
        assert dag.is_dependency_satisfied("t2", statuses) is True

    def test_get_ready_tasks_linear(self) -> None:
        dag = WorkflowDAG.from_definition(_wf("t1", "t2", deps=[("t1", "t2")]))
        statuses = {
            "t1": WorkflowTaskStatus.PENDING,
            "t2": WorkflowTaskStatus.PENDING,
        }
        ready = dag.get_ready_tasks(statuses)
        assert ready == ["t1"]

    def test_get_ready_tasks_after_completion(self) -> None:
        dag = WorkflowDAG.from_definition(_wf("t1", "t2", deps=[("t1", "t2")]))
        statuses = {
            "t1": WorkflowTaskStatus.SUCCEEDED,
            "t2": WorkflowTaskStatus.PENDING,
        }
        ready = dag.get_ready_tasks(statuses)
        assert ready == ["t2"]

    def test_continue_on_failure_satisfied_when_upstream_failed(self) -> None:
        tasks = [_task("t1"), _task("t2")]
        edges = [DependencyEdge(
            upstream_task_id="t1",
            downstream_task_id="t2",
            policy=DependencyPolicy.CONTINUE_ON_FAILURE,
        )]
        wf = WorkflowDefinition(name="test", tasks=tasks, dependencies=edges)
        dag = WorkflowDAG.from_definition(wf)
        statuses = {
            "t1": WorkflowTaskStatus.FAILED,
            "t2": WorkflowTaskStatus.PENDING,
        }
        assert dag.is_dependency_satisfied(
            "t2", statuses, default_policy=DependencyPolicy.REQUIRE_ALL_SUCCESS
        ) is True

    def test_continue_on_failure_not_satisfied_when_upstream_running(self) -> None:
        tasks = [_task("t1"), _task("t2")]
        edges = [DependencyEdge(
            upstream_task_id="t1",
            downstream_task_id="t2",
            policy=DependencyPolicy.CONTINUE_ON_FAILURE,
        )]
        wf = WorkflowDefinition(name="test", tasks=tasks, dependencies=edges)
        dag = WorkflowDAG.from_definition(wf)
        statuses = {
            "t1": WorkflowTaskStatus.RUNNING,
            "t2": WorkflowTaskStatus.PENDING,
        }
        assert dag.is_dependency_satisfied(
            "t2", statuses, default_policy=DependencyPolicy.REQUIRE_ALL_SUCCESS
        ) is False


class TestBlockingDetection:
    """Tests for is_blocked_by_failure()."""

    def test_blocked_when_upstream_failed_require_all(self) -> None:
        dag = WorkflowDAG.from_definition(_wf("t1", "t2", deps=[("t1", "t2")]))
        statuses = {
            "t1": WorkflowTaskStatus.FAILED,
            "t2": WorkflowTaskStatus.PENDING,
        }
        assert dag.is_blocked_by_failure("t2", statuses) is True

    def test_not_blocked_when_upstream_succeeded(self) -> None:
        dag = WorkflowDAG.from_definition(_wf("t1", "t2", deps=[("t1", "t2")]))
        statuses = {
            "t1": WorkflowTaskStatus.SUCCEEDED,
            "t2": WorkflowTaskStatus.PENDING,
        }
        assert dag.is_blocked_by_failure("t2", statuses) is False

    def test_not_blocked_when_no_dependencies(self) -> None:
        dag = WorkflowDAG.from_definition(_wf("t1"))
        statuses = {"t1": WorkflowTaskStatus.PENDING}
        assert dag.is_blocked_by_failure("t1", statuses) is False


class TestDAGSummary:
    """Tests for the summary() method."""

    def test_summary_keys(self) -> None:
        dag = WorkflowDAG.from_definition(_wf("t1", "t2", deps=[("t1", "t2")]))
        summary = dag.summary()
        assert "task_count" in summary
        assert "edge_count" in summary
        assert "roots" in summary
        assert "leaves" in summary
        assert "topological_order" in summary

    def test_summary_counts(self) -> None:
        dag = WorkflowDAG.from_definition(_wf("t1", "t2", deps=[("t1", "t2")]))
        summary = dag.summary()
        assert summary["task_count"] == 2
        assert summary["edge_count"] == 1
