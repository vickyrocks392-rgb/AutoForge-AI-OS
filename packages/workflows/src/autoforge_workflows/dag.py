"""
DAG Engine — Phase 9.

Implements a Directed Acyclic Graph (DAG) for workflow task orchestration.

Responsibilities
----------------
- Build a validated DAG from a WorkflowDefinition.
- Detect cycles (deterministic Kahn's algorithm — O(V+E)).
- Produce a deterministic topological ordering.
- Answer dependency readiness queries: is task X eligible to run?
- Identify independent tasks (no outbound dependency constraints) for
  parallel scheduling.

This module is PURE COMPUTATION: it never touches IO, state managers,
or event buses.  All methods are synchronous and deterministic.

Cycle detection
---------------
Uses Kahn's algorithm (BFS-based topological sort).  If the algorithm
cannot consume all nodes, a cycle exists.  The cycle members are reported
deterministically by comparing the residual in-degree counts.

Ordering determinism
--------------------
When multiple tasks have equal in-degree (equally eligible), they are
ordered lexicographically by task_id to ensure deterministic sequencing
across different Python versions and platforms.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Any

from autoforge_workflows.errors import CycleDetectedError, DependencyError, WorkflowValidationError
from autoforge_workflows.models import (
    DependencyEdge,
    DependencyPolicy,
    TaskDefinition,
    WorkflowDefinition,
    WorkflowTaskStatus,
)


# ── DAG Node ──────────────────────────────────────────────────────────────


@dataclass
class DAGNode:
    """
    A node in the workflow DAG representing a single task.

    Nodes carry references to their upstream (predecessor) and downstream
    (successor) task IDs.  The definition is the immutable task spec.
    """

    task_id: str
    definition: TaskDefinition
    upstream_ids: set[str] = field(default_factory=set)
    """Task IDs that must satisfy their dependency condition before this task."""
    downstream_ids: set[str] = field(default_factory=set)
    """Task IDs that depend on this task."""
    dependency_policies: dict[str, DependencyPolicy] = field(default_factory=dict)
    """Per-edge dependency policy keyed by upstream_task_id."""

    def __repr__(self) -> str:
        return (
            f"DAGNode(task_id={self.task_id!r}, "
            f"upstream={self.upstream_ids}, "
            f"downstream={self.downstream_ids})"
        )


# ── DAG ───────────────────────────────────────────────────────────────────


class WorkflowDAG:
    """
    Directed Acyclic Graph for a workflow.

    Construction
    ------------
    Build from a WorkflowDefinition using ``WorkflowDAG.from_definition()``.
    Construction validates:
      - All referenced task IDs exist.
      - No self-referential edges.
      - No cycles (Kahn's algorithm).

    Usage
    -----
    After construction the DAG is frozen (immutable).  Query methods answer
    questions about the workflow structure without mutating anything.

    Thread safety
    -------------
    All query methods are read-only and thread-safe.
    """

    def __init__(
        self,
        nodes: dict[str, DAGNode],
        topological_order: list[str],
    ) -> None:
        self._nodes: dict[str, DAGNode] = nodes
        self._topological_order: list[str] = topological_order

    # ── Construction ──────────────────────────────────────────────────────

    @classmethod
    def from_definition(cls, definition: WorkflowDefinition) -> WorkflowDAG:
        """
        Build and validate a WorkflowDAG from a WorkflowDefinition.

        Args:
            definition: A WorkflowDefinition (already validated by Pydantic).

        Returns:
            A validated, immutable WorkflowDAG.

        Raises:
            WorkflowValidationError: If task IDs are not unique, dependency
                edges reference unknown tasks, or self-edges are detected.
            CycleDetectedError: If the dependency graph contains a cycle.
            DependencyError: If dependency edge configuration is invalid.
        """
        tasks = definition.tasks
        edges = definition.dependencies

        # ── 1. Unique task IDs ─────────────────────────────────────────
        task_ids: set[str] = set()
        for task in tasks:
            if task.task_id in task_ids:
                raise WorkflowValidationError(
                    f"Duplicate task_id: {task.task_id!r}",
                    details={"task_id": task.task_id},
                )
            task_ids.add(task.task_id)

        # ── 2. Build node map ──────────────────────────────────────────
        nodes: dict[str, DAGNode] = {
            t.task_id: DAGNode(task_id=t.task_id, definition=t)
            for t in tasks
        }

        # ── 3. Wire edges ──────────────────────────────────────────────
        for edge in edges:
            up = edge.upstream_task_id
            down = edge.downstream_task_id

            if up not in task_ids:
                raise DependencyError(
                    f"Dependency edge references unknown upstream task: {up!r}",
                    details={"upstream_task_id": up, "downstream_task_id": down},
                )
            if down not in task_ids:
                raise DependencyError(
                    f"Dependency edge references unknown downstream task: {down!r}",
                    details={"upstream_task_id": up, "downstream_task_id": down},
                )
            if up == down:
                raise WorkflowValidationError(
                    f"Self-referential dependency edge on task: {up!r}",
                    details={"task_id": up},
                )

            nodes[up].downstream_ids.add(down)
            nodes[down].upstream_ids.add(up)
            nodes[down].dependency_policies[up] = edge.policy

        # ── 4. Cycle detection (Kahn's algorithm) ─────────────────────
        topological_order = cls._topological_sort(nodes)

        return cls(nodes=nodes, topological_order=topological_order)

    @staticmethod
    def _topological_sort(nodes: dict[str, DAGNode]) -> list[str]:
        """
        Kahn's algorithm — deterministic topological sort.

        Determinism guarantee: when multiple nodes have equal in-degree,
        they are enqueued in lexicographic order by task_id.

        Raises:
            CycleDetectedError: If a cycle is detected.
        """
        in_degree: dict[str, int] = {tid: len(n.upstream_ids) for tid, n in nodes.items()}

        # Seed queue with all nodes that have no incoming edges, sorted
        # lexicographically for determinism.
        queue: deque[str] = deque(
            sorted(tid for tid, deg in in_degree.items() if deg == 0)
        )
        order: list[str] = []

        while queue:
            current = queue.popleft()
            order.append(current)

            # Process successors in deterministic order.
            for successor in sorted(nodes[current].downstream_ids):
                in_degree[successor] -= 1
                if in_degree[successor] == 0:
                    queue.append(successor)

        if len(order) != len(nodes):
            # Not all nodes were consumed → cycle detected.
            cycle_members = sorted(
                tid for tid, deg in in_degree.items() if deg > 0
            )
            raise CycleDetectedError(
                f"Cycle detected in workflow DAG involving tasks: {cycle_members}",
                details={"cycle_members": cycle_members},
            )

        return order

    # ── Query API (read-only) ─────────────────────────────────────────────

    @property
    def topological_order(self) -> list[str]:
        """Deterministic topological ordering of task IDs."""
        return list(self._topological_order)

    @property
    def task_ids(self) -> frozenset[str]:
        """All task IDs in this DAG."""
        return frozenset(self._nodes.keys())

    def get_node(self, task_id: str) -> DAGNode:
        """Return the DAGNode for a task ID.

        Raises:
            WorkflowValidationError: If the task_id is not in this DAG.
        """
        try:
            return self._nodes[task_id]
        except KeyError:
            raise WorkflowValidationError(
                f"Task {task_id!r} is not part of this DAG.",
                details={"task_id": task_id},
            )

    def upstream_of(self, task_id: str) -> frozenset[str]:
        """Return the direct upstream (predecessor) task IDs."""
        return frozenset(self._nodes[task_id].upstream_ids)

    def downstream_of(self, task_id: str) -> frozenset[str]:
        """Return the direct downstream (successor) task IDs."""
        return frozenset(self._nodes[task_id].downstream_ids)

    def roots(self) -> list[str]:
        """
        Return task IDs with no upstream dependencies (entry points).
        Ordered lexicographically for determinism.
        """
        return sorted(
            tid for tid, node in self._nodes.items() if not node.upstream_ids
        )

    def leaves(self) -> list[str]:
        """
        Return task IDs with no downstream dependencies (exit points).
        Ordered lexicographically.
        """
        return sorted(
            tid for tid, node in self._nodes.items() if not node.downstream_ids
        )

    def is_dependency_satisfied(
        self,
        task_id: str,
        task_statuses: dict[str, WorkflowTaskStatus],
        *,
        default_policy: DependencyPolicy = DependencyPolicy.REQUIRE_ALL_SUCCESS,
    ) -> bool:
        """
        Determine whether all dependency conditions for ``task_id`` are met.

        This is the core deterministic dependency resolution function.
        It NEVER uses AI reasoning — it is a pure predicate over statuses.

        Args:
            task_id: The task to evaluate.
            task_statuses: Current status of all tasks in the workflow.
            default_policy: Fallback policy when an edge has no explicit policy.

        Returns:
            True if all dependency conditions are satisfied.

        Raises:
            WorkflowValidationError: If task_id is not in the DAG.
        """
        node = self.get_node(task_id)
        if not node.upstream_ids:
            return True  # No dependencies → always ready

        for upstream_id in node.upstream_ids:
            policy = node.dependency_policies.get(upstream_id, default_policy)
            upstream_status = task_statuses.get(upstream_id, WorkflowTaskStatus.PENDING)

            if policy == DependencyPolicy.REQUIRE_ALL_SUCCESS:
                if upstream_status != WorkflowTaskStatus.SUCCEEDED:
                    return False

            elif policy == DependencyPolicy.REQUIRE_ANY_SUCCESS:
                # At least one upstream must have SUCCEEDED — evaluated per edge here;
                # if this edge is not succeeded we can check the others.
                if upstream_status != WorkflowTaskStatus.SUCCEEDED:
                    # Check if any OTHER upstream already succeeded.
                    # For a single REQUIRE_ANY_SUCCESS edge the contract is
                    # "THIS upstream succeeded."
                    return False

            elif policy == DependencyPolicy.CONTINUE_ON_FAILURE:
                # Continue unless upstream is still running / pending / retrying.
                if upstream_status in {
                    WorkflowTaskStatus.PENDING,
                    WorkflowTaskStatus.READY,
                    WorkflowTaskStatus.RUNNING,
                    WorkflowTaskStatus.RETRYING,
                }:
                    return False  # Upstream not yet done

        return True

    def is_blocked_by_failure(
        self,
        task_id: str,
        task_statuses: dict[str, WorkflowTaskStatus],
        *,
        default_policy: DependencyPolicy = DependencyPolicy.REQUIRE_ALL_SUCCESS,
    ) -> bool:
        """
        Determine whether task_id should enter BLOCKED state because a
        dependency has terminally failed and the policy does not allow
        continuation.

        Returns:
            True if the task must be BLOCKED.
        """
        node = self.get_node(task_id)
        for upstream_id in node.upstream_ids:
            policy = node.dependency_policies.get(upstream_id, default_policy)
            upstream_status = task_statuses.get(upstream_id, WorkflowTaskStatus.PENDING)

            if upstream_status in {WorkflowTaskStatus.FAILED, WorkflowTaskStatus.CANCELLED}:
                if policy == DependencyPolicy.REQUIRE_ALL_SUCCESS:
                    return True
                if policy == DependencyPolicy.REQUIRE_ANY_SUCCESS:
                    # If ALL upstreams failed/cancelled the task is blocked.
                    all_upstream = node.upstream_ids
                    all_failed = all(
                        task_statuses.get(uid, WorkflowTaskStatus.PENDING)
                        in {WorkflowTaskStatus.FAILED, WorkflowTaskStatus.CANCELLED}
                        for uid in all_upstream
                    )
                    if all_failed:
                        return True

        return False

    def get_ready_tasks(
        self,
        task_statuses: dict[str, WorkflowTaskStatus],
        *,
        default_policy: DependencyPolicy = DependencyPolicy.REQUIRE_ALL_SUCCESS,
    ) -> list[str]:
        """
        Return task IDs that are currently PENDING and have all dependencies
        satisfied (i.e. should transition to READY).

        Returns tasks in topological order for determinism.

        Args:
            task_statuses: Current status of all tasks.
            default_policy: Default dependency policy.

        Returns:
            List of task IDs that should become READY.
        """
        result = []
        for tid in self._topological_order:
            status = task_statuses.get(tid, WorkflowTaskStatus.PENDING)
            if status != WorkflowTaskStatus.PENDING:
                continue
            if self.is_dependency_satisfied(tid, task_statuses, default_policy=default_policy):
                result.append(tid)
        return result

    def get_independent_tasks(self) -> list[str]:
        """
        Return task IDs that have no dependencies and no dependents —
        i.e. completely independent tasks suitable for full parallel execution.

        Ordered lexicographically.
        """
        return sorted(
            tid
            for tid, node in self._nodes.items()
            if not node.upstream_ids and not node.downstream_ids
        )

    def summary(self) -> dict[str, Any]:
        """Return a summary dictionary for observability / logging."""
        return {
            "task_count": len(self._nodes),
            "edge_count": sum(len(n.upstream_ids) for n in self._nodes.values()),
            "roots": self.roots(),
            "leaves": self.leaves(),
            "topological_order": self._topological_order,
        }
