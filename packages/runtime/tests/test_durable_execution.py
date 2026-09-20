"""Durable execution identity, boundaries and reconstruction (Phase 18-J.2).

These tests validate the durable execution model added by 18-J.2 on top of
the 18-J.1 persistence foundation:

    - canonical execution identity (workflow + task work unit -> stable
      execution_id) and its distinction from attempts and checkpoints
    - durable execution / attempt / checkpoint records
    - atomic lifecycle transitions (transactional, replay-safe)
    - optimistic version conflicts
    - rollback leaves no partially persisted execution state
    - cache coherence after commit and after rollback
    - interrupted execution semantics and queries
    - restart reconstruction of execution state from durable storage
    - failure injection at critical persistence boundaries
    - real cross-process restart reconstruction (subprocess)
"""

from __future__ import annotations

import json
import subprocess
import sys
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest

from autoforge_runtime import EntityType, PersistenceLayer
from autoforge_runtime.exceptions import (
    EntityNotFoundError,
    VersionConflictError,
)
from autoforge_runtime.execution_store import (
    AttemptStatus,
    DurableExecutionStore,
    ExecutionReconstruction,
    ExecutionStatus,
    execution_id_for_key,
    execution_key_for_task,
)

# ── Fixtures & helpers ───────────────────────────────────────────────────


@pytest.fixture
def persistence(tmp_path: Path) -> Iterator[PersistenceLayer]:
    layer = PersistenceLayer(tmp_path / "runtime_state.sqlite3")
    yield layer
    layer.close()


@pytest.fixture
def store(persistence: PersistenceLayer) -> DurableExecutionStore:
    return DurableExecutionStore(persistence, owner_id="test-owner")


WF = uuid.UUID("00000000-0000-0000-0000-00000000aa01")


def _begin(store: DurableExecutionStore, wf=WF, task="task-1", attempt=1):
    return store.begin_execution(
        workflow_id=wf,
        task_id=task,
        attempt_number=attempt,
        metadata={"project_id": "p1"},
    )


def _store_src() -> str:
    import autoforge_runtime

    return str(Path(autoforge_runtime.__file__).parent.parent)


# ── Execution / attempt identity ─────────────────────────────────────────


class TestExecutionIdentity:
    def test_create_durable_execution(self, store):
        exec_state = _begin(store)
        assert exec_state.execution_id == execution_id_for_key(
            execution_key_for_task(WF, "task-1")
        )
        assert exec_state.status == ExecutionStatus.RUNNING
        assert exec_state.workflow_id == WF
        assert exec_state.task_id == "task-1"

    def test_get_durable_execution(self, store):
        created = _begin(store)
        fetched = store.get_execution(created.execution_id)
        assert fetched.execution_id == created.execution_id
        assert fetched.workflow_id == WF
        with pytest.raises(EntityNotFoundError):
            store.get_execution(uuid.uuid4())

    def test_create_attempt(self, store):
        exec_state = _begin(store)
        attempts = store.get_attempts(exec_state.execution_id)
        assert len(attempts) == 1
        assert attempts[0].attempt_number == 1
        assert attempts[0].status == AttemptStatus.STARTED

    def test_multiple_attempts_same_execution(self, store):
        exec_state = _begin(store, attempt=1)
        store.fail_attempt(exec_state.execution_id, retryable=True)
        exec_state = store.begin_attempt(exec_state.execution_id, attempt_number=2)
        attempts = store.get_attempts(exec_state.execution_id)
        assert [a.attempt_number for a in attempts] == [1, 2]
        assert attempts[0].status == AttemptStatus.FAILED
        assert attempts[1].status == AttemptStatus.STARTED
        assert exec_state.execution_id == execution_id_for_key(
            execution_key_for_task(WF, "task-1")
        )

    def test_attempt_identity_distinct_from_execution_identity(self, store):
        exec_state = _begin(store)
        attempt = store.get_attempt_by_number(exec_state.execution_id, 1)
        assert attempt.attempt_id != exec_state.execution_id
        assert attempt.execution_id == exec_state.execution_id

    def test_retry_does_not_create_new_logical_execution(self, store):
        e1 = _begin(store, attempt=1)
        store.fail_attempt(e1.execution_id, retryable=True)
        e2 = _begin(store, attempt=2)
        assert e1.execution_id == e2.execution_id
        # retrying an already-completed execution is rejected
        store.complete_attempt(e1.execution_id)
        from autoforge_runtime.exceptions import InvalidStateError

        with pytest.raises(InvalidStateError):
            _begin(store, attempt=3)

    def test_execution_key_deterministic(self):
        key1 = execution_key_for_task(WF, "task-9")
        key2 = execution_key_for_task(str(WF), "task-9")
        assert key1 == key2
        assert execution_id_for_key(key1) == execution_id_for_key(key2)

    def test_execution_workflow_task_linkage(self, store):
        exec_state = _begin(store)
        assert store.list_executions_for_workflow(WF)[0].execution_id == exec_state.execution_id
        assert store.list_executions_for_task("task-1")[0].execution_id == exec_state.execution_id


