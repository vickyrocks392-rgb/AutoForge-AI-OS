"""
Unit tests for ExecutionRecovery.
"""

import uuid
import pytest

from autoforge_execution.models import WorkerState, WorkerStatus, WorkerType
from autoforge_execution.recovery import ExecutionRecovery


def test_worker_snapshot_and_restore():
    w_id = "worker-rec-1"
    wf_id = uuid.uuid4()
    corr_id = uuid.uuid4()

    state = WorkerState(
        worker_id=w_id,
        worker_type=WorkerType.CODING,
        task_id="task-rec-100",
        workflow_id=wf_id,
        correlation_id=corr_id,
        attempt_number=2,
        status=WorkerStatus.RUNNING,
        current_iteration=3,
        last_error_code="TEST_FAILED",
        last_error_message="Assertion failed in test_recovery",
    )

    snapshot = ExecutionRecovery.snapshot_worker(state)
    assert snapshot["worker_id"] == w_id
    assert snapshot["workflow_id"] == str(wf_id)
    assert snapshot["status"] == "running"
    assert snapshot["current_iteration"] == 3

    restored = ExecutionRecovery.restore_worker_state(snapshot)
    assert restored.worker_id == w_id
    assert restored.workflow_id == wf_id
    assert restored.correlation_id == corr_id
    assert restored.attempt_number == 2
    assert restored.status == WorkerStatus.RUNNING
    assert restored.current_iteration == 3
    assert restored.last_error_code == "TEST_FAILED"
