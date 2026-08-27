"""
Execution Recovery — snapshot and recovery for execution state.

Enables resuming interrupted engineering loops and recovering worker states
without creating a competing recovery database (uses Runtime checkpoint store).
"""

from __future__ import annotations

import uuid
from typing import Any

from autoforge_execution.models import WorkerState, WorkerStatus, WorkerType


class ExecutionRecovery:
    """
    Handles snapshot creation and restoration for execution workers and loops.
    """

    @staticmethod
    def snapshot_worker(worker_state: WorkerState) -> dict[str, Any]:
        """
        Create a serializable snapshot of a worker's state.
        """
        return worker_state.to_snapshot()

    @staticmethod
    def restore_worker_state(snapshot: dict[str, Any]) -> WorkerState:
        """
        Reconstruct a WorkerState from a checkpoint snapshot.
        """
        state = WorkerState(
            worker_id=snapshot["worker_id"],
            worker_type=WorkerType(snapshot["worker_type"]),
            task_id=snapshot["task_id"],
            workflow_id=uuid.UUID(snapshot["workflow_id"]) if snapshot.get("workflow_id") else None,
            correlation_id=uuid.UUID(snapshot["correlation_id"]) if snapshot.get("correlation_id") else None,
            attempt_number=snapshot.get("attempt_number", 1),
            status=WorkerStatus(snapshot["status"]),
            current_iteration=snapshot.get("current_iteration", 0),
            last_error_code=snapshot.get("last_error_code"),
            last_error_message=snapshot.get("last_error_message"),
            cancellation_requested=snapshot.get("cancellation_requested", False),
            metadata=snapshot.get("metadata", {}),
        )
        return state