# ── State transitions ────────────────────────────────────────────────────


class TestTransitions:
    def test_execution_state_transition(self, store):
        exec_state = _begin(store)
        store.cancel_execution(exec_state.execution_id)
        assert store.get_execution(exec_state.execution_id).status == ExecutionStatus.CANCELLED

    def test_attempt_state_transition(self, store):
        exec_state = _begin(store)
        store.complete_attempt(exec_state.execution_id)
        attempt = store.get_attempt_by_number(exec_state.execution_id, 1)
        assert attempt.status == AttemptStatus.COMPLETED
        assert attempt.completed_at is not None

    def test_atomic_execution_attempt_transition(self, store):
        """Completing an attempt also transitions the execution atomically."""
        exec_state = _begin(store)
        store.complete_attempt(exec_state.execution_id)
        execution = store.get_execution(exec_state.execution_id)
        attempt = store.get_attempt_by_number(exec_state.execution_id, 1)
        assert execution.status == ExecutionStatus.COMPLETED
        assert attempt.status == AttemptStatus.COMPLETED
        assert attempt.completed_at is not None
        assert execution.completed_at is not None

    def test_completed_execution_cannot_be_mistaken_for_running(self, store):
        exec_state = _begin(store)
        store.complete_attempt(exec_state.execution_id)
        assert store.get_execution(exec_state.execution_id).status == ExecutionStatus.COMPLETED
        assert store.list_active_executions() == []
        assert store.list_interrupted_executions() == []

    def test_version_conflict(self, store):
        exec_state = _begin(store)
        stale = store.get_execution(exec_state.execution_id)
        # a concurrent transition advances the version
        store.cancel_execution(exec_state.execution_id)
        with pytest.raises(VersionConflictError):
            store.mark_interrupted(
                exec_state.execution_id,
                reason="should conflict",
                expected_version=stale.version,
            )

    def test_transition_history_replay_safety(self, store):
        exec_state = _begin(store)
        tid = uuid.uuid4()
        store.complete_attempt(exec_state.execution_id, transition_id=tid)
        # Replaying the same transition id must not duplicate history.
        store.complete_attempt(exec_state.execution_id, transition_id=tid)
        history = store.get_transition_history(exec_state.execution_id)
        completions = [
            t for t in history if t.metadata.get("operation") == "execution.completed"
        ]
        assert len(completions) == 1


# ── Checkpoints / durable boundaries ─────────────────────────────────────


class TestCheckpoints:
    def test_durable_checkpoint_creation(self, store):
        exec_state = _begin(store)
        cp = store.record_checkpoint(
            exec_state.execution_id,
            label="step-A",
            boundary_state={"step": "A", "committed": True},
        )
        assert cp.label == "step-A"
        assert cp.execution_id == exec_state.execution_id
        assert cp.boundary_state["step"] == "A"
        assert cp.sequence >= 1

    def test_latest_checkpoint_retrieval(self, store):
        exec_state = _begin(store)
        store.record_checkpoint(exec_state.execution_id, label="step-A")
        store.record_checkpoint(exec_state.execution_id, label="step-B")
        latest = store.get_latest_checkpoint(exec_state.execution_id)
        assert latest.label == "step-B"
        checkpoints = store.get_checkpoints(exec_state.execution_id)
        assert [c.label for c in checkpoints] == ["step-A", "step-B"]

    def test_checkpoint_attempt_linkage(self, store):
        exec_state = _begin(store)
        attempt = store.get_active_attempt(exec_state.execution_id)
        cp = store.record_checkpoint(exec_state.execution_id, label="step-A")
        assert cp.attempt_id == attempt.attempt_id

    def test_unknown_checkpoint_label_query(self, store):
        exec_state = _begin(store)
        assert store.get_latest_checkpoint(exec_state.execution_id) is None
        assert all(
            c.label != "nope" for c in store.get_checkpoints(exec_state.execution_id)
        )


