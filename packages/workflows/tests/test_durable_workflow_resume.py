"""Comprehensive Phase 18-J.3 Tests: Durable Workflow Resume + State Reconstruction.

Validates:
1. Durable workflow reconstruction from authoritative SQLite storage.
2. Completed work is never queued and never replayed.
3. Interrupted executions (dead owner) are identified and cleanly resumed.
4. Logical execution identity and workflow identity are strictly preserved.
5. Attempt numbering increments on resume (attempt 2 under same execution_id).
6. Retry counters and failure metadata survive restart.
7. Deterministic queue derivation from DAG + durable task states.
8. Non-dispatching supervisor startup reconciliation.
9. Idempotent resume within process.
10. Concurrency-safe resume across processes (optimistic locking preventing duplicate dispatch).
11. Crash boundary scenarios.
12. Real OS subprocess crash and resume.
"""

from __future__ import annotations

import os
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

from autoforge_runtime.exceptions import InvalidStateError, VersionConflictError
from autoforge_runtime.execution_store import DurableExecutionStore
from autoforge_runtime.models import (
    AttemptStatus,
    ExecutionStatus,
    WorkflowStatus,
)
from autoforge_runtime.persistence import PersistenceLayer
from autoforge_runtime.workflow_store import DurableWorkflowStore
from autoforge_workflows.engine import WorkflowEngine, WorkflowEngineStatus
from autoforge_workflows.errors import RecoveryError, WorkflowNotFoundError
from autoforge_workflows.models import (
    DependencyEdge,
    DependencyPolicy,
    ExecutionPolicy,
    RetryPolicy,
    TaskDefinition,
    WorkflowDefinition,
    WorkflowTaskStatus,
)
from autoforge_workflows.reconstruction import WorkflowReconstructor
from autoforge_workflows.supervisor import WorkflowSupervisor


def _make_sample_workflow(
    workflow_id: uuid.UUID | None = None,
) -> WorkflowDefinition:
    """Creates a 3-task pipeline: task_a -> task_b -> task_c."""
    wid = workflow_id or uuid.uuid4()
    t_a = TaskDefinition(
        task_id="task_a",
        name="Task A",
        priority="high",
        retry_policy=RetryPolicy(max_attempts=3),
    )
    t_b = TaskDefinition(
        task_id="task_b",
        name="Task B",
        priority="critical",
        retry_policy=RetryPolicy(max_attempts=3),
    )
    t_c = TaskDefinition(
        task_id="task_c",
        name="Task C",
        priority="medium",
        retry_policy=RetryPolicy(max_attempts=3),
    )
    edges = [
        DependencyEdge(upstream_task_id="task_a", downstream_task_id="task_b"),
        DependencyEdge(upstream_task_id="task_b", downstream_task_id="task_c"),
    ]
    return WorkflowDefinition(
        workflow_id=wid,
        name="test_pipeline",
        tasks=[t_a, t_b, t_c],
        dependencies=edges,
        execution_policy=ExecutionPolicy(max_concurrent_tasks=2),
    )


@pytest.fixture
def test_db_path(tmp_path: Path) -> Path:
    return tmp_path / "autoforge_test.db"


@pytest.fixture
def stores(test_db_path: Path):
    persistence = PersistenceLayer(test_db_path)
    exec_store = DurableExecutionStore(persistence)
    wf_store = DurableWorkflowStore(persistence)
    yield persistence, wf_store, exec_store
    persistence.close()


# ─────────────────────────────────────────────────────────────────────────────
# 1. Workflow Reconstruction Tests
# ─────────────────────────────────────────────────────────────────────────────


