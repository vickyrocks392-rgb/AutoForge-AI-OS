"""
Workflow Recovery — Phase 9.

Implements workflow state snapshot / restore for recovery from interruption.

Design
------
A WorkflowSnapshot captures the full execution-time state of a workflow
(task states, queue, approval gates, attempt counts) into a plain dictionary
that can be stored in the Runtime checkpoint infrastructure.

On recovery:
1. Load the snapshot from the Runtime CheckpointManager.
2. Reconstruct WorkflowTaskState instances from the snapshot.
3. Skip tasks already in terminal (SUCCEEDED / CANCELLED) states.
4. Re-enqueue tasks that were READY or RETRYING at interruption time.
5. Resume the WorkflowEngine with the reconstructed state.

This module does NOT:
- Create its own persistence layer.
- Bypass the Runtime checkpoint mechanism.
- Store secrets or credentials.

Recovery algorithm (deterministic)
-----------------------------------
1. Enumerate all task states from the snapshot.
2. For each task:
   - Terminal (SUCCEEDED / CANCELLED): keep as-is.
   - RUNNING / WAITING_APPROVAL at interruption: reset to READY
     (they will be re-dispatched by the scheduler).
   - RETRYING: keep RETRYING; scheduler will pick them up when backoff elapses.
   - PENDING / BLOCKED: keep as-is; scheduler re-evaluates.
   - FAILED with retries remaining: reset to RETRYING so the engine
     applies the retry policy correctly on resume.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from autoforge_workflows.errors import RecoveryError
from autoforge_workflows.models import (
    TaskDefinition,
    WorkflowDefinition,
    WorkflowTaskState,
    WorkflowTaskStatus,
)
from autoforge_workflows.queue import TaskQueue


# ── Workflow Snapshot ─────────────────────────────────────────────────────


@dataclass
class WorkflowSnapshot:
    """
    A point-in-time snapshot of a workflow's execution state.

    Snapshots are serialisable plain dicts; the actual persistence backend
    is the Runtime's CheckpointManager (or any equivalent dict store).
    """

    workflow_id: uuid.UUID
    definition_snapshot: dict[str, Any]
    """Serialised WorkflowDefinition (model_dump)."""

    task_snapshots: dict[str, dict[str, Any]]
    """task_id → WorkflowTaskState.to_snapshot()."""

    queue_snapshot: list[dict[str, Any]]
    """TaskQueue.snapshot()."""

    approval_gate_snapshots: dict[str, dict[str, Any]]
    """gate_id → ApprovalGate.to_snapshot()."""

    recovery_attempt: int = 0
    correlation_id: uuid.UUID | None = None
    captured_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialise to a plain dictionary for the checkpoint store."""
        return {
            "workflow_id": str(self.workflow_id),
            "definition_snapshot": self.definition_snapshot,
            "task_snapshots": self.task_snapshots,
            "queue_snapshot": self.queue_snapshot,
            "approval_gate_snapshots": self.approval_gate_snapshots,
            "recovery_attempt": self.recovery_attempt,
            "correlation_id": str(self.correlation_id) if self.correlation_id else None,
            "captured_at": self.captured_at.isoformat(),
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> WorkflowSnapshot:
        """Deserialise from the checkpoint store."""
        return cls(
            workflow_id=uuid.UUID(data["workflow_id"]),
            definition_snapshot=data["definition_snapshot"],
            task_snapshots=data.get("task_snapshots", {}),
            queue_snapshot=data.get("queue_snapshot", []),
            approval_gate_snapshots=data.get("approval_gate_snapshots", {}),
            recovery_attempt=data.get("recovery_attempt", 0),
            correlation_id=(
                uuid.UUID(data["correlation_id"]) if data.get("correlation_id") else None
            ),
            captured_at=datetime.fromisoformat(data["captured_at"]),
            metadata=data.get("metadata", {}),
        )


# ── Recovery Context ──────────────────────────────────────────────────────


@dataclass
class RecoveryContext:
    """
    The result of a successful recovery operation.

    Contains reconstructed state ready for the WorkflowEngine to resume.
    """

    workflow_id: uuid.UUID
    definition: WorkflowDefinition
    task_states: dict[str, WorkflowTaskState]
    queue: TaskQueue
    recovery_attempt: int
    """How many times recovery has been attempted for this workflow."""

    recovered_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    skipped_tasks: list[str] = field(default_factory=list)
    """Task IDs that were skipped because they were already terminal."""
    reset_tasks: list[str] = field(default_factory=list)
    """Task IDs that were reset to READY after being interrupted mid-run."""


# ── Recovery Engine ───────────────────────────────────────────────────────


class WorkflowRecovery:
    """
    Reconstructs a workflow's execution state from a WorkflowSnapshot.

    This class implements the deterministic recovery algorithm described
    in the module docstring.  It does not touch external IO directly;
    the snapshot dict is provided by the caller (who reads from the
    Runtime checkpoint mechanism).

    Usage
    -----
    ::

        snapshot_dict = runtime_checkpoint_manager.restore(checkpoint_id)
        snapshot = WorkflowSnapshot.from_dict(snapshot_dict["state_snapshot"])
        context = WorkflowRecovery().recover(snapshot)
        # Pass context.task_states and context.queue back to WorkflowEngine.
    """

    # States that are safe to keep as-is on recovery.
    _KEEP_STATES: frozenset[WorkflowTaskStatus] = frozenset({
        WorkflowTaskStatus.SUCCEEDED,
        WorkflowTaskStatus.CANCELLED,
        WorkflowTaskStatus.PENDING,
        WorkflowTaskStatus.BLOCKED,
        WorkflowTaskStatus.RETRYING,
    })

    # States that indicate the task was mid-execution at interruption time.
    _INTERRUPTED_STATES: frozenset[WorkflowTaskStatus] = frozenset({
        WorkflowTaskStatus.RUNNING,
        WorkflowTaskStatus.WAITING_APPROVAL,
    })

    def recover(
        self,
        snapshot: WorkflowSnapshot,
        *,
        max_recovery_attempts: int = 3,
    ) -> RecoveryContext:
        """
        Reconstruct workflow state from a snapshot.

        Args:
            snapshot: The workflow snapshot to recover from.
            max_recovery_attempts: Maximum allowed recovery attempts.

        Returns:
            A RecoveryContext ready to be passed back to the WorkflowEngine.

        Raises:
            RecoveryError: If recovery attempt limit is exceeded or the
                snapshot is malformed.
        """
        if snapshot.recovery_attempt >= max_recovery_attempts:
            raise RecoveryError(
                f"Workflow {snapshot.workflow_id} has exceeded the maximum "
                f"recovery attempt limit ({max_recovery_attempts}).",
                details={
                    "workflow_id": str(snapshot.workflow_id),
                    "recovery_attempt": snapshot.recovery_attempt,
                    "max_recovery_attempts": max_recovery_attempts,
                },
            )

        # Reconstruct the WorkflowDefinition.
        try:
            definition = WorkflowDefinition.model_validate(
                snapshot.definition_snapshot
            )
        except Exception as exc:
            raise RecoveryError(
                f"Failed to reconstruct WorkflowDefinition for workflow "
                f"{snapshot.workflow_id}: {exc}",
                details={"workflow_id": str(snapshot.workflow_id)},
            ) from exc

        # Build a lookup of TaskDefinitions.
        task_defs: dict[str, TaskDefinition] = {
            t.task_id: t for t in definition.tasks
        }

        # Reconstruct task states.
        task_states: dict[str, WorkflowTaskState] = {}
        skipped: list[str] = []
        reset: list[str] = []

        for task_id, ts_snapshot in snapshot.task_snapshots.items():
            if task_id not in task_defs:
                raise RecoveryError(
                    f"Snapshot references unknown task_id {task_id!r} "
                    f"in workflow {snapshot.workflow_id}.",
                    details={
                        "workflow_id": str(snapshot.workflow_id),
                        "unknown_task_id": task_id,
                    },
                )

            task_def = task_defs[task_id]
            ts = WorkflowTaskState.from_snapshot(ts_snapshot, task_def)

            if ts.status in {WorkflowTaskStatus.SUCCEEDED, WorkflowTaskStatus.CANCELLED}:
                # Terminal — preserve as-is.
                skipped.append(task_id)

            elif ts.status in self._INTERRUPTED_STATES:
                # Mid-execution at interruption → reset to READY for re-dispatch.
                ts.status = WorkflowTaskStatus.READY
                ts.started_at = None
                ts.finished_at = None
                reset.append(task_id)

            elif ts.status == WorkflowTaskStatus.FAILED:
                # Failed with retries remaining → back to RETRYING.
                if ts.attempt_number < task_def.retry_policy.max_attempts:
                    ts.status = WorkflowTaskStatus.RETRYING
                    reset.append(task_id)
                # else: keep FAILED — no retries left.

            # All other states (PENDING, BLOCKED, READY, RETRYING) keep.

            task_states[task_id] = ts

        # Rebuild the queue — only enqueue READY tasks (not already running).
        queue = TaskQueue()
        for task_id, ts in task_states.items():
            if ts.status == WorkflowTaskStatus.READY:
                queue.enqueue(
                    task_id=task_id,
                    workflow_id=str(snapshot.workflow_id),
                    priority=task_defs[task_id].priority,
                )

        return RecoveryContext(
            workflow_id=snapshot.workflow_id,
            definition=definition,
            task_states=task_states,
            queue=queue,
            recovery_attempt=snapshot.recovery_attempt + 1,
            skipped_tasks=skipped,
            reset_tasks=reset,
        )

    def create_snapshot(
        self,
        workflow_id: uuid.UUID,
        definition: WorkflowDefinition,
        task_states: dict[str, WorkflowTaskState],
        queue: TaskQueue,
        approval_gates: dict[str, Any] | None = None,
        recovery_attempt: int = 0,
        correlation_id: uuid.UUID | None = None,
    ) -> WorkflowSnapshot:
        """
        Capture a snapshot of the current workflow execution state.

        Args:
            workflow_id: The workflow ID.
            definition: The workflow definition.
            task_states: Current task states.
            queue: Current task queue.
            approval_gates: Optional dict of gate_id → ApprovalGate.
            recovery_attempt: Current recovery attempt count.
            correlation_id: Correlation ID for tracing.

        Returns:
            A WorkflowSnapshot ready for checkpointing.
        """
        task_snapshots = {
            task_id: ts.to_snapshot()
            for task_id, ts in task_states.items()
        }

        gate_snapshots: dict[str, dict[str, Any]] = {}
        if approval_gates:
            for gate_id, gate in approval_gates.items():
                if hasattr(gate, "to_snapshot"):
                    gate_snapshots[gate_id] = gate.to_snapshot()

        return WorkflowSnapshot(
            workflow_id=workflow_id,
            definition_snapshot=definition.model_dump(mode="python"),
            task_snapshots=task_snapshots,
            queue_snapshot=queue.snapshot(),
            approval_gate_snapshots=gate_snapshots,
            recovery_attempt=recovery_attempt,
            correlation_id=correlation_id,
        )