# ── Rollback / cache coherence ───────────────────────────────────────────


class TestRollbackAndCache:
    def test_rollback_does_not_partially_persist_execution(self, persistence, store):
        exec_state = _begin(store)
        cache = persistence.cache
        with pytest.raises(RuntimeError), persistence.transaction():
            persistence.write_state(
                EntityType.EXECUTION,
                exec_state.execution_id,
                exec_state.model_copy(
                    update={
                        "status": ExecutionStatus.CANCELLED,
                        "version": exec_state.version + 1,
                    }
                ),
            )
            raise RuntimeError("rollback now")

        # durable truth: unchanged execution, cache must retain the
        # pre-transaction committed state and must NOT retain the
        # staged (rolled-back) "cancelled" state.
        execution = store.get_execution(exec_state.execution_id)
        assert execution.status == ExecutionStatus.RUNNING
        assert execution.version == exec_state.version
        cached = cache.get(EntityType.EXECUTION, exec_state.execution_id)
        assert cached is not None
        assert cached.status == "running"
        assert cached.version == exec_state.version

    def test_cache_coherence_after_commit(self, persistence, store):
        exec_state = _begin(store)
        cache = persistence.cache
        # warm the cache
        persistence.read_state(EntityType.EXECUTION, exec_state.execution_id)
        assert (EntityType.EXECUTION, exec_state.execution_id) in cache.keys()
        store.cancel_execution(exec_state.execution_id)
        cached = cache.get(EntityType.EXECUTION, exec_state.execution_id)
        assert cached is not None
        assert cached.status == "cancelled"

    def test_cache_coherence_after_rollback(self, persistence, store):
        exec_state = _begin(store)
        persistence.read_state(EntityType.EXECUTION, exec_state.execution_id)
        with pytest.raises(RuntimeError), persistence.transaction():
            persistence.write_state(
                EntityType.EXECUTION,
                exec_state.execution_id,
                exec_state.model_copy(
                    update={
                        "status": ExecutionStatus.CANCELLED,
                        "version": exec_state.version + 1,
                    }
                ),
            )
            raise RuntimeError("boom")
        cached = persistence.cache.get(EntityType.EXECUTION, exec_state.execution_id)
        assert cached is None or cached.status == "running"


# ── Interrupted execution semantics ──────────────────────────────────────


class TestInterruptedExecutions:
    def test_interrupted_detection(self, store):
        exec_state = _begin(store)
        store.record_checkpoint(exec_state.execution_id, label="step-A")
        store.mark_interrupted(exec_state.execution_id, reason="process died")
        execution = store.get_execution(exec_state.execution_id)
        assert execution.status == ExecutionStatus.INTERRUPTED
        interrupted = store.list_interrupted_executions()
        assert [e.execution_id for e in interrupted] == [exec_state.execution_id]
        # active attempt was interrupted too
        attempts = store.get_attempts(exec_state.execution_id)
        assert attempts[0].status == AttemptStatus.INTERRUPTED

    def test_reconcile_abandoned_executions(self, store):
        exec_state = _begin(store, attempt=1)
        # simulate a dead process: the owner id no longer matches
        store._owner_id = "old-host:123"
        abandoned = store.find_abandoned_executions()
        assert [e.execution_id for e in abandoned] == [exec_state.execution_id]
        reconciled = store.reconcile_interrupted_executions()
        assert [r.execution_id for r in reconciled] == [exec_state.execution_id]
        assert (
            store.get_execution(exec_state.execution_id).status == ExecutionStatus.INTERRUPTED
        )

    def test_interrupted_never_completed_or_failed(self, store):
        exec_state = _begin(store)
        store.mark_interrupted(exec_state.execution_id, reason="crash")
        execution = store.get_execution(exec_state.execution_id)
        assert execution.status != ExecutionStatus.COMPLETED
        assert execution.status != ExecutionStatus.FAILED
        assert execution.status == ExecutionStatus.INTERRUPTED

    def test_no_automatic_resume(self, store):
        """Interrupted executions are reported, never resumed, by J.2."""
        exec_state = _begin(store)
        store.mark_interrupted(exec_state.execution_id, reason="crash")
        reconstruction = store.reconstruct(exec_state.execution_id)
        assert isinstance(reconstruction, ExecutionReconstruction)
        assert reconstruction.resumable is True
        # J.2 exposes metadata only; dispatching/resuming is 18-J.3.
        assert reconstruction.recovery_metadata["status"] == "interrupted"