def test_reconstruct_workflow_state_and_dag(stores):
    _, wf_store, exec_store = stores
    definition = _make_sample_workflow()
    wid = definition.workflow_id

    # Register workflow
    wf_store.register_workflow(wid, definition=definition)

    # Task A completed
    e_a = exec_store.begin_execution(workflow_id=wid, task_id="task_a")
    exec_store.complete_attempt(e_a.execution_id, result={"out": "a_done"})

    # Task B interrupted
    e_b = exec_store.begin_execution(workflow_id=wid, task_id="task_b", owner_id="dead_host:99999999")
    exec_store.mark_interrupted(e_b.execution_id, reason="Process died")

    # Mark workflow interrupted
    wf_store.mark_interrupted(wid, reason="Node crash")

    # Reconstruct
    reconstructor = WorkflowReconstructor(workflow_store=wf_store, execution_store=exec_store)
    handle = reconstructor.reconstruct(wid)

    assert handle.workflow_id == wid
    assert handle.definition.name == "test_pipeline"
    assert handle._dag is not None

    # Verify task states
    states = handle.task_states
    assert states["task_a"].status == WorkflowTaskStatus.SUCCEEDED
    assert states["task_a"].result == {"out": "a_done"}
    assert states["task_a"].attempt_number == 1

    assert states["task_b"].status == WorkflowTaskStatus.READY
    assert states["task_b"].attempt_number == 1

    assert states["task_c"].status == WorkflowTaskStatus.PENDING

    # Verify queue contains ONLY task_b (task_a is done, task_c is pending)
    assert not handle._queue.contains("task_a")
    assert handle._queue.contains("task_b")
    assert not handle._queue.contains("task_c")
    assert handle._queue.qsize() == 1


def test_completed_work_never_replayed(stores):
    _, wf_store, exec_store = stores
    definition = _make_sample_workflow()
    wid = definition.workflow_id

    wf_store.register_workflow(wid, definition=definition)

    # Task A completed
    e_a = exec_store.begin_execution(workflow_id=wid, task_id="task_a")
    exec_store.complete_attempt(e_a.execution_id, result={"result": "data"})

    wf_store.mark_interrupted(wid, reason="Interrupted")

    # Reconstructed handle before engine tick has task_b in queue
    reconstructor = WorkflowReconstructor(workflow_store=wf_store, execution_store=exec_store)
    recon_handle = reconstructor.reconstruct(wid)
    assert not recon_handle._queue.contains("task_a")
    assert recon_handle._queue.contains("task_b")
    assert not recon_handle._queue.contains("task_c")

    # Resume workflow in engine
    engine = WorkflowEngine(workflow_store=wf_store, execution_store=exec_store)
    handle = engine.resume_workflow(wid)

    # Task A must remain SUCCEEDED
    assert handle.task_states["task_a"].status == WorkflowTaskStatus.SUCCEEDED
    # Task A must NOT be queued
    assert not handle._queue.contains("task_a")

    # Task B must be READY
    assert handle.task_states["task_b"].status == WorkflowTaskStatus.READY

    # Verify execution record for Task A was not modified
    latest_a = exec_store.get_execution(e_a.execution_id)
    assert latest_a.status == ExecutionStatus.COMPLETED
    assert latest_a.attempt_count == 1


def test_interrupted_work_receives_new_attempt_under_same_execution(stores):
    _, wf_store, exec_store = stores
    definition = _make_sample_workflow()
    wid = definition.workflow_id

    wf_store.register_workflow(wid, definition=definition)

    # Task A had attempt 1 interrupted
    e_a = exec_store.begin_execution(workflow_id=wid, task_id="task_a")
    assert e_a.attempt_count == 1
    exec_store.mark_interrupted(e_a.execution_id, reason="OOM crash")
    wf_store.mark_interrupted(wid, reason="Node failure")

    engine = WorkflowEngine(workflow_store=wf_store, execution_store=exec_store)
    handle = engine.resume_workflow(wid)

    # Logical execution ID must be unchanged
    resumed_e_a = exec_store.get_execution(e_a.execution_id)
    assert resumed_e_a.execution_id == e_a.execution_id
    assert resumed_e_a.status == ExecutionStatus.RUNNING
    # Attempt count must now be 2
    assert resumed_e_a.attempt_count == 2

    # History contains both attempts
    attempts = exec_store.get_attempts(e_a.execution_id)
    assert len(attempts) == 2
    assert attempts[0].attempt_number == 1
    assert attempts[0].status == AttemptStatus.INTERRUPTED
    assert attempts[1].attempt_number == 2
    assert attempts[1].status == AttemptStatus.STARTED


# ─────────────────────────────────────────────────────────────────────────────
# 2. Retry Reconstruction Tests
# ─────────────────────────────────────────────────────────────────────────────


