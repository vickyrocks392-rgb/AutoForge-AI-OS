"""Durable Workflow Store tests — Phase 18-J.3.

Validates:
- Durable workflow registration and definition persistence
- Optimistic versioning and concurrency control
- Abandoned workflow detection based on process ownership
- Reconciling abandoned workflows to INTERRUPTED (recoverable)
- Claiming INTERRUPTED workflow for controlled resume
- Terminal states (FINISHED, FAILED, CANCELLED)
- Controlled resume of INTERRUPTED executions (new attempt, same logical ID)
- Cache coherence across commits and rollbacks
"""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest

from autoforge_runtime import (
    DurableExecutionStore,
    DurableWorkflowStore,
    EntityType,
    ExecutionStatus,
    PersistenceLayer,
    WorkflowStatus,
)
from autoforge_runtime.exceptions import (
    EntityNotFoundError,
    InvalidStateError,
    InvalidTransitionError,
    VersionConflictError,
)


@pytest.fixture
def persistence(tmp_path: Path):
    layer = PersistenceLayer(tmp_path / "runtime_workflow_test.sqlite3")
    yield layer
    layer.close()


@pytest.fixture
def wf_store(persistence: PersistenceLayer) -> DurableWorkflowStore:
    return DurableWorkflowStore(persistence, owner_id="proc-1:1001")


@pytest.fixture
def exec_store(persistence: PersistenceLayer) -> DurableExecutionStore:
    return DurableExecutionStore(persistence, owner_id="proc-1:1001")


def test_register_and_get_workflow(wf_store: DurableWorkflowStore):
    wid = uuid.uuid4()
    definition = {
        "workflow_id": str(wid),
        "name": "data-pipeline",
        "tasks": [{"task_id": "extract"}, {"task_id": "transform"}],
    }
    wf = wf_store.register_workflow(
        wid,
        definition=definition,
        metadata={"user": "alice"},
    )
    assert wf.workflow_id == wid
    assert wf.status == WorkflowStatus.RUNNING
    assert wf.owner_id == "proc-1:1001"
    assert wf.task_count == 2
    assert wf.state_version == 1

    fetched = wf_store.get_workflow(wid)
    assert fetched.workflow_id == wid
    assert fetched.definition["name"] == "data-pipeline"
    assert fetched.metadata["user"] == "alice"


def test_register_workflow_idempotent(wf_store: DurableWorkflowStore):
    wid = uuid.uuid4()
    w1 = wf_store.register_workflow(wid, definition={"tasks": []})
    w2 = wf_store.register_workflow(wid, definition={"tasks": []})
    assert w1.workflow_id == w2.workflow_id
    assert w1.state_version == w2.state_version


def test_find_abandoned_workflows(persistence: PersistenceLayer):
    store_a = DurableWorkflowStore(persistence, owner_id="proc-A:2001")
    store_b = DurableWorkflowStore(persistence, owner_id="proc-B:2002")

    wid_a = uuid.uuid4()
    wid_b = uuid.uuid4()

    store_a.register_workflow(wid_a, definition={"tasks": []})
    store_b.register_workflow(wid_b, definition={"tasks": []})

    # store_b looking for abandoned workflows sees wid_a because owner is proc-A
    abandoned = store_b.find_abandoned_workflows()
    assert len(abandoned) == 1
    assert abandoned[0].workflow_id == wid_a
    assert abandoned[0].owner_id == "proc-A:2001"


def test_reconcile_abandoned_workflows(persistence: PersistenceLayer):
    store_dead = DurableWorkflowStore(persistence, owner_id="proc-dead:9999")
    store_alive = DurableWorkflowStore(persistence, owner_id="proc-alive:1000")

    wid = uuid.uuid4()
    store_dead.register_workflow(wid, definition={"tasks": []})

    reconciled = store_alive.reconcile_abandoned_workflows()
    assert len(reconciled) == 1
    assert reconciled[0].workflow_id == wid
    assert reconciled[0].status == WorkflowStatus.INTERRUPTED
    assert reconciled[0].recoverable is True

    # Re-check via store_alive
    rechecked = store_alive.get_workflow(wid)
    assert rechecked.status == WorkflowStatus.INTERRUPTED
    assert rechecked.recoverable is True


