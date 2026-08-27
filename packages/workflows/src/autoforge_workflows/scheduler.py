"""
Workflow Scheduler — Phase 9.

The Scheduler's responsibility is ELIGIBILITY — it determines WHICH tasks
may execute now and returns scheduling decisions.  It does NOT execute tasks.
Execution is Phase 10 (autonomous engineering workers).

Separation of concerns
-----------------------
  WorkflowDAG   — knows the graph structure
  TaskQueue     — stores ready tasks
  WorkflowScheduler — decides how many tasks may run concurrently and
                      which tasks to dispatch next

Determinism guarantee
---------------------
All scheduling decisions are deterministic:
- Priority order (CRITICAL > HIGH > MEDIUM > LOW)
- Within equal priority: topological order from the DAG
- Concurrency is bounded by SchedulerConfig.max_concurrent_tasks
- No randomness, no model inference

HITL awareness
--------------
Tasks in WAITING_APPROVAL status are counted as "running" for concurrency
purposes (they hold a slot) so that the workflow doesn't overschedule while
waiting for human approval.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from autoforge_workflows.dag import WorkflowDAG
from autoforge_workflows.errors import SchedulerError
from autoforge_workflows.models import (
    DependencyPolicy,
    ExecutionPolicy,
    FailureAction,
    WorkflowTaskState,
    WorkflowTaskStatus,
)
from autoforge_workflows.queue import QueueEntry, TaskQueue
from autoforge_workflows.state import (
    get_allowed_transitions,
    is_terminal,
    validate_workflow_task_transition,
)


# ── Scheduling Decision ───────────────────────────────────────────────────


@dataclass
class SchedulingDecision:
    """
    The result of a single scheduling tick.

    The scheduler returns this record so the engine knows what to dispatch,
    what to block, and whether the workflow is complete or failed.
    """

    dispatch: list[QueueEntry] = field(default_factory=list)
    """Tasks to dispatch to executors this tick."""

    newly_ready: list[str] = field(default_factory=list)
    """Task IDs that transitioned PENDING → READY this tick."""

    newly_blocked: list[str] = field(default_factory=list)
    """Task IDs that transitioned to BLOCKED this tick (dependency failed)."""

    workflow_complete: bool = False
    """True if all tasks are terminal and the workflow is done."""

    workflow_failed: bool = False
    """True if the workflow must be marked as failed."""

    cancellable_tasks: list[str] = field(default_factory=list)
    """Tasks that should be cancelled due to workflow failure policy."""

    available_slots: int = 0
    """How many execution slots are currently free."""

    concurrency_limited: bool = False
    """True if tasks were not dispatched due to concurrency limits."""


# ── Scheduler Config ──────────────────────────────────────────────────────


@dataclass
class SchedulerConfig:
    """
    Configuration for the WorkflowScheduler.

    Values here are in addition to the per-workflow ExecutionPolicy; they
    apply at the scheduler level (e.g. a global concurrency ceiling that
    overrides individual workflow configuration).
    """

    global_max_concurrent: int | None = None
    """Optional global ceiling on concurrent tasks across all workflows.
    None means no global limit (each workflow uses its own ExecutionPolicy)."""


# ── Workflow Scheduler ────────────────────────────────────────────────────


class WorkflowScheduler:
    """
    Determines which tasks are eligible to execute and how many may run
    concurrently.

    Usage
    -----
    Call ``tick()`` whenever task status changes to get an updated
    SchedulingDecision.

    The scheduler is synchronous and deterministic.  It does not modify
    task state — that is the engine's responsibility.  It reports what
    SHOULD happen; the engine enacts it.
    """

    def __init__(self, config: SchedulerConfig | None = None) -> None:
        self._config = config or SchedulerConfig()

    def tick(
        self,
        dag: WorkflowDAG,
        task_states: dict[str, WorkflowTaskState],
        queue: TaskQueue,
        execution_policy: ExecutionPolicy,
    ) -> SchedulingDecision:
        """
        Compute a scheduling decision for the current workflow state.

        Steps (all deterministic):
        1. Identify tasks that should transition PENDING → READY or → BLOCKED.
        2. Enqueue newly READY tasks.
        3. Compute available concurrency slots.
        4. Dequeue up to available_slots READY tasks for dispatch.
        5. Determine if the workflow is complete or failed.

        Args:
            dag: The workflow's DAG.
            task_states: Current state of all tasks.
            queue: The task queue (mutated: tasks enqueued/dequeued).
            execution_policy: Workflow-level execution policy.

        Returns:
            A SchedulingDecision describing what the engine should do.
        """
        decision = SchedulingDecision()

        # ── 1. Compute current task status map ────────────────────────
        statuses: dict[str, WorkflowTaskStatus] = {
            tid: ts.status for tid, ts in task_states.items()
        }

        # ── 2. Identify PENDING tasks that should become READY or BLOCKED ─
        for task_id in dag.topological_order:
            state = task_states.get(task_id)
            if state is None:
                continue
            if state.status != WorkflowTaskStatus.PENDING:
                continue

            if dag.is_blocked_by_failure(
                task_id,
                statuses,
                default_policy=execution_policy.dependency_policy,
            ):
                decision.newly_blocked.append(task_id)

            elif dag.is_dependency_satisfied(
                task_id,
                statuses,
                default_policy=execution_policy.dependency_policy,
            ):
                if not queue.contains(task_id):
                    decision.newly_ready.append(task_id)
                    queue.enqueue(
                        task_id=task_id,
                        workflow_id=str(state.workflow_id),
                        priority=state.definition.priority,
                    )

        # Update statuses map with newly ready tasks so concurrency calc
        # sees them as READY.
        updated_statuses: dict[str, WorkflowTaskStatus] = dict(statuses)
        for tid in decision.newly_ready:
            updated_statuses[tid] = WorkflowTaskStatus.READY

        # ── 3. Compute available concurrency slots ─────────────────────
        running_count = sum(
            1 for ts in task_states.values()
            if ts.status in {WorkflowTaskStatus.RUNNING, WorkflowTaskStatus.WAITING_APPROVAL}
        )
        max_concurrent = execution_policy.max_concurrent_tasks
        if self._config.global_max_concurrent is not None:
            max_concurrent = min(max_concurrent, self._config.global_max_concurrent)

        available = max(0, max_concurrent - running_count)
        decision.available_slots = available

        if available == 0 and queue.ready_count(updated_statuses) > 0:
            decision.concurrency_limited = True

        # ── 4. Dequeue tasks for dispatch ─────────────────────────────
        dispatched = queue.dequeue_batch(updated_statuses, max_count=available)
        decision.dispatch = dispatched

        # ── 5. Failure policy evaluation ──────────────────────────────
        has_terminal_failure = any(
            ts.status == WorkflowTaskStatus.FAILED
            and ts.attempt_number >= ts.definition.retry_policy.max_attempts
            for ts in task_states.values()
        )

        if has_terminal_failure and execution_policy.failure_action == FailureAction.FAIL_WORKFLOW:
            decision.workflow_failed = True
            # Identify cancellable tasks (PENDING / READY / RETRYING).
            decision.cancellable_tasks = [
                tid for tid, ts in task_states.items()
                if ts.status in {
                    WorkflowTaskStatus.PENDING,
                    WorkflowTaskStatus.READY,
                    WorkflowTaskStatus.RETRYING,
                    WorkflowTaskStatus.BLOCKED,
                }
            ]
        elif has_terminal_failure and execution_policy.failure_action == FailureAction.CANCEL_DEPENDENTS:
            # Only cancel downstream dependents of failed tasks.
            failed_terminal = [
                tid for tid, ts in task_states.items()
                if ts.status == WorkflowTaskStatus.FAILED
                and ts.attempt_number >= ts.definition.retry_policy.max_attempts
            ]
            cancellable: set[str] = set()
            for ftid in failed_terminal:
                cancellable.update(dag.downstream_of(ftid))
            decision.cancellable_tasks = [
                tid for tid in cancellable
                if task_states.get(tid) and not is_terminal(
                    task_states[tid].status  # type: ignore[union-attr]
                )
            ]

        # ── 6. Workflow completion check ───────────────────────────────
        if not decision.workflow_failed:
            all_done = all(
                is_terminal(ts.status) or ts.status == WorkflowTaskStatus.FAILED
                for ts in task_states.values()
            )
            if all_done:
                # Determine success: all tasks must have SUCCEEDED.
                all_succeeded = all(
                    ts.status == WorkflowTaskStatus.SUCCEEDED
                    for ts in task_states.values()
                )
                if all_succeeded:
                    decision.workflow_complete = True
                else:
                    # Mixed: some succeeded, some failed/cancelled.
                    # If failure_action is CONTINUE, this is still "complete".
                    if execution_policy.failure_action == FailureAction.CONTINUE:
                        decision.workflow_complete = True
                    else:
                        decision.workflow_failed = True

        return decision

    def compute_retry_eligible(
        self,
        task_states: dict[str, WorkflowTaskState],
    ) -> list[str]:
        """
        Return task IDs that are in RETRYING status and whose backoff delay
        has elapsed (retry_scheduled_at <= now).

        This method is deterministic — it compares timestamps, not model output.

        Args:
            task_states: Current task states.

        Returns:
            Task IDs ready to be re-dispatched (RETRYING → RUNNING).
        """
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)

        result = []
        for tid, ts in task_states.items():
            if ts.status != WorkflowTaskStatus.RETRYING:
                continue
            if ts.retry_scheduled_at is None:
                # No scheduled time → immediately eligible.
                result.append(tid)
            elif ts.retry_scheduled_at <= now:
                result.append(tid)
        return result

    def summary(
        self,
        task_states: dict[str, WorkflowTaskState],
        execution_policy: ExecutionPolicy,
    ) -> dict[str, Any]:
        """Return a diagnostic summary of scheduler state."""
        status_counts: dict[str, int] = {}
        for ts in task_states.values():
            key = ts.status.value
            status_counts[key] = status_counts.get(key, 0) + 1

        running = status_counts.get("running", 0) + status_counts.get("waiting_approval", 0)
        return {
            "status_counts": status_counts,
            "running": running,
            "max_concurrent": execution_policy.max_concurrent_tasks,
            "available_slots": max(0, execution_policy.max_concurrent_tasks - running),
        }