def test_retry_metadata_and_counter_survive_restart(stores):
    _, wf_store, exec_store = stores
    definition = _make_sample_workflow()
    wid = definition.workflow_id

    wf_store.register_workflow(wid, definition=definition)

    # Task A fails attempt 1 with a retryable error
    e_a = exec_store.begin_execution(workflow_id=wid, task_id="task_a")
    exec_store.fail_attempt(
        e_a.execution_id,
        error_code="TIMEOUT",
        error_message="Network timeout",
        retryable=True,
    )
    # Execution status stays RUNNING because retryable=True
    # Let process crash
    exec_store.mark_interrupted(e_a.execution_id, reason="Crash during backoff")
    wf_store.mark_interrupted(wid, reason="Crash")

    reconstructor = WorkflowReconstructor(workflow_store=wf_store, execution_store=exec_store)
    handle = reconstructor.reconstruct(wid)

    ts_a = handle.task_states["task_a"]
    assert ts_a.attempt_number == 1
    assert ts_a.last_error_code == "TIMEOUT"
    assert ts_a.last_error_message == "Network timeout"


def test_terminal_failure_remains_terminal_after_restart(stores):
    _, wf_store, exec_store = stores
    # Task with max_attempts=1
    t_single = TaskDefinition(
        task_id="single",
        name="Single Attempt Task",
        retry_policy=RetryPolicy(max_attempts=1),
    )
    definition = WorkflowDefinition(
        name="no_retry_wf",
        tasks=[t_single],
    )
    wid = definition.workflow_id

    wf_store.register_workflow(wid, definition=definition)

    e = exec_store.begin_execution(workflow_id=wid, task_id="single", max_attempts=1)
    exec_store.fail_attempt(
        e.execution_id,
        error_code="FATAL",
        error_message="Fatal non-retryable error",
        retryable=False,
    )

    wf_store.mark_interrupted(wid, reason="Interrupted")

    reconstructor = WorkflowReconstructor(workflow_store=wf_store, execution_store=exec_store)
    handle = reconstructor.reconstruct(wid)

    ts = handle.task_states["single"]
    assert ts.status == WorkflowTaskStatus.FAILED
    assert ts.is_failed_terminal
    assert not handle._queue.contains("single")


# ─────────────────────────────────────────────────────────────────────────────
# 3. Resume Semantics & Idempotency
# ─────────────────────────────────────────────────────────────────────────────


def test_resume_workflow_is_idempotent(stores):
    _, wf_store, exec_store = stores
    definition = _make_sample_workflow()
    wid = definition.workflow_id

    wf_store.register_workflow(wid, definition=definition)
    wf_store.mark_interrupted(wid, reason="Crash")

    engine = WorkflowEngine(workflow_store=wf_store, execution_store=exec_store)
    handle1 = engine.resume_workflow(wid)
    handle2 = engine.resume_workflow(wid)

    # Should return identical active handle without duplicate claims or queue explosion
    assert handle1 is handle2
    assert handle1.task_states["task_a"].status == WorkflowTaskStatus.READY


def test_concurrent_resume_protection_via_optimistic_version(stores):
    persistence, wf_store1, exec_store1 = stores
    definition = _make_sample_workflow()
    wid = definition.workflow_id

    wf_store1.register_workflow(wid, definition=definition)
    wf_store1.mark_interrupted(wid, reason="Crash")

    # Second store instance sharing same SQLite storage, representing a different process
    wf_store2 = DurableWorkflowStore(persistence, owner_id="process_b:12345")
    exec_store2 = DurableExecutionStore(persistence, owner_id="process_b:12345")

    engine1 = WorkflowEngine(workflow_store=wf_store1, execution_store=exec_store1)
    engine2 = WorkflowEngine(workflow_store=wf_store2, execution_store=exec_store2)

    # Engine 1 claims and resumes
    handle1 = engine1.resume_workflow(wid)
    assert handle1.workflow_id == wid

    # Engine 2 attempting to resume the same workflow must fail with conflict / state error
    with pytest.raises((VersionConflictError, InvalidStateError, RecoveryError)):
        engine2.resume_workflow(wid)


# ─────────────────────────────────────────────────────────────────────────────
# 4. Supervisor Startup Reconciliation
# ─────────────────────────────────────────────────────────────────────────────


def test_supervisor_reconciliation_does_not_execute_workflows(stores):
    _, wf_store, exec_store = stores
    definition = _make_sample_workflow()
    wid = definition.workflow_id

    wf_store.register_workflow(wid, definition=definition, owner_id="host:99999999")

    # An execution running under a dead PID
    e = exec_store.begin_execution(workflow_id=wid, task_id="task_a", owner_id="host:99999999")

    supervisor = WorkflowSupervisor(workflow_store=wf_store, execution_store=exec_store)
    report = supervisor.reconcile_startup()

    assert e.execution_id in report.reconciled_executions
    assert wid in report.reconciled_workflows
    assert wid in report.recoverable_workflows

    # Verify they are INTERRUPTED and NOT RUNNING/COMPLETED
    updated_exec = exec_store.get_execution(e.execution_id)
    assert updated_exec.status == ExecutionStatus.INTERRUPTED

    updated_wf = wf_store.get_workflow(wid)
    assert updated_wf.status == WorkflowStatus.INTERRUPTED
    assert updated_wf.recoverable is True

    # Re-running startup reconciliation is completely idempotent
    report2 = supervisor.reconcile_startup()
    assert report2.reconciled_executions == []
    assert report2.reconciled_workflows == []
    assert wid in report2.recoverable_workflows


# ─────────────────────────────────────────────────────────────────────────────
# 5. Crash Boundary Tests
# ─────────────────────────────────────────────────────────────────────────────


def test_crash_boundary_before_claim_commits(stores):
    _, wf_store, exec_store = stores
    definition = _make_sample_workflow()
    wid = definition.workflow_id

    wf_store.register_workflow(wid, definition=definition)
    wf_store.mark_interrupted(wid, reason="First crash")

    # Workflow is still INTERRUPTED
    wf_before = wf_store.get_workflow(wid)
    assert wf_before.status == WorkflowStatus.INTERRUPTED

    # Next attempt cleanly claims
    claimed = wf_store.claim_workflow_for_resume(wid)
    assert claimed.status == WorkflowStatus.RUNNING


def test_crash_boundary_after_claim_before_dispatch(stores):
    _, wf_store, exec_store = stores
    definition = _make_sample_workflow()
    wid = definition.workflow_id

    wf_store.register_workflow(wid, definition=definition)
    wf_store.mark_interrupted(wid, reason="Interrupted")

    # Claimed by a process that then dies immediately
    wf_store.claim_workflow_for_resume(wid, owner_id="crashed_node:99999999")

    # Supervisor discovers this abandoned claim
    supervisor = WorkflowSupervisor(workflow_store=wf_store, execution_store=exec_store)
    report = supervisor.reconcile_startup()

    assert wid in report.reconciled_workflows
    wf_reconciled = wf_store.get_workflow(wid)
    assert wf_reconciled.status == WorkflowStatus.INTERRUPTED

    # Can be safely resumed again
    engine = WorkflowEngine(workflow_store=wf_store, execution_store=exec_store)
    handle = engine.resume_workflow(wid)
    assert handle.status == WorkflowEngineStatus.RUNNING


def test_crash_boundary_during_resumed_attempt(stores):
    _, wf_store, exec_store = stores
    definition = _make_sample_workflow()
    wid = definition.workflow_id

    wf_store.register_workflow(wid, definition=definition)
    e = exec_store.begin_execution(workflow_id=wid, task_id="task_a")
    exec_store.mark_interrupted(e.execution_id, reason="Crash in attempt 1")
    wf_store.mark_interrupted(wid, reason="Interrupted")

    # Resumed: starts attempt 2 under owner "resumer:1"
    engine1 = WorkflowEngine(workflow_store=wf_store, execution_store=exec_store)
    handle = engine1.resume_workflow(wid, owner_id="resumer:99999999")
    exec_after_resume = exec_store.get_execution(e.execution_id)
    assert exec_after_resume.attempt_count == 2
    assert exec_after_resume.status == ExecutionStatus.RUNNING

    # Crash occurs during attempt 2: supervisor reconciles
    supervisor = WorkflowSupervisor(workflow_store=wf_store, execution_store=exec_store)
    report = supervisor.reconcile_startup()
    assert e.execution_id in report.reconciled_executions

    # Execution is again INTERRUPTED
    exec_after_crash2 = exec_store.get_execution(e.execution_id)
    assert exec_after_crash2.status == ExecutionStatus.INTERRUPTED

    # Next resume starts attempt 3!
    engine2 = WorkflowEngine(workflow_store=wf_store, execution_store=exec_store)
    handle2 = engine2.resume_workflow(wid)
    exec_after_resume3 = exec_store.get_execution(e.execution_id)
    assert exec_after_resume3.attempt_count == 3
    assert exec_after_resume3.status == ExecutionStatus.RUNNING


