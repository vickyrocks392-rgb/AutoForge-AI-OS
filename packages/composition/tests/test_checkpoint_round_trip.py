"""Cross-package checkpoint round-trip integration test.

Exercises REAL Runtime components through the composition root:

    Create runtime state -> Execute transitions -> Create checkpoint
        -> Serialize checkpoint -> Simulate failure/restart
        -> Restore into a fresh RuntimeStateManager -> Resume
        -> Verify state integrity, history, events, idempotency
"""

from __future__ import annotations

import uuid

import pytest

from autoforge_composition import AutoForgeSystem, build_autoforge_system
from autoforge_events.event_types import EventType
from autoforge_kernel.interfaces import Request
from autoforge_models.project import Project
from autoforge_models.task import Task
from autoforge_runtime import (
    CheckpointType,
    EntityType,
    RestoreType,
    RuntimeStateManager,
    RuntimeSnapshot,
)


@pytest.fixture
async def system() -> AutoForgeSystem:
    s = build_autoforge_system()
    await s.initialize()
    return s


async def _seed_running_project(system: AutoForgeSystem) -> tuple[uuid.UUID, uuid.UUID]:
    """Drive real state to RUNNING via the composed boundary."""
    request = Request(request_text="Round trip")
    result = await system.kernel.submit_request(request)
    pid = uuid.UUID(str(result["project_id"]))

    task = Task(project_id=pid, title="Implement feature")
    tid = await system.runtime_facade.create_task(task)

    # submit_request already moved intake -> planning; now planning ->
    # running through the authoritative runtime (with required plan
    # preconditions supplied as transition metadata).
    system.runtime.transition_project_state(
        pid,
        "running",
        metadata={"strategic_plan": {"id": "SP"}, "executable_workflow": {"id": "WF"}},
    )
    return pid, tid


async def test_checkpoint_round_trip_across_restart(system: AutoForgeSystem) -> None:
    """Full persistence -> crash -> restore -> resume cycle."""
    received: list = []
    system.events.subscribe(
        received.append,
        event_types=[EventType.CHECKPOINT_CREATED, EventType.CHECKPOINT_RESTORED],
    )

    pid, tid = await _seed_running_project(system)

    # ── 1-2. State created and transitions executed ───────────────────
    pre_state = system.runtime.get_project_state(pid)
    assert pre_state.status.value == "running"
    pre_version = pre_state.version
    assert pre_version >= 3  # created + planning + running

    # Transition history recorded by the authoritative runtime.
    history = system.runtime.get_runtime_history(EntityType.PROJECT, pid)
    assert [(t.from_state, t.to_state) for t in history] == [
        ("created", "planning"),
        ("planning", "running"),
    ]

    # ── 3. Checkpoint creation (real CheckpointManager) ───────────────
    checkpoint_id = system.runtime.create_checkpoint(
        pid, CheckpointType.MANUAL, label="before-mutation"
    )

    # ── Event publication for the checkpoint ──────────────────────────
    assert any(
        e.event_type == EventType.CHECKPOINT_CREATED and e.aggregate_id == pid
        for e in received
    ), "checkpoint.created never reached the transport observer"

    # ── 4. Mutate after checkpoint (the 'damage' before failure) ──────
    system.runtime.update_task_state(
        tid, "ready", metadata={"dependencies_satisfied": True}
    )
    assert system.runtime.get_task_state(tid).status == "ready"

    # ── 5. Simulate failure/restart ───────────────────────────────────
    # The whole runtime memory is serialized out of the process and a
    # fresh RuntimeStateManager instance revives from it (exercising BOTH
    # the full-state snapshot mechanism and the checkpoint restorer).
    crash_snapshot = system.runtime.create_snapshot()
    serialized = crash_snapshot.model_dump_json()  # leaves the process

    restarted = RuntimeStateManager()
    adopted = restarted.restore_snapshot(
        RuntimeSnapshot.model_validate_json(serialized)
    )
    assert adopted >= 3  # project + task + checkpoint came back

    # ── 6. Restore checkpoint into the fresh instance ─────────────────
    result = restarted.restore_checkpoint(checkpoint_id, RestoreType.FULL)
    assert result.success is True

    # ── 7. Verify state integrity ─────────────────────────────────────
    restored_project = restarted.get_project_state(pid)
    assert restored_project.status == pre_state.status
    assert restored_project.version == pre_version  # version integrity
    assert restored_project.project_id == pid  # identity integrity

    restored_task = restarted.get_task_state(tid)
    assert restored_task.status == "pending"  # rolled back to checkpoint time
    assert restored_task.version == 1

    # ── Idempotency / concurrency expectation ─────────────────────────
    # A checkpoint may only be restored once; double restore is rejected
    # instead of silently re-applying stale state.
    from autoforge_runtime.exceptions import InvalidStateError

    with pytest.raises(InvalidStateError):
        restarted.restore_checkpoint(checkpoint_id, RestoreType.FULL)
    assert restarted.get_project_state(pid).version == pre_version


async def test_checkpoint_restore_publishes_canonical_event(
    system: AutoForgeSystem,
) -> None:
    """checkpoint.restored flows through the canonical transport."""
    pid, _tid = await _seed_running_project(system)
    checkpoint_id = system.runtime.create_checkpoint(pid, CheckpointType.MANUAL)

    received: list = []
    system.events.subscribe(received.append, event_types=[EventType.CHECKPOINT_RESTORED])

    system.runtime.restore_checkpoint(checkpoint_id, RestoreType.FULL)

    # checkpoint.restored payloads aggregate by CHECKPOINT id.
    assert any(e.aggregate_id == checkpoint_id for e in received), (
        "checkpoint.restored never reached the transport observer"
    )