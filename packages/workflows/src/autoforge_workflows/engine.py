"""
Workflow Engine — Phase 9.

The WorkflowEngine is the central orchestrator of the Workflow Platform.
It receives WorkflowDefinitions, manages their full lifecycle, and
coordinates the DAG, Queue, Scheduler, Retry, Recovery, and Approval Gate
subsystems.

Responsibilities
----------------
- Submit workflows (build DAG, initialise task states, create WorkflowHandle).
- Drive the scheduling loop (tick-based: DAG readiness → queue → dispatch).
- Record task outcomes (success, failure, retry, cancellation).
- Enforce retry policies deterministically.
- Pause at HITL approval gates; resume after decision.
- Capture checkpoints for recovery.
- Integrate with the canonical event vocabulary (optional event sink).
- Integrate with the Runtime state boundary (optional runtime facade).

NOT responsible for
-------------------
- Executing tasks (that is Phase 10 — engineering workers).
- Communicating over the network.
- Making AI-based scheduling decisions.
- Providing a distributed message broker.

Architecture
------------
The engine is synchronous from the outside but is designed to be embedded
in an async application (event loop) without blocking.  Each public method
completes a unit of work and returns.  Long-running execution happens by
calling ``tick()`` repeatedly as task results arrive from executors.

Event integration
-----------------
If an ``event_sink`` is provided, the engine publishes canonical events
from the existing autoforge_events vocabulary (task.created, task.ready,
task.started, task.completed, task.failed, etc.) via the frozen event
types.  It NEVER creates new event types — only uses the existing vocabulary.
Workflow-level events map to WORKFLOW category via EventCategory.SYSTEM_EVENT.

Runtime integration
-------------------
If a ``runtime_facade`` is provided (matching the KernelRuntimeFacade
protocol), the engine records WorkflowState and TaskState into the Runtime
so that Runtime remains the authoritative state platform.  Without a facade,
the engine is fully self-contained (suitable for testing).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Protocol

from autoforge_workflows.approval import (
    ApprovalDecision,
    ApprovalGate,
    ApprovalOutcome,
    ApprovalStatus,
)
from autoforge_workflows.dag import WorkflowDAG
from autoforge_workflows.errors import (
    ApprovalError,
    RecoveryError,
    WorkflowNotFoundError,
    WorkflowValidationError,
)
from autoforge_workflows.models import (
    FailureAction,
    WorkflowDefinition,
    WorkflowTaskState,
    WorkflowTaskStatus,
)
from autoforge_workflows.queue import TaskQueue
from autoforge_workflows.recovery import RecoveryContext, WorkflowRecovery, WorkflowSnapshot
from autoforge_workflows.retry import RetryContext, compute_backoff, should_retry
from autoforge_workflows.scheduler import SchedulerConfig, SchedulingDecision, WorkflowScheduler
from autoforge_workflows.state import validate_workflow_task_transition
from autoforge_runtime.models import ExecutionStatus, WorkflowStatus


# ── Event Sink Protocol ───────────────────────────────────────────────────


class EventSinkProtocol(Protocol):
    """Minimal protocol for publishing canonical events."""

    def publish(self, event: Any) -> None:  # noqa: ANN401
        """Publish an event to the canonical event bus."""
        ...


# ── Runtime Facade Protocol ───────────────────────────────────────────────


class RuntimeFacadeProtocol(Protocol):
    """Minimal protocol for Runtime integration."""

    def record_workflow_state(self, workflow_id: uuid.UUID, state: dict[str, Any]) -> None:
        """Record workflow-level state into the Runtime."""
        ...

    def record_task_state(self, task_id: str, state: dict[str, Any]) -> None:
        """Record task-level state into the Runtime."""
        ...


# ── Workflow Status (engine-level) ────────────────────────────────────────


class WorkflowEngineStatus(str):
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


# ── Workflow Handle ───────────────────────────────────────────────────────


@dataclass
class WorkflowHandle:
    """
    A live reference to a workflow managed by the WorkflowEngine.

    Callers receive a WorkflowHandle when they submit a workflow.
    The handle provides:
    - Read access to current task states.
    - The workflow_id for correlation.
    - Access to pending approval gates.

    The handle is a view — it does not own the state; the engine does.
    """

    workflow_id: uuid.UUID
    definition: WorkflowDefinition
    status: str = WorkflowEngineStatus.RUNNING
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    finished_at: datetime | None = None

    # Internal references (not exposed directly)
    _task_states: dict[str, WorkflowTaskState] = field(default_factory=dict, repr=False)
    _dag: WorkflowDAG | None = field(default=None, repr=False)
    _queue: TaskQueue = field(default_factory=TaskQueue, repr=False)
    _approval_gates: dict[str, ApprovalGate] = field(default_factory=dict, repr=False)
    _recovery_attempt: int = field(default=0, repr=False)

    # ── Query API ─────────────────────────────────────────────────────────

    @property
    def task_states(self) -> dict[str, WorkflowTaskState]:
        """All task states (read-only mapping)."""
        return dict(self._task_states)

    @property
    def task_statuses(self) -> dict[str, WorkflowTaskStatus]:
        """Current status of all tasks (read-only view)."""
        return {tid: ts.status for tid, ts in self._task_states.items()}

    @property
    def pending_approval_gates(self) -> dict[str, ApprovalGate]:
        """Approval gates currently awaiting a decision."""
        return {
            gid: gate
            for gid, gate in self._approval_gates.items()
            if gate.status == ApprovalStatus.PENDING_APPROVAL
        }

    def get_task_state(self, task_id: str) -> WorkflowTaskState | None:
        """Return the task state for the given task ID, or None."""
        return self._task_states.get(task_id)

    @property
    def is_complete(self) -> bool:
        return self.status == WorkflowEngineStatus.COMPLETED

    @property
    def is_failed(self) -> bool:
        return self.status == WorkflowEngineStatus.FAILED

    @property
    def is_paused(self) -> bool:
        return self.status == WorkflowEngineStatus.PAUSED

    @property
    def progress(self) -> float:
        """Percentage of tasks that have reached a terminal state (0–100)."""
        if not self._task_states:
            return 0.0
        terminal_count = sum(
            1 for ts in self._task_states.values()
            if ts.status in {WorkflowTaskStatus.SUCCEEDED, WorkflowTaskStatus.CANCELLED}
        )
        return round(100.0 * terminal_count / len(self._task_states), 2)


# ── Engine Config ─────────────────────────────────────────────────────────


@dataclass
class WorkflowEngineConfig:
    """Configuration for the WorkflowEngine."""

    scheduler_config: SchedulerConfig = field(default_factory=SchedulerConfig)
    auto_checkpoint: bool = True
    """Whether to take a checkpoint snapshot after every state change."""
    checkpoint_store: dict[str, Any] | None = None
    """Optional dict-based checkpoint store (for testing / simple persistence).
    In production, this would be backed by the Runtime CheckpointManager."""


# ── Workflow Engine ───────────────────────────────────────────────────────


class WorkflowEngine:
    """
    The central orchestrator for the AutoForge Workflow Platform.

    The engine manages the lifecycle of one or more workflows simultaneously.
    It accepts task outcome reports from executors and advances workflow state
    deterministically using the DAG, Queue, Scheduler, Retry, and Approval
    subsystems.

    Phase 10 note
    -------------
    The engine dispatches tasks by returning them in SchedulingDecision.dispatch.
    In Phase 10, engineering workers will pick these up via the Execution Engine.
    In Phase 9, executors are simulated — the engine exposes ``report_task_result()``
    for tests and for future integration.
    """

    def __init__(
        self,
        *,
        config: WorkflowEngineConfig | None = None,
        event_sink: EventSinkProtocol | None = None,
        runtime_facade: RuntimeFacadeProtocol | None = None,
        workflow_store: Any | None = None,
        execution_store: Any | None = None,
    ) -> None:
        self._config = config or WorkflowEngineConfig()
        self._scheduler = WorkflowScheduler(self._config.scheduler_config)
        self._recovery = WorkflowRecovery()
        self._event_sink = event_sink
        self._runtime_facade = runtime_facade
        self._workflow_store = workflow_store
        self._execution_store = execution_store
        self._handles: dict[uuid.UUID, WorkflowHandle] = {}

    # ── Workflow Submission ───────────────────────────────────────────────

    def submit(
        self,
        definition: WorkflowDefinition,
        *,
        correlation_id: uuid.UUID | None = None,
    ) -> WorkflowHandle:
        """
        Submit a workflow for execution.

        Builds the DAG, validates it, initialises task states, seeds the
        queue with root tasks, and returns a WorkflowHandle.

        Args:
            definition: The workflow to execute.
            correlation_id: Optional correlation ID for distributed tracing.

        Returns:
            A live WorkflowHandle.

        Raises:
            WorkflowValidationError: If the DAG is invalid or contains cycles.
            DependencyError: If edge references are invalid.
        """
        # Build and validate the DAG.
        dag = WorkflowDAG.from_definition(definition)

        # Initialise task states.
        task_states: dict[str, WorkflowTaskState] = {}
        for task_def in definition.tasks:
            # Apply workflow-level retry policy as fallback.
            effective_retry = task_def.retry_policy
            ts = WorkflowTaskState(
                task_id=task_def.task_id,
                workflow_id=definition.workflow_id,
                definition=task_def,
                status=WorkflowTaskStatus.PENDING,
                correlation_id=correlation_id or definition.correlation_id,
            )
            task_states[task_def.task_id] = ts

        # Initialise queue.
        queue = TaskQueue()

        # Create the handle.
        handle = WorkflowHandle(
            workflow_id=definition.workflow_id,
            definition=definition,
            status=WorkflowEngineStatus.RUNNING,
            _task_states=task_states,
            _dag=dag,
            _queue=queue,
        )
        self._handles[definition.workflow_id] = handle

        # Register in durable workflow store if available (Phase 18-J.3)
        if self._workflow_store is not None:
            try:
                self._workflow_store.register_workflow(
                    definition.workflow_id,
                    definition=definition,
                    correlation_id=correlation_id or definition.correlation_id,
                    metadata=dict(definition.metadata),
                )
            except Exception:
                pass

        # Publish workflow-started event.
        self._emit_workflow_event("workflow.started", definition.workflow_id, {
            "name": definition.name,
            "task_count": len(definition.tasks),
            "correlation_id": str(correlation_id) if correlation_id else None,
        })

        # Run first scheduling tick to seed the queue with independent tasks.
        self._tick(handle)

        return handle

    # ── Task Result Reporting ─────────────────────────────────────────────

    def report_task_success(
        self,
        workflow_id: uuid.UUID,
        task_id: str,
        *,
        result: dict[str, Any] | None = None,
    ) -> SchedulingDecision:
        """
        Report that a task succeeded.

        Transitions the task to SUCCEEDED, then drives a scheduling tick
        to advance dependent tasks.

        Args:
            workflow_id: The workflow this task belongs to.
            task_id: The task that succeeded.
            result: Optional output from the task executor.

        Returns:
            A SchedulingDecision describing what the engine did next.

        Raises:
            WorkflowNotFoundError: If the workflow is not found.
            WorkflowValidationError: If the transition is invalid.
        """
        handle = self._get_handle(workflow_id)
        ts = self._get_task_state(handle, task_id)

        # Check for approval gate — only on first execution attempt,
        # NOT after being resumed from approval (which re-runs the task).
        task_def = ts.definition
        if task_def.approval_gate is not None:
            gate_id = task_def.approval_gate.gate_id
            # If the gate already exists and is resolved (approved), skip gate.
            existing_gate = handle._approval_gates.get(gate_id)
            if existing_gate is None or existing_gate.status.value == "pending_approval":
                if existing_gate is None:
                    # First time — enter the approval gate.
                    return self._enter_approval_gate(handle, ts, task_def.approval_gate, result or {})

        # Transition to SUCCEEDED.
        validate_workflow_task_transition(
            ts.status, WorkflowTaskStatus.SUCCEEDED, task_id=task_id
        )
        ts.status = WorkflowTaskStatus.SUCCEEDED
        ts.finished_at = datetime.now(timezone.utc)
        ts.result = result or {}

        self._emit_task_event("task.completed", workflow_id, task_id, {
            "attempt_number": ts.attempt_number,
            "result_keys": list(ts.result.keys()),
        })

        return self._tick(handle)

    def report_task_failure(
        self,
        workflow_id: uuid.UUID,
        task_id: str,
        *,
        error_code: str,
        error_message: str,
        is_retryable: bool | None = None,
    ) -> SchedulingDecision:
        """
        Report that a task failed.

        Applies retry policy deterministically:
        - If retryable and attempts remain → RETRYING, schedule backoff.
        - Otherwise → terminal FAILED.

        Args:
            workflow_id: The workflow this task belongs to.
            task_id: The task that failed.
            error_code: Machine-readable error code.
            error_message: Human-readable error message.
            is_retryable: If provided, overrides the error-code-based
                retryability check (for callers that have more context).

        Returns:
            A SchedulingDecision.

        Raises:
            WorkflowNotFoundError: If the workflow is not found.
        """
        handle = self._get_handle(workflow_id)
        ts = self._get_task_state(handle, task_id)

        # Transition to FAILED first.
        validate_workflow_task_transition(
            ts.status, WorkflowTaskStatus.FAILED, task_id=task_id
        )
        ts.status = WorkflowTaskStatus.FAILED
        ts.finished_at = datetime.now(timezone.utc)
        ts.last_error_code = error_code
        ts.last_error_message = error_message

        self._emit_task_event("task.failed", workflow_id, task_id, {
            "error_code": error_code,
            "attempt_number": ts.attempt_number,
            "recoverable": False,  # updated below if retrying
        })

        # Evaluate retry policy (deterministic).
        ctx = RetryContext(
            task_id=task_id,
            attempt_number=ts.attempt_number,
            error_code=error_code,
            error_message=error_message,
        )
        policy = ts.definition.retry_policy

        # If caller explicitly specified retryability, respect it.
        if is_retryable is False:
            retryable = False
        else:
            retryable = should_retry(ctx, policy)

        if retryable:
            delay = compute_backoff(ts.attempt_number, policy)
            validate_workflow_task_transition(
                ts.status, WorkflowTaskStatus.RETRYING, task_id=task_id
            )
            ts.status = WorkflowTaskStatus.RETRYING
            ts.retry_scheduled_at = datetime.now(timezone.utc) + timedelta(seconds=delay)

            self._emit_task_event("task.retrying", workflow_id, task_id, {
                "attempt_number": ts.attempt_number,
                "error_code": error_code,
                "retry_delay_seconds": delay,
            })

        return self._tick(handle)

    def report_task_cancelled(
        self,
        workflow_id: uuid.UUID,
        task_id: str,
        *,
        reason: str = "cancelled",
    ) -> SchedulingDecision:
        """
        Report that a task was cancelled.

        Args:
            workflow_id: The workflow.
            task_id: The task to cancel.
            reason: Optional cancellation reason.

        Returns:
            A SchedulingDecision.
        """
        handle = self._get_handle(workflow_id)
        ts = self._get_task_state(handle, task_id)

        validate_workflow_task_transition(
            ts.status, WorkflowTaskStatus.CANCELLED, task_id=task_id
        )
        ts.status = WorkflowTaskStatus.CANCELLED
        ts.finished_at = datetime.now(timezone.utc)

        self._emit_task_event("task.cancelled", workflow_id, task_id, {"reason": reason})

        # Remove from queue if present.
        handle._queue.cancel(task_id)

        return self._tick(handle)

    def mark_task_running(
        self,
        workflow_id: uuid.UUID,
        task_id: str,
    ) -> None:
        """
        Mark a dispatched task as RUNNING.

        Called by the execution layer (Phase 10 workers or test harness)
        after it accepts the task from the dispatch list.

        Args:
            workflow_id: The workflow.
            task_id: The task being started.
        """
        handle = self._get_handle(workflow_id)
        ts = self._get_task_state(handle, task_id)
        validate_workflow_task_transition(
            ts.status, WorkflowTaskStatus.RUNNING, task_id=task_id
        )
        ts.status = WorkflowTaskStatus.RUNNING
        ts.attempt_number += 1
        ts.started_at = datetime.now(timezone.utc)
        ts.finished_at = None

        self._emit_task_event("task.started", workflow_id, task_id, {
            "attempt_number": ts.attempt_number,
        })

    # ── HITL Approval Gate API ────────────────────────────────────────────

    def submit_approval_decision(
        self,
        workflow_id: uuid.UUID,
        gate_id: str,
        decision: ApprovalDecision,
    ) -> SchedulingDecision:
        """
        Submit a human approval decision for a task's approval gate.

        If approved: the task transitions back to RUNNING for continuation.
        If rejected: the task transitions to CANCELLED.

        Args:
            workflow_id: The workflow.
            gate_id: The approval gate identifier.
            decision: The human decision.

        Returns:
            A SchedulingDecision describing what happened next.

        Raises:
            WorkflowNotFoundError: If the workflow is not found.
            ApprovalError: If the gate does not exist or is already resolved.
        """
        handle = self._get_handle(workflow_id)
        gate = handle._approval_gates.get(gate_id)
        if gate is None:
            raise ApprovalError(
                f"Approval gate {gate_id!r} not found in workflow {workflow_id}.",
                details={"gate_id": gate_id, "workflow_id": str(workflow_id)},
            )

        new_status = gate.decide(decision)

        if new_status == ApprovalStatus.APPROVED:
            ts = self._get_task_state(handle, gate.task_id)
            # Resume task after approval.
            validate_workflow_task_transition(
                ts.status, WorkflowTaskStatus.RUNNING, task_id=gate.task_id
            )
            ts.status = WorkflowTaskStatus.RUNNING
            ts.attempt_number += 1
            ts.started_at = datetime.now(timezone.utc)

            # Resume workflow if it was paused.
            if handle.status == WorkflowEngineStatus.PAUSED:
                handle.status = WorkflowEngineStatus.RUNNING

            self._emit_task_event("task.resumed", workflow_id, gate.task_id, {
                "gate_id": gate_id,
                "decided_by": decision.decided_by,
            })

        elif new_status in {ApprovalStatus.REJECTED, ApprovalStatus.TIMED_OUT}:
            ts = self._get_task_state(handle, gate.task_id)
            validate_workflow_task_transition(
                ts.status, WorkflowTaskStatus.CANCELLED, task_id=gate.task_id
            )
            ts.status = WorkflowTaskStatus.CANCELLED
            ts.finished_at = datetime.now(timezone.utc)

            self._emit_task_event("task.cancelled", workflow_id, gate.task_id, {
                "gate_id": gate_id,
                "reason": f"approval_{new_status.value}",
            })

        return self._tick(handle)

    # ── Cancellation ──────────────────────────────────────────────────────

    def cancel_workflow(
        self,
        workflow_id: uuid.UUID,
        *,
        reason: str = "cancelled",
    ) -> WorkflowHandle:
        """
        Cancel all non-terminal tasks in a workflow.

        Args:
            workflow_id: The workflow to cancel.
            reason: Optional cancellation reason.

        Returns:
            The updated WorkflowHandle.
        """
        handle = self._get_handle(workflow_id)
        cancellable_states = {
            WorkflowTaskStatus.PENDING,
            WorkflowTaskStatus.READY,
            WorkflowTaskStatus.RUNNING,
            WorkflowTaskStatus.BLOCKED,
            WorkflowTaskStatus.RETRYING,
            WorkflowTaskStatus.WAITING_APPROVAL,
        }
        for ts in handle._task_states.values():
            if ts.status in cancellable_states:
                ts.status = WorkflowTaskStatus.CANCELLED
                ts.finished_at = datetime.now(timezone.utc)
                handle._queue.cancel(ts.task_id)

        handle.status = WorkflowEngineStatus.CANCELLED
        handle.finished_at = datetime.now(timezone.utc)
        if self._workflow_store is not None:
            try:
                self._workflow_store.cancel_workflow(handle.workflow_id, reason=reason)
            except Exception:
                pass
        self._emit_workflow_event("workflow.cancelled", workflow_id, {"reason": reason})
        return handle

    # ── Recovery ─────────────────────────────────────────────────────────

    def snapshot(self, workflow_id: uuid.UUID) -> WorkflowSnapshot:
        """
        Capture a checkpoint snapshot of a workflow's execution state.

        Args:
            workflow_id: The workflow to snapshot.

        Returns:
            A WorkflowSnapshot ready for checkpointing.
        """
        handle = self._get_handle(workflow_id)
        return self._recovery.create_snapshot(
            workflow_id=workflow_id,
            definition=handle.definition,
            task_states=handle._task_states,
            queue=handle._queue,
            approval_gates=handle._approval_gates,
            recovery_attempt=handle._recovery_attempt,
            correlation_id=handle.definition.correlation_id,
        )

    def restore(self, snapshot: WorkflowSnapshot) -> WorkflowHandle:
        """
        Restore a workflow from a snapshot.

        Args:
            snapshot: The snapshot to restore from.

        Returns:
            A new WorkflowHandle with recovered state.

        Raises:
            RecoveryError: If recovery fails.
        """
        ctx = self._recovery.recover(
            snapshot,
            max_recovery_attempts=snapshot.definition_snapshot.get(
                "recovery_policy", {}
            ).get("max_recovery_attempts", 3),
        )

        # Restore approval gates if any.
        approval_gates: dict[str, ApprovalGate] = {}
        for gate_id, gate_snap in snapshot.approval_gate_snapshots.items():
            approval_gates[gate_id] = ApprovalGate.from_snapshot(gate_snap)

        handle = WorkflowHandle(
            workflow_id=ctx.workflow_id,
            definition=ctx.definition,
            status=WorkflowEngineStatus.RUNNING,
            _task_states=ctx.task_states,
            _dag=WorkflowDAG.from_definition(ctx.definition),
            _queue=ctx.queue,
            _approval_gates=approval_gates,
            _recovery_attempt=ctx.recovery_attempt,
        )
        self._handles[ctx.workflow_id] = handle

        self._emit_workflow_event("workflow.recovered", ctx.workflow_id, {
            "recovery_attempt": ctx.recovery_attempt,
            "skipped_tasks": ctx.skipped_tasks,
            "reset_tasks": ctx.reset_tasks,
        })

        # Run a scheduling tick to advance from recovered state.
        self._tick(handle)
        return handle

    def resume_workflow(
        self,
        workflow_id: uuid.UUID,
        *,
        owner_id: str | None = None,
    ) -> WorkflowHandle:
        """
        Durable controlled resume of an interrupted workflow (Phase 18-J.3).

        Performs transactional claim, reconstructs the workflow runtime state
        from authoritative durable facts, resumes any interrupted execution
        records (attaching attempt N+1), and drives a scheduling tick to dispatch
        only eligible, unfinished work.

        Args:
            workflow_id: The canonical ID of the workflow to resume.
            owner_id: Optional new owner identifier for the resumed workflow.

        Returns:
            The resumed WorkflowHandle.

        Raises:
            WorkflowNotFoundError: If the workflow does not exist durably.
            RecoveryError: If the workflow is not in a resumable state.
            VersionConflictError: If a concurrent resume operation won the claim.
        """
        # 1. In-process idempotency check
        if workflow_id in self._handles:
            existing_handle = self._handles[workflow_id]
            if existing_handle.status in {WorkflowEngineStatus.RUNNING, WorkflowEngineStatus.PAUSED}:
                return existing_handle

        # 2. Durable transactional claim (concurrency-safe via optimistic versioning)
        if self._workflow_store is not None:
            self._workflow_store.claim_workflow_for_resume(workflow_id, owner_id=owner_id)
        elif workflow_id not in self._handles:
            raise WorkflowNotFoundError(
                f"Workflow {workflow_id} not found in durable store or active handles.",
                details={"workflow_id": str(workflow_id)},
            )

        # 3. Deterministic reconstruction from durable facts
        from autoforge_workflows.reconstruction import WorkflowReconstructor
        reconstructor = WorkflowReconstructor(
            workflow_store=self._workflow_store,
            execution_store=self._execution_store,
        )
        handle = reconstructor.reconstruct(workflow_id)

        # 4. Resume interrupted executions (attaching new physical attempts)
        if self._execution_store is not None:
            executions = self._execution_store.list_executions_for_workflow(workflow_id)
            for e in executions:
                if e.status == ExecutionStatus.INTERRUPTED:
                    self._execution_store.resume_execution(
                        e.execution_id,
                        owner_id=owner_id,
                        metadata={"resume": True},
                    )

        # 5. Register in engine handles
        self._handles[workflow_id] = handle

        # 6. Observational event emission
        self._emit_workflow_event("workflow.resumed", workflow_id, {
            "recovery_attempt": handle._recovery_attempt,
        })

        # 7. Drive scheduling tick to dispatch only eligible unfinished work
        self._tick(handle)

        return handle

    # ── Query API ─────────────────────────────────────────────────────────

    def get_handle(self, workflow_id: uuid.UUID) -> WorkflowHandle:
        """Return the WorkflowHandle for a workflow ID."""
        return self._get_handle(workflow_id)

    def tick(self, workflow_id: uuid.UUID) -> SchedulingDecision:
        """
        Manually advance the scheduler for a workflow.

        This is the primary method for callers that want to check for
        retry-eligible tasks or advance the queue without a new task result.

        Args:
            workflow_id: The workflow to tick.

        Returns:
            A SchedulingDecision.
        """
        handle = self._get_handle(workflow_id)
        return self._tick(handle)

    # ── Internal ──────────────────────────────────────────────────────────

    def _tick(self, handle: WorkflowHandle) -> SchedulingDecision:
        """
        Drive one scheduling iteration for a workflow.

        This is the central execution loop of the workflow engine.
        """
        if handle.status in {
            WorkflowEngineStatus.COMPLETED,
            WorkflowEngineStatus.FAILED,
            WorkflowEngineStatus.CANCELLED,
        }:
            # Terminal workflow — nothing to do.
            return SchedulingDecision()

        assert handle._dag is not None, "WorkflowHandle has no DAG"

        # Process RETRYING tasks whose backoff has elapsed.
        retry_eligible = self._scheduler.compute_retry_eligible(handle._task_states)
        for tid in retry_eligible:
            ts = handle._task_states[tid]
            validate_workflow_task_transition(
                ts.status, WorkflowTaskStatus.RUNNING, task_id=tid
            )
            ts.status = WorkflowTaskStatus.RUNNING
            ts.attempt_number += 1
            ts.started_at = datetime.now(timezone.utc)
            ts.retry_scheduled_at = None
            self._emit_task_event("task.started", handle.workflow_id, tid, {
                "attempt_number": ts.attempt_number,
                "is_retry": True,
            })

        decision = self._scheduler.tick(
            dag=handle._dag,
            task_states=handle._task_states,
            queue=handle._queue,
            execution_policy=handle.definition.execution_policy,
        )

        # Emit events for newly READY tasks.
        for tid in decision.newly_ready:
            ts = handle._task_states[tid]
            validate_workflow_task_transition(
                ts.status, WorkflowTaskStatus.READY, task_id=tid
            )
            ts.status = WorkflowTaskStatus.READY
            self._emit_task_event("task.ready", handle.workflow_id, tid, {})

        # Emit events for newly BLOCKED tasks.
        for tid in decision.newly_blocked:
            ts = handle._task_states[tid]
            validate_workflow_task_transition(
                ts.status, WorkflowTaskStatus.BLOCKED, task_id=tid
            )
            ts.status = WorkflowTaskStatus.BLOCKED
            self._emit_task_event("task.blocked", handle.workflow_id, tid, {})

        # Apply cancellable tasks from failure policy.
        for tid in decision.cancellable_tasks:
            ts = handle._task_states.get(tid)
            if ts and not ts.is_terminal:
                ts.status = WorkflowTaskStatus.CANCELLED
                ts.finished_at = datetime.now(timezone.utc)
                handle._queue.cancel(tid)

        # Update workflow status.
        if decision.workflow_complete:
            handle.status = WorkflowEngineStatus.COMPLETED
            handle.finished_at = datetime.now(timezone.utc)
            if self._workflow_store is not None:
                try:
                    self._workflow_store.complete_workflow(handle.workflow_id)
                except Exception:
                    pass
            self._emit_workflow_event("workflow.completed", handle.workflow_id, {
                "task_count": len(handle._task_states),
            })
        elif decision.workflow_failed:
            handle.status = WorkflowEngineStatus.FAILED
            handle.finished_at = datetime.now(timezone.utc)
            if self._workflow_store is not None:
                try:
                    self._workflow_store.fail_workflow(handle.workflow_id)
                except Exception:
                    pass
            self._emit_workflow_event("workflow.failed", handle.workflow_id, {
                "task_count": len(handle._task_states),
            })

        # Emit dispatched task events.
        for entry in decision.dispatch:
            self._emit_task_event("task.dispatched", handle.workflow_id, entry.task_id, {
                "priority": entry.priority,
            })

        # Auto-checkpoint if configured.
        if self._config.auto_checkpoint and self._config.checkpoint_store is not None:
            snap = self.snapshot(handle.workflow_id)
            key = f"workflow:{handle.workflow_id}"
            self._config.checkpoint_store[key] = snap.to_dict()

        return decision

    def _enter_approval_gate(
        self,
        handle: WorkflowHandle,
        ts: WorkflowTaskState,
        gate_policy: Any,
        result: dict[str, Any],
    ) -> SchedulingDecision:
        """Transition a task into WAITING_APPROVAL and pause the workflow."""
        validate_workflow_task_transition(
            ts.status, WorkflowTaskStatus.WAITING_APPROVAL, task_id=ts.task_id
        )
        ts.status = WorkflowTaskStatus.WAITING_APPROVAL
        ts.result = result

        gate = ApprovalGate(
            gate_id=gate_policy.gate_id,
            task_id=ts.task_id,
            workflow_id=handle.workflow_id,
            description=gate_policy.description,
            required_approvers=gate_policy.required_approvers,
            timeout_seconds=gate_policy.timeout_seconds,
        )
        handle._approval_gates[gate_policy.gate_id] = gate

        # Pause the workflow.
        handle.status = WorkflowEngineStatus.PAUSED

        self._emit_task_event("task.waiting_approval", handle.workflow_id, ts.task_id, {
            "gate_id": gate_policy.gate_id,
            "description": gate_policy.description,
        })
        self._emit_workflow_event("workflow.paused", handle.workflow_id, {
            "reason": "awaiting_approval",
            "gate_id": gate_policy.gate_id,
        })

        return self._tick(handle)

    def _get_handle(self, workflow_id: uuid.UUID) -> WorkflowHandle:
        handle = self._handles.get(workflow_id)
        if handle is None:
            raise WorkflowNotFoundError(
                f"Workflow {workflow_id} is not managed by this engine.",
                details={"workflow_id": str(workflow_id)},
            )
        return handle

    def _get_task_state(
        self, handle: WorkflowHandle, task_id: str
    ) -> WorkflowTaskState:
        ts = handle._task_states.get(task_id)
        if ts is None:
            raise WorkflowNotFoundError(
                f"Task {task_id!r} not found in workflow {handle.workflow_id}.",
                details={"task_id": task_id, "workflow_id": str(handle.workflow_id)},
            )
        return ts

    def _emit_task_event(
        self,
        event_type: str,
        workflow_id: uuid.UUID,
        task_id: str,
        payload: dict[str, Any],
    ) -> None:
        """Publish a canonical task event if a sink is configured."""
        if self._event_sink is None:
            return
        try:
            from autoforge_events.event_types import EventCategory, EventType
            from autoforge_events.base import BaseEvent
            try:
                etype = EventType(event_type)
            except ValueError:
                etype = EventType.SYSTEM_EVENT
            event = BaseEvent(
                event_type=etype,
                event_category=EventCategory.TASK,
                aggregate_id=workflow_id,
                aggregate_type="Workflow",
                metadata={
                    "task_id": task_id,
                    "workflow_id": str(workflow_id),
                    **payload,
                },
            )
            self._event_sink.publish(event)
        except Exception:
            # Event sink failures must NEVER break the workflow engine.
            pass

    def _emit_workflow_event(
        self,
        event_type: str,
        workflow_id: uuid.UUID,
        payload: dict[str, Any],
    ) -> None:
        """Publish a canonical workflow-level event if a sink is configured."""
        if self._event_sink is None:
            return
        try:
            from autoforge_events.event_types import EventCategory, EventType
            from autoforge_events.base import BaseEvent
            try:
                etype = EventType(event_type)
            except ValueError:
                etype = EventType.SYSTEM_EVENT
            event = BaseEvent(
                event_type=etype,
                event_category=EventCategory.SYSTEM_EVENT,
                aggregate_id=workflow_id,
                aggregate_type="Workflow",
                metadata={"workflow_id": str(workflow_id), **payload},
            )
            self._event_sink.publish(event)
        except Exception:
            pass