def test_crash_boundary_after_resumed_completion(stores):
    _, wf_store, exec_store = stores
    definition = _make_sample_workflow()
    wid = definition.workflow_id

    wf_store.register_workflow(wid, definition=definition)
    e_a = exec_store.begin_execution(workflow_id=wid, task_id="task_a")
    exec_store.mark_interrupted(e_a.execution_id, reason="Crash in attempt 1")
    wf_store.mark_interrupted(wid, reason="Interrupted")

    # Resumed attempt completes
    engine = WorkflowEngine(workflow_store=wf_store, execution_store=exec_store)
    handle = engine.resume_workflow(wid)
    exec_store.complete_attempt(e_a.execution_id, result={"out": "recovered"})
    engine.mark_task_running(wid, "task_a")
    engine.report_task_success(wid, "task_a", result={"out": "recovered"})

    # Now simulate crash before downstream task_b runs
    wf_store.mark_interrupted(wid, reason="Crash after task_a completed")

    # Next restart reconstructs
    reconstructor = WorkflowReconstructor(workflow_store=wf_store, execution_store=exec_store)
    handle_next = reconstructor.reconstruct(wid)

    # Task A is SUCCEEDED and never re-queued
    assert handle_next.task_states["task_a"].status == WorkflowTaskStatus.SUCCEEDED
    assert not handle_next._queue.contains("task_a")

    # Task B is now READY
    assert handle_next.task_states["task_b"].status == WorkflowTaskStatus.READY
    assert handle_next._queue.contains("task_b")


def test_cache_coherence_across_reconstruction_and_resume(stores):
    persistence, wf_store, exec_store = stores
    definition = _make_sample_workflow()
    wid = definition.workflow_id

    wf_store.register_workflow(wid, definition=definition)
    wf_store.mark_interrupted(wid, reason="Interrupted")

    # Read from store (populates cache)
    cached_wf = wf_store.get_workflow(wid)
    assert cached_wf.status == WorkflowStatus.INTERRUPTED

    # Claim for resume
    claimed = wf_store.claim_workflow_for_resume(wid)
    assert claimed.status == WorkflowStatus.RUNNING

    # Cache must reflect durable update immediately
    cache_read = wf_store.get_workflow(wid)
    assert cache_read.status == WorkflowStatus.RUNNING
    assert cache_read.state_version == claimed.state_version


def test_cache_rollback_discard_during_resume(stores):
    persistence, wf_store, exec_store = stores
    definition = _make_sample_workflow()
    wid = definition.workflow_id

    wf_store.register_workflow(wid, definition=definition)
    wf_store.mark_interrupted(wid, reason="Interrupted")

    # Start a transaction and rollback
    try:
        with persistence.transaction():
            wf_store.claim_workflow_for_resume(wid)
            # Deliberately raise to trigger rollback
            raise RuntimeError("Simulated crash during transaction")
    except RuntimeError:
        pass

    # Cache and durable store must not expose the rolled-back RUNNING state
    wf_after_rollback = wf_store.get_workflow(wid)
    assert wf_after_rollback.status == WorkflowStatus.INTERRUPTED



# ─────────────────────────────────────────────────────────────────────────────
# 6. Real OS Subprocess Crash & Resume Test
# ─────────────────────────────────────────────────────────────────────────────