# ── Restart reconstruction ───────────────────────────────────────────────


class TestRestartReconstruction:
    def test_reconstruction_from_durable_storage(self, store):
        exec_state = _begin(store)
        store.record_checkpoint(exec_state.execution_id, label="step-A")
        store.record_checkpoint(exec_state.execution_id, label="step-B")
        store.mark_interrupted(exec_state.execution_id, reason="crash mid-execution")

        # simulate a fresh process: new store instance over the same db
        fresh = DurableExecutionStore(
            PersistenceLayer(store.persistence.db_path), owner_id="new-owner"
        )
        reconstruction = fresh.reconstruct(exec_state.execution_id)
        assert reconstruction.execution.execution_id == exec_state.execution_id
        assert reconstruction.execution.status == ExecutionStatus.INTERRUPTED
        assert [a.attempt_number for a in reconstruction.attempts] == [1]
        assert reconstruction.latest_checkpoint is not None
        assert reconstruction.latest_checkpoint.label == "step-B"
        assert reconstruction.resumable is True
        assert reconstruction.recovery_metadata["last_checkpoint_label"] == "step-B"
        assert reconstruction.recovery_metadata["transitions"] >= 3
        fresh.persistence.close()

    def test_active_execution_query_after_reopen(self, store):
        exec_state = _begin(store)
        fresh = DurableExecutionStore(
            PersistenceLayer(store.persistence.db_path), owner_id="new-owner"
        )
        active = fresh.list_active_executions()
        assert [e.execution_id for e in active] == [exec_state.execution_id]
        fresh.persistence.close()


_SUBPROCESS_WRITER = """
import sys, uuid
from pathlib import Path
sys.path.insert(0, {src!r})
from autoforge_runtime import PersistenceLayer
from autoforge_runtime.execution_store import DurableExecutionStore

p = PersistenceLayer(Path(sys.argv[1]))
s = DurableExecutionStore(p, owner_id="process-A")
e = s.begin_execution(workflow_id=uuid.UUID(sys.argv[2]), task_id="task-R")
s.record_checkpoint(e.execution_id, label="step-A")
s.record_checkpoint(e.execution_id, label="step-B")
print(e.execution_id)
p.close()  # Process A "terminates" without completing the execution
"""

_SUBPROCESS_READER = """
import sys, json
from pathlib import Path
sys.path.insert(0, {src!r})
from autoforge_runtime import PersistenceLayer
from autoforge_runtime.execution_store import DurableExecutionStore, ExecutionStatus

p = PersistenceLayer(Path(sys.argv[1]))
s = DurableExecutionStore(p, owner_id="process-B")
# J.2 startup detection: classify executions owned by dead processes.
s.reconcile_interrupted_executions()
interrupted = s.list_interrupted_executions()
out = {{"interrupted": len(interrupted)}}
if interrupted:
    r = s.reconstruct(interrupted[0].execution_id)
    out.update(
        execution_id=str(r.execution.execution_id),
        status=r.execution.status.value,
        attempts=[a.attempt_number for a in r.attempts],
        attempt_status=[a.status.value for a in r.attempts],
        latest=r.latest_checkpoint.label if r.latest_checkpoint else None,
        version=r.execution.version,
        transitions=r.recovery_metadata["transitions"],
        resumable=r.resumable,
        completed=(r.execution.status == ExecutionStatus.COMPLETED),
    )
print(json.dumps(out))
p.close()
"""