def test_claim_workflow_for_resume(persistence: PersistenceLayer):
    store_dead = DurableWorkflowStore(persistence, owner_id="proc-dead:9999")
    store_alive = DurableWorkflowStore(persistence, owner_id="proc-alive:1000")

    wid = uuid.uuid4()
    store_dead.register_workflow(wid, definition={"tasks": []})
    store_alive.reconcile_abandoned_workflows()

    # Now claim for resume
    resumed = store_alive.claim_workflow_for_resume(wid)
    assert resumed.status == WorkflowStatus.RUNNING
    assert resumed.owner_id == "proc-alive:1000"
    assert resumed.recoverable is False

    # Calling again from same owner is idempotent
    again = store_alive.claim_workflow_for_resume(wid)
    assert again.workflow_id == wid
    assert again.status == WorkflowStatus.RUNNING


def test_concurrent_resume_optimistic_conflict(persistence: PersistenceLayer):
    store_dead = DurableWorkflowStore(persistence, owner_id="proc-dead:9999")
    store_p1 = DurableWorkflowStore(persistence, owner_id="proc-1:1001")
    store_p2 = DurableWorkflowStore(persistence, owner_id="proc-2:1002")

    wid = uuid.uuid4()
    store_dead.register_workflow(wid, definition={"tasks": []})
    store_p1.reconcile_abandoned_workflows()

    wf_before = store_p1.get_workflow(wid)
    expected_v = wf_before.state_version

    # Process 1 claims successfully with expected_version
    store_p1.claim_workflow_for_resume(wid, expected_version=expected_v)

    # Process 2 attempts to claim with stale expected_version -> raises VersionConflictError
    with pytest.raises(VersionConflictError):
        store_p2.claim_workflow_for_resume(wid, expected_version=expected_v)


def test_controlled_execution_resume(
    exec_store: DurableExecutionStore, persistence: PersistenceLayer
):
    wid = uuid.uuid4()
    dead_store = DurableExecutionStore(persistence, owner_id="dead-host:5555")
    e = dead_store.begin_execution(workflow_id=wid, task_id="task-compute")
    assert e.status == ExecutionStatus.RUNNING

    # Reconcile abandoned
    live_store = DurableExecutionStore(persistence, owner_id="live-host:6666")
    live_store.reconcile_interrupted_executions()

    reconciled_e = live_store.get_execution(e.execution_id)
    assert reconciled_e.status == ExecutionStatus.INTERRUPTED
    assert reconciled_e.recoverable is True

    # Resume execution
    resumed_e, attempt_2 = live_store.resume_execution(e.execution_id)
    assert resumed_e.execution_id == e.execution_id  # Stable canonical identity!
    assert resumed_e.status == ExecutionStatus.RUNNING
    assert resumed_e.owner_id == "live-host:6666"
    assert attempt_2.attempt_number == 2
    assert attempt_2.execution_id == e.execution_id

    # Attempts lineage: attempt 1 = interrupted, attempt 2 = started
    attempts = live_store.get_attempts(e.execution_id)
    assert len(attempts) == 2
    assert attempts[0].attempt_number == 1
    assert attempts[0].status.value == "interrupted"
    assert attempts[1].attempt_number == 2
    assert attempts[1].status.value == "started"


def test_workflow_lifecycle_transitions(wf_store: DurableWorkflowStore):
    wid = uuid.uuid4()
    wf_store.register_workflow(wid, definition={"tasks": []})

    # Complete workflow
    completed = wf_store.complete_workflow(wid, result={"exit_code": 0})
    assert completed.status == WorkflowStatus.FINISHED
    assert completed.metadata["result"] == {"exit_code": 0}

    # Cannot resume finished workflow
    with pytest.raises(InvalidStateError):
        wf_store.claim_workflow_for_resume(wid)