def test_real_subprocess_crash_and_resume(test_db_path: Path):
    """
    Spawns an independent OS process (Process A) which submits a workflow,
    completes Task A, starts Task B, and terminates abruptly using os._exit(0).

    Process B (this test process) then opens the same SQLite database, runs
    supervisor reconciliation, asserts Task A is SUCCEEDED, Task B is
    INTERRUPTED, resumes the workflow, and completes Task B and Task C.
    """
    workflow_id = uuid.uuid4()
    script = f"""
import os
import uuid
import sys
from pathlib import Path
from autoforge_runtime.persistence import PersistenceLayer
from autoforge_runtime.execution_store import DurableExecutionStore
from autoforge_runtime.workflow_store import DurableWorkflowStore
from autoforge_workflows.models import (
    WorkflowDefinition, TaskDefinition, DependencyEdge, RetryPolicy, ExecutionPolicy
)

db_path = Path({repr(str(test_db_path))})
persistence = PersistenceLayer(db_path)
exec_store = DurableExecutionStore(persistence)
wf_store = DurableWorkflowStore(persistence)

wid = uuid.UUID({repr(str(workflow_id))})
t_a = TaskDefinition(task_id="task_a", name="Task A")
t_b = TaskDefinition(task_id="task_b", name="Task B")
t_c = TaskDefinition(task_id="task_c", name="Task C")
edges = [
    DependencyEdge(upstream_task_id="task_a", downstream_task_id="task_b"),
    DependencyEdge(upstream_task_id="task_b", downstream_task_id="task_c"),
]
defn = WorkflowDefinition(
    workflow_id=wid,
    name="subprocess_pipeline",
    tasks=[t_a, t_b, t_c],
    dependencies=edges,
)

wf_store.register_workflow(wid, definition=defn)

# Task A completes
e_a = exec_store.begin_execution(workflow_id=wid, task_id="task_a")
exec_store.complete_attempt(e_a.execution_id, result={{"result": "a_completed"}})

# Task B starts under this process's PID
e_b = exec_store.begin_execution(workflow_id=wid, task_id="task_b")

# Abruptly exit process simulating crash
os._exit(0)
"""
    # Execute Process A
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"Process A failed: {result.stderr}"

    # Process B: Inspect and reconcile state
    persistence = PersistenceLayer(test_db_path)
    exec_store = DurableExecutionStore(persistence)
    wf_store = DurableWorkflowStore(persistence)

    # 1. Supervisor startup reconciliation
    supervisor = WorkflowSupervisor(workflow_store=wf_store, execution_store=exec_store)
    report = supervisor.reconcile_startup()

    # Task B execution and workflow should have been reconciled (Process A died)
    assert len(report.reconciled_executions) == 1
    assert len(report.reconciled_workflows) == 1
    assert workflow_id in report.recoverable_workflows

    # 2. Reconstruct workflow
    reconstructor = WorkflowReconstructor(workflow_store=wf_store, execution_store=exec_store)
    handle = reconstructor.reconstruct(workflow_id)

    # Task A was completed
    assert handle.task_states["task_a"].status == WorkflowTaskStatus.SUCCEEDED
    assert handle.task_states["task_a"].result == {"result": "a_completed"}

    # Task B was interrupted and is now READY for controlled resume
    assert handle.task_states["task_b"].status == WorkflowTaskStatus.READY

    # Task C is waiting on Task B
    assert handle.task_states["task_c"].status == WorkflowTaskStatus.PENDING

    # Queue contains ONLY Task B
    assert not handle._queue.contains("task_a")
    assert handle._queue.contains("task_b")
    assert not handle._queue.contains("task_c")

    # 3. Controlled Resume
    engine = WorkflowEngine(workflow_store=wf_store, execution_store=exec_store)
    resumed_handle = engine.resume_workflow(workflow_id)

    # Execution for Task B received attempt 2 under same execution ID
    exec_b = [e for e in exec_store.list_executions_for_workflow(workflow_id) if e.task_id == "task_b"][0]
    assert exec_b.status == ExecutionStatus.RUNNING
    assert exec_b.attempt_count == 2

    # Complete Task B
    engine.mark_task_running(workflow_id, "task_b")
    exec_store.complete_attempt(exec_b.execution_id, result={"result": "b_completed"})
    decision_b = engine.report_task_success(workflow_id, "task_b", result={"result": "b_completed"})

    # Task C is now newly ready!
    assert "task_c" in decision_b.newly_ready
    assert resumed_handle.task_states["task_c"].status == WorkflowTaskStatus.READY

    # Start and complete Task C
    engine.mark_task_running(workflow_id, "task_c")
    exec_c = exec_store.begin_execution(workflow_id=workflow_id, task_id="task_c")
    exec_store.complete_attempt(exec_c.execution_id, result={"result": "c_completed"})
    decision_c = engine.report_task_success(workflow_id, "task_c", result={"result": "c_completed"})

    # Entire workflow is complete
    assert decision_c.workflow_complete
    assert resumed_handle.status == WorkflowEngineStatus.COMPLETED

    # Verify durable state in SQLite is FINISHED
    final_wf = wf_store.get_workflow(workflow_id)
    assert final_wf.status == WorkflowStatus.FINISHED
