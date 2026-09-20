"""Workflow Reconstruction — Phase 18-J.3.

Reconstructs an interrupted or stored workflow's runtime state (WorkflowHandle,
TaskQueue, DAG, and task states) from canonical durable facts.

Authoritative durable state consumed:
- WorkflowState (workflow identity, lifecycle status, definition, recovery facts)
- ExecutionState / ExecutionAttemptState (logical execution identity, attempts,
  terminal outcomes, checkpoints)

Derived runtime state produced:
- WorkflowHandle
- WorkflowDAG
- TaskQueue (containing only ready, eligible, non-completed tasks)
- WorkflowTaskState instances

Guarantees:
- Completed tasks are never replayed or re-queued.
- Tasks that were RUNNING when the process died (INTERRUPTED) are marked READY
  for controlled resume; physical re-execution begins as a new attempt under
  the same logical execution identity.
- Dependencies are deterministically evaluated against completed upstream work.
- Queue reconstruction is deterministic (topological + priority order).
- Preserves retry counters, attempt numbers, and error details.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from autoforge_runtime.models import (
    AttemptStatus,
    DurableApprovalStatus,
    ExecutionStatus,
    WorkflowStatus,
)
from autoforge_workflows.approval import (
    ApprovalDecision,
    ApprovalGate,
    ApprovalOutcome,
    ApprovalStatus,
)
from autoforge_workflows.dag import WorkflowDAG
from autoforge_workflows.errors import RecoveryError, WorkflowNotFoundError
from autoforge_workflows.models import (
    TaskDefinition,
    WorkflowDefinition,
    WorkflowTaskState,
    WorkflowTaskStatus,
)
from autoforge_workflows.queue import TaskQueue

if TYPE_CHECKING:
    from autoforge_workflows.engine import WorkflowHandle

logger = logging.getLogger(__name__)


@dataclass
class WorkflowReconstructionContext:
    """Detailed summary of a workflow reconstruction pass."""

    workflow_id: uuid.UUID
    succeeded_tasks: list[str] = field(default_factory=list)
    interrupted_tasks: list[str] = field(default_factory=list)
    ready_tasks: list[str] = field(default_factory=list)
    pending_tasks: list[str] = field(default_factory=list)
    blocked_tasks: list[str] = field(default_factory=list)
    failed_tasks: list[str] = field(default_factory=list)
    cancelled_tasks: list[str] = field(default_factory=list)
    retrying_tasks: list[str] = field(default_factory=list)
    waiting_approval_tasks: list[str] = field(default_factory=list)


class WorkflowReconstructor:
    """Reconstructs runtime workflow objects from authoritative durable state."""

    def __init__(
        self,
        workflow_store: Any,
        execution_store: Any | None = None,
        approval_store: Any | None = None,
    ) -> None:
        self._workflow_store = workflow_store
        self._execution_store = execution_store
        self._approval_store = approval_store
        self.last_context: WorkflowReconstructionContext | None = None

    def reconstruct(
        self,
        workflow_id: uuid.UUID,
        *,
        max_recovery_attempts: int = 3,
    ) -> WorkflowHandle:
        """Reconstruct a WorkflowHandle from durable state.

        Args:
            workflow_id: Canonical UUID of the workflow to reconstruct.
            max_recovery_attempts: Guardrail ceiling on recovery attempts.

        Returns:
            A ready-to-resume WorkflowHandle.

        Raises:
            WorkflowNotFoundError: If no durable record exists for this ID.
            RecoveryError: If durable data is corrupt or recovery attempt limit exceeded.
        """
        from autoforge_workflows.engine import WorkflowEngineStatus, WorkflowHandle

        # 1. Authoritative durable workflow state
        wf_state = self._workflow_store.get_workflow(workflow_id)
        if wf_state is None:
            raise WorkflowNotFoundError(
                f"Durable workflow {workflow_id} not found",
                details={"workflow_id": str(workflow_id)},
            )

        # 2. Reconstruct WorkflowDefinition
        definition = self._extract_definition(wf_state)

        # 3. Deterministically reconstruct DAG from definition
        dag = WorkflowDAG.from_definition(definition)

        # 4. Query durable executions for this workflow
        exec_map = {}
        if self._execution_store is not None:
            if hasattr(self._execution_store, "list_executions_for_workflow"):
                executions = self._execution_store.list_executions_for_workflow(workflow_id)
            elif hasattr(self._execution_store, "find_by_workflow"):
                executions = self._execution_store.find_by_workflow(workflow_id)
            else:
                executions = []
            for e in executions:
                if e.task_id:
                    exec_map[e.task_id] = e

        # 4b. Query durable approvals for this workflow (Phase 18-J.5)
        app_map = {}
        if self._approval_store is not None:
            if hasattr(self._approval_store, "find_by_workflow"):
                approvals = self._approval_store.find_by_workflow(workflow_id)
            else:
                approvals = []
            for a in approvals:
                if a.task_id:
                    app_map[a.task_id] = a

        # 5. Reconstruct Task States
        task_states: dict[str, WorkflowTaskState] = {}
        context = WorkflowReconstructionContext(workflow_id=workflow_id)

        for task_def in definition.tasks:
            tid = task_def.task_id
            e = exec_map.get(tid)
            app = app_map.get(tid)

            ts = WorkflowTaskState(
                task_id=tid,
                workflow_id=workflow_id,
                definition=task_def,
                correlation_id=definition.correlation_id,
            )

            if e is not None:
                ts.attempt_number = e.attempt_count
                ts.started_at = e.started_at
                ts.finished_at = e.completed_at
                result = {}
                last_error_code = e.failure.error_code if e.failure else None
                last_error_message = e.failure.error_message if e.failure else None
                if self._execution_store is not None:
                    try:
                        attempts = self._execution_store.get_attempts(e.execution_id)
                        if attempts:
                            result = dict(attempts[-1].result or {})
                            for att in reversed(attempts):
                                if att.failure and att.failure.error_code:
                                    last_error_code = att.failure.error_code
                                    last_error_message = att.failure.error_message
                                    break
                    except Exception:
                        pass
                ts.result = result
                ts.last_error_code = last_error_code
                ts.last_error_message = last_error_message

                # Phase 18-J.5: Check durable approval status first
                if app is not None and app.status == DurableApprovalStatus.PENDING:
                    ts.status = WorkflowTaskStatus.WAITING_APPROVAL
                    ts.approval_gate_id = app.approval_key
                    context.waiting_approval_tasks.append(tid)

                elif app is not None and app.status in {
                    DurableApprovalStatus.REJECTED,
                    DurableApprovalStatus.CANCELLED,
                    DurableApprovalStatus.EXPIRED,
                }:
                    ts.status = WorkflowTaskStatus.CANCELLED
                    context.cancelled_tasks.append(tid)

                elif e.status == ExecutionStatus.COMPLETED:
                    ts.status = WorkflowTaskStatus.SUCCEEDED
                    context.succeeded_tasks.append(tid)

                elif e.status in {ExecutionStatus.INTERRUPTED, ExecutionStatus.RUNNING}:
                    # Mid-execution when process died -> candidate for controlled resume.
                    # Status is marked READY so scheduler will dispatch it for resume.
                    ts.status = WorkflowTaskStatus.READY
                    context.interrupted_tasks.append(tid)
                    context.ready_tasks.append(tid)

                elif e.status == ExecutionStatus.FAILED:
                    if e.attempt_count < task_def.retry_policy.max_attempts:
                        ts.status = WorkflowTaskStatus.RETRYING
                        context.retrying_tasks.append(tid)
                    else:
                        ts.status = WorkflowTaskStatus.FAILED
                        context.failed_tasks.append(tid)

                elif e.status == ExecutionStatus.CANCELLED:
                    ts.status = WorkflowTaskStatus.CANCELLED
                    context.cancelled_tasks.append(tid)

                elif e.status == ExecutionStatus.BLOCKED:
                    ts.status = WorkflowTaskStatus.BLOCKED
                    context.blocked_tasks.append(tid)

                else:
                    ts.status = WorkflowTaskStatus.READY
                    context.ready_tasks.append(tid)
            else:
                # Execution record not found — check if an approval request was created
                if app is not None and app.status == DurableApprovalStatus.PENDING:
                    ts.status = WorkflowTaskStatus.WAITING_APPROVAL
                    ts.approval_gate_id = app.approval_key
                    context.waiting_approval_tasks.append(tid)
                elif app is not None and app.status in {
                    DurableApprovalStatus.REJECTED,
                    DurableApprovalStatus.CANCELLED,
                    DurableApprovalStatus.EXPIRED,
                }:
                    ts.status = WorkflowTaskStatus.CANCELLED
                    context.cancelled_tasks.append(tid)
                else:
                    # Not yet executed
                    ts.status = WorkflowTaskStatus.PENDING
                    context.pending_tasks.append(tid)

            task_states[tid] = ts

        # 6. Evaluate dependencies for un-started (PENDING) tasks
        status_map = {t: s.status for t, s in task_states.items()}
        for tid in dag.topological_order:
            ts = task_states[tid]
            if ts.status == WorkflowTaskStatus.PENDING:
                if dag.is_blocked_by_failure(
                    tid,
                    status_map,
                    default_policy=definition.execution_policy.dependency_policy,
                ):
                    ts.status = WorkflowTaskStatus.BLOCKED
                    status_map[tid] = WorkflowTaskStatus.BLOCKED
                    context.blocked_tasks.append(tid)
                    if tid in context.pending_tasks:
                        context.pending_tasks.remove(tid)
                elif dag.is_dependency_satisfied(
                    tid,
                    status_map,
                    default_policy=definition.execution_policy.dependency_policy,
                ):
                    ts.status = WorkflowTaskStatus.READY
                    status_map[tid] = WorkflowTaskStatus.READY
                    context.ready_tasks.append(tid)
                    if tid in context.pending_tasks:
                        context.pending_tasks.remove(tid)

        # 7. Deterministically reconstruct TaskQueue
        # Only READY tasks enter the queue in topological + priority order.
        # SUCCEEDED and WAITING_APPROVAL tasks are NEVER enqueued.
        queue = TaskQueue()
        for tid in dag.topological_order:
            ts = task_states[tid]
            if ts.status == WorkflowTaskStatus.READY:
                queue.enqueue(
                    task_id=tid,
                    workflow_id=str(workflow_id),
                    priority=ts.definition.priority,
                )

        # 8. Reconstruct Approval Gates (Phase 18-J.5)
        approval_gates: dict[str, ApprovalGate] = {}
        for task_def in definition.tasks:
            if task_def.approval_gate is not None:
                gate_id = task_def.approval_gate.gate_id
                gate = ApprovalGate(
                    gate_id=gate_id,
                    task_id=task_def.task_id,
                    workflow_id=workflow_id,
                    description=task_def.approval_gate.description,
                    required_approvers=task_def.approval_gate.required_approvers,
                    timeout_seconds=task_def.approval_gate.timeout_seconds,
                )
                app = app_map.get(task_def.task_id)
                if app is not None:
                    if app.status == DurableApprovalStatus.APPROVED:
                        gate.status = ApprovalStatus.APPROVED
                    elif app.status == DurableApprovalStatus.REJECTED:
                        gate.status = ApprovalStatus.REJECTED
                    elif app.status == DurableApprovalStatus.EXPIRED:
                        gate.status = ApprovalStatus.TIMED_OUT
                    elif app.status == DurableApprovalStatus.PENDING:
                        gate.status = ApprovalStatus.PENDING_APPROVAL
                    for d_raw in getattr(app, "decision_history", []):
                        try:
                            outcome = (
                                ApprovalOutcome.APPROVED
                                if d_raw.get("outcome") == "approved"
                                else ApprovalOutcome.REJECTED
                            )
                            decided_at = (
                                datetime.fromisoformat(d_raw["decided_at"])
                                if d_raw.get("decided_at")
                                else datetime.now(timezone.utc)
                            )
                            gate.decisions.append(
                                ApprovalDecision(
                                    outcome=outcome,
                                    decided_by=d_raw.get("decided_by", "system"),
                                    reason=d_raw.get("reason", ""),
                                    metadata=d_raw.get("metadata", {}),
                                    decided_at=decided_at,
                                )
                            )
                        except Exception:
                            pass
                approval_gates[gate_id] = gate

        # 9. Determine overall runtime status
        if wf_state.status == WorkflowStatus.FINISHED:
            engine_status = WorkflowEngineStatus.COMPLETED
        elif wf_state.status == WorkflowStatus.FAILED:
            engine_status = WorkflowEngineStatus.FAILED
        elif wf_state.status == WorkflowStatus.CANCELLED:
            engine_status = WorkflowEngineStatus.CANCELLED
        elif wf_state.status == WorkflowStatus.PAUSED:
            engine_status = WorkflowEngineStatus.PAUSED
        elif any(ts.status == WorkflowTaskStatus.WAITING_APPROVAL for ts in task_states.values()):
            engine_status = WorkflowEngineStatus.PAUSED
        else:
            engine_status = WorkflowEngineStatus.RUNNING

        handle = WorkflowHandle(
            workflow_id=workflow_id,
            definition=definition,
            status=engine_status,
            started_at=wf_state.created_at,
            _task_states=task_states,
            _dag=dag,
            _queue=queue,
            _approval_gates=approval_gates,
            _recovery_attempt=getattr(wf_state, "recovery_attempt", 0) + 1,
        )

        self.last_context = context
        return handle

    def _extract_definition(self, wf_state: Any) -> WorkflowDefinition:
        """Extract or deserialize WorkflowDefinition from WorkflowState."""
        defn_raw = wf_state.definition
        if isinstance(defn_raw, WorkflowDefinition):
            return defn_raw
        if isinstance(defn_raw, dict):
            try:
                return WorkflowDefinition.model_validate(defn_raw)
            except Exception as exc:
                raise RecoveryError(
                    f"Failed to validate durable WorkflowDefinition for {wf_state.workflow_id}: {exc}",
                    details={"workflow_id": str(wf_state.workflow_id)},
                ) from exc
        raise RecoveryError(
            f"No valid WorkflowDefinition found on durable WorkflowState for {wf_state.workflow_id}",
            details={"workflow_id": str(wf_state.workflow_id)},
        )