class TestSubprocessRestart:
    def test_real_process_boundary_reconstruction(self, tmp_path: Path):
        """REAL process boundary: Process A writes durable state and exits
        without completing the execution; Process B reconstructs everything
        from durable storage alone and classifies it as interrupted."""
        db_path = tmp_path / "restart.sqlite3"
        writer = _SUBPROCESS_WRITER.format(src=_store_src())
        result = subprocess.run(
            [sys.executable, "-c", writer, str(db_path), str(WF)],
            capture_output=True,
            text=True,
            timeout=120,
        )
        assert result.returncode == 0, result.stderr

        reader = _SUBPROCESS_READER.format(src=_store_src())
        result = subprocess.run(
            [sys.executable, "-c", reader, str(db_path)],
            capture_output=True,
            text=True,
            timeout=120,
        )
        assert result.returncode == 0, result.stderr
        out = json.loads(result.stdout.strip().splitlines()[-1])
        assert out["interrupted"] == 1
        assert out["status"] == "interrupted"
        assert out["completed"] is False
        assert out["attempts"] == [1]
        assert out["attempt_status"] == ["interrupted"]
        assert out["latest"] == "step-B"
        assert out["resumable"] is True
        assert out["transitions"] >= 3
        assert out["version"] >= 1


# ── Failure injection at critical boundaries ─────────────────────────────


class TestFailureInjection:
    """Crash/failure injection at each critical persistence boundary.

    Durable truth must remain internally consistent after every injected
    failure: an attempt never claims completion while the execution still
    says running, and an in-flight unit is never reported as committed.
    """

    def test_crash_before_execution_start_commit(self, persistence):
        fresh = DurableExecutionStore(persistence)
        with pytest.raises(RuntimeError), persistence.transaction():
            raise RuntimeError("crash before start commit")
        assert fresh.list_executions() == []

    def test_crash_during_attempt_start(self, persistence, store):
        exec_state = _begin(store)
        with pytest.raises(RuntimeError), persistence.transaction():
            persistence.write_state(
                EntityType.EXECUTION,
                exec_state.execution_id,
                exec_state.model_copy(
                    update={
                        "status": ExecutionStatus.CANCELLED,
                        "version": exec_state.version + 1,
                    }
                ),
            )
            raise RuntimeError("crash during attempt start")
        execution = store.get_execution(exec_state.execution_id)
        assert execution.status == ExecutionStatus.RUNNING
        assert store.get_attempts(exec_state.execution_id)[0].status == AttemptStatus.STARTED

    def test_crash_after_checkpoint_commit(self, store):
        exec_state = _begin(store)
        store.record_checkpoint(exec_state.execution_id, label="step-B")
        # crash: step C never committed — no checkpoint, no completion
        assert store.get_latest_checkpoint(exec_state.execution_id).label == "step-B"
        assert store.get_execution(exec_state.execution_id).status == ExecutionStatus.RUNNING
        assert all(
            c.label != "step-C" for c in store.get_checkpoints(exec_state.execution_id)
        )

    def test_crash_before_completion_commit(self, store):
        exec_state = _begin(store)
        # the unit ran to completion (boundary written) but the completion
        # commit never happened: durable truth is still "running"
        store.record_checkpoint(exec_state.execution_id, label="dispatch-completed")
        execution = store.get_execution(exec_state.execution_id)
        assert execution.status == ExecutionStatus.RUNNING
        assert store.get_active_attempt(exec_state.execution_id) is not None

    def test_after_completion_commit_is_terminal(self, store):
        exec_state = _begin(store)
        store.complete_attempt(exec_state.execution_id)
        execution = store.get_execution(exec_state.execution_id)
        assert execution.status == ExecutionStatus.COMPLETED
        # a terminal execution cannot be restarted as a new attempt
        from autoforge_runtime.exceptions import InvalidStateError

        with pytest.raises(InvalidStateError):
            store.begin_attempt(exec_state.execution_id, attempt_number=2)

    def test_internally_consistent_after_retryable_failure(self, store):
        exec_state = _begin(store)
        store.fail_attempt(exec_state.execution_id, retryable=True)
        execution = store.get_execution(exec_state.execution_id)
        attempt = store.get_attempt_by_number(exec_state.execution_id, 1)
        # retryable failure: execution keeps running, attempt failed — one
        # consistent interpretation of durable truth
        assert execution.status == ExecutionStatus.RUNNING
        assert attempt.status == AttemptStatus.FAILED
