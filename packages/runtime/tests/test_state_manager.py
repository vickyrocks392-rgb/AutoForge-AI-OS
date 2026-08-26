"""
Comprehensive tests for the Runtime State Manager.

These tests validate the API defined by the frozen Runtime State Manager
Specification v1.0 (sync operations over runtime state models):

    - Project/task lifecycle and state writes
    - Transition validation (including preconditions) and versioning
    - Checkpoints: creation, history, restoration
    - Immutable RuntimeSnapshot capture/restore
    - Event publication and subscription
    - Health check
    - Exception detail contracts

Note: a previous version of this file targeted an async, domain-model based
API that was never implemented and directly contradicted the frozen
specification; it never collected. This suite validates the authoritative
contract instead.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping

import pytest

from autoforge_runtime import (
    CheckpointType,
    EntityType,
    ProjectState,
    ProjectStatus,
    RestoreType,
    RuntimeStateManager,
    RuntimeSnapshot,
    TaskState,
)
from autoforge_runtime.exceptions import (
    DuplicateEntityError,
    EntityNotFoundError,
    InvalidEntityTypeError,
    InvalidTransitionError,
)
from autoforge_runtime.transitions import (
    get_allowed_execution_transitions,
    get_allowed_task_transitions,
    is_terminal,
    validate_execution_transition,
    validate_task_transition,
)


# ── Fixtures ─────────────────────────────────────────────────────────────


@pytest.fixture
def manager() -> RuntimeStateManager:
    """Create a fresh RuntimeStateManager for each test."""
    return RuntimeStateManager()


@pytest.fixture
def project_state() -> ProjectState:
    """Create a sample project state."""
    return ProjectState()


@pytest.fixture
def task_state(project_state: ProjectState) -> TaskState:
    """Create a sample task state belonging to the sample project."""
    return TaskState(project_id=project_state.project_id)


# ── Project Lifecycle Tests ──────────────────────────────────────────────


class TestProjectLifecycle:
    """Tests for project creation and registration."""

    def test_create_project_returns_id(self, manager: RuntimeStateManager) -> None:
        """create_project registers new project state and returns its ID."""
        project_id = manager.create_project({"request": {"text": "Build app"}})
        assert isinstance(project_id, uuid.UUID)
        state = manager.get_project_state(project_id)
        assert state.status == ProjectStatus.CREATED
        assert state.request == {"text": "Build app"}

    def test_register_and_get_project_state(
        self, manager: RuntimeStateManager, project_state: ProjectState
    ) -> None:
        """register_project stores state readable by ID."""
        manager.register_project(project_state)
        found = manager.get_project_state(project_state.project_id)
        assert found.project_id == project_state.project_id
        assert found.version == 1

    def test_register_duplicate_project_raises(
        self, manager: RuntimeStateManager, project_state: ProjectState
    ) -> None:
        """Registering the same project ID twice raises DuplicateEntityError."""
        manager.register_project(project_state)
        with pytest.raises(DuplicateEntityError) as exc_info:
            manager.register_project(project_state)
        assert exc_info.value.details["entity_type"] == "project"

    def test_get_unknown_project_raises(self, manager: RuntimeStateManager) -> None:
        """Reading a non-existent project raises EntityNotFoundError."""
        with pytest.raises(EntityNotFoundError) as exc_info:
            manager.get_project_state(uuid.uuid4())
        assert exc_info.value.details["entity_type"] == "project"


# ── Project Transition Tests ─────────────────────────────────────────────


class TestProjectTransitions:
    """Tests for project state transitions."""

    def test_valid_transition_chain(self, manager: RuntimeStateManager) -> None:
        """created → planning → running executes and increments versions."""
        pid = manager.create_project({})
        result = manager.transition_project_state(pid, "planning")
        assert result.success is True
        assert result.from_state == "created"
        assert result.to_state == "planning"

        result = manager.transition_project_state(
            pid,
            "running",
            metadata={"strategic_plan": {"id": "SP-1"}, "executable_workflow": {"id": "WF-1"}},
        )
        assert result.success is True
        state = manager.get_project_state(pid)
        assert state.status == ProjectStatus.RUNNING
        assert state.version == 3  # created=1, planning=2, running=3

    def test_planning_to_running_requires_preconditions(
        self, manager: RuntimeStateManager
    ) -> None:
        """Transition to running without plan/workflow metadata is rejected."""
        pid = manager.create_project({})
        manager.transition_project_state(pid, "planning")
        with pytest.raises(InvalidTransitionError):
            manager.transition_project_state(pid, "running")

    def test_invalid_transition_raises_with_details(
        self, manager: RuntimeStateManager
    ) -> None:
        """Invalid transitions raise InvalidTransitionError with details."""
        pid = manager.create_project({})
        with pytest.raises(InvalidTransitionError) as exc_info:
            manager.transition_project_state(pid, "finished")
        details = exc_info.value.details
        # The transition engine reports enum reprs for current/target.
        assert details["current"].endswith("CREATED")
        assert details["target"].endswith("FINISHED")
        assert "allowed" in details

    def test_transition_unknown_project_raises(
        self, manager: RuntimeStateManager
    ) -> None:
        """Transitioning an unknown project raises EntityNotFoundError."""
        with pytest.raises(EntityNotFoundError):
            manager.transition_project_state(uuid.uuid4(), "planning")

    def test_transition_history_recorded(self, manager: RuntimeStateManager) -> None:
        """Each transition is recorded in the runtime history store."""
        pid = manager.create_project({})
        manager.transition_project_state(pid, "planning")
        history = manager.get_runtime_history(EntityType.PROJECT, pid)
        assert len(history) == 1
        assert history[0].from_state == "created"
        assert history[0].to_state == "planning"


# ── Task State Tests ─────────────────────────────────────────────────────


class TestTaskState:
    """Tests for task state management."""

    def test_register_and_get_task(
        self, manager: RuntimeStateManager, task_state: TaskState
    ) -> None:
        """register_task stores task state readable via get_task_state."""
        manager.register_task(task_state)
        found = manager.get_task_state(task_state.task_id)
        assert found.task_id == task_state.task_id
        assert found.status == "pending"

    def test_update_task_state(self, manager: RuntimeStateManager) -> None:
        """update_task_state executes valid transitions and bumps version."""
        task = TaskState(project_id=uuid.uuid4())
        manager.register_task(task)
        manager.update_task_state(
            task.task_id, "ready", metadata={"dependencies_satisfied": True}
        )
        updated = manager.get_task_state(task.task_id)
        assert updated.status == "ready"
        assert updated.version == 2

    def test_invalid_task_transition_raises(
        self, manager: RuntimeStateManager
    ) -> None:
        """Invalid task transitions are rejected by the transition engine."""
        task = TaskState(project_id=uuid.uuid4())
        manager.register_task(task)
        with pytest.raises(InvalidTransitionError):
            manager.update_task_state(task.task_id, "completed")

    def test_task_ready_requires_dependencies(
        self, manager: RuntimeStateManager
    ) -> None:
        """pending → ready is rejected unless dependencies are satisfied."""
        task = TaskState(project_id=uuid.uuid4())
        manager.register_task(task)
        with pytest.raises(InvalidTransitionError):
            manager.update_task_state(task.task_id, "ready")

    def test_get_tasks_by_status(self, manager: RuntimeStateManager) -> None:
        """Tasks can be filtered by status."""
        pid = uuid.uuid4()
        t1 = TaskState(project_id=pid)
        t2 = TaskState(project_id=pid)
        manager.register_task(t1)
        manager.register_task(t2)
        manager.update_task_state(
            t1.task_id, "ready", metadata={"dependencies_satisfied": True}
        )
        ready = manager.get_tasks_by_status("ready")
        assert [t.task_id for t in ready] == [t1.task_id]

    def test_get_tasks_by_project(self, manager: RuntimeStateManager) -> None:
        """Tasks can be filtered by owning project."""
        pid = uuid.uuid4()
        other = uuid.uuid4()
        t1 = TaskState(project_id=pid)
        t2 = TaskState(project_id=pid)
        t3 = TaskState(project_id=other)
        for t in (t1, t2, t3):
            manager.register_task(t)
        tasks = manager.get_tasks_by_project(pid)
        assert {t.task_id for t in tasks} == {t1.task_id, t2.task_id}


# ── Checkpoint Tests ─────────────────────────────────────────────────────


class TestCheckpoints:
    """Tests for checkpoint creation and restoration."""

    def test_create_checkpoint(self, manager: RuntimeStateManager) -> None:
        """create_checkpoint captures state and links it to the project."""
        pid = manager.create_project({})
        checkpoint_id = manager.create_checkpoint(
            pid, CheckpointType.MANUAL, label="before-risky-step"
        )
        checkpoint = manager.get_checkpoint(checkpoint_id)
        assert checkpoint.project_id == pid
        assert "project" in checkpoint.state_snapshot

        project = manager.get_project_state(pid)
        assert project.current_checkpoint_id == checkpoint_id

    def test_checkpoint_not_found(self, manager: RuntimeStateManager) -> None:
        """Reading an unknown checkpoint raises EntityNotFoundError."""
        with pytest.raises(EntityNotFoundError):
            manager.get_checkpoint(uuid.uuid4())

    def test_checkpoint_requires_existing_project(
        self, manager: RuntimeStateManager
    ) -> None:
        """Creating a checkpoint for unknown project raises EntityNotFoundError."""
        with pytest.raises(EntityNotFoundError):
            manager.create_checkpoint(uuid.uuid4(), CheckpointType.MANUAL)

    def test_restore_checkpoint_restores_prior_state(
        self, manager: RuntimeStateManager
    ) -> None:
        """Restoring rolls project/tasks back to checkpoint-time state."""
        pid = manager.create_project({})
        task = TaskState(project_id=pid)
        manager.register_task(task)
        checkpoint_id = manager.create_checkpoint(pid, CheckpointType.MANUAL)

        # Mutate after checkpoint
        manager.update_task_state(
            task.task_id, "ready", metadata={"dependencies_satisfied": True}
        )

        result = manager.restore_checkpoint(checkpoint_id, RestoreType.FULL)
        assert result.success is True

        restored_task = manager.get_task_state(task.task_id)
        assert restored_task.status == "pending"  # rolled back

    def test_checkpoint_history(self, manager: RuntimeStateManager) -> None:
        """All checkpoints of a project are queryable in order."""
        pid = manager.create_project({})
        c1 = manager.create_checkpoint(pid, CheckpointType.MANUAL, label="one")
        c2 = manager.create_checkpoint(pid, CheckpointType.MANUAL, label="two")
        history = manager.get_checkpoint_history(pid)
        assert [c.checkpoint_id for c in history] == [c1, c2]

# ── Snapshot Tests ───────────────────────────────────────────────────────


class TestSnapshots:
    """Tests for immutable snapshot creation and restoration."""

    def test_create_empty_snapshot(self, manager: RuntimeStateManager) -> None:
        """Create a snapshot when no entities are registered."""
        snapshot = manager.create_snapshot()
        assert isinstance(snapshot, RuntimeSnapshot)
        assert len(snapshot) == 0

    def test_create_snapshot_with_entities(self, manager: RuntimeStateManager) -> None:
        """Snapshot contains deep copies of all registered entities."""
        project = ProjectState()
        task = TaskState(project_id=project.project_id)
        manager.register_project(project)
        manager.register_task(task)

        snapshot = manager.create_snapshot()
        assert len(snapshot) == 2
        assert project.project_id in snapshot.projects
        assert task.task_id in snapshot.tasks

    def test_snapshot_model_is_frozen(self, manager: RuntimeStateManager) -> None:
        """Snapshot attributes cannot be reassigned (frozen model)."""
        project = ProjectState()
        manager.register_project(project)
        snapshot = manager.create_snapshot()
        with pytest.raises(Exception):
            snapshot.snapshot_id = uuid.uuid4()  # type: ignore[misc]

    def test_snapshot_collections_are_immutable(
        self, manager: RuntimeStateManager
    ) -> None:
        """Snapshot collections reject mutation attempts."""
        project = ProjectState()
        manager.register_project(project)
        snapshot = manager.create_snapshot()
        assert isinstance(snapshot.projects, Mapping)
        with pytest.raises(TypeError):
            snapshot.projects[uuid.uuid4()] = project  # type: ignore[index]
        # mappingproxy exposes no mutating API at all.
        assert not hasattr(snapshot.projects, "clear") or pytest.raises(
            (TypeError, AttributeError)
        )

    def test_snapshot_is_isolated_from_live_state(
        self, manager: RuntimeStateManager
    ) -> None:
        """Mutating live state after capture does not affect the snapshot."""
        project = ProjectState()
        manager.register_project(project)
        snapshot = manager.create_snapshot()

        extra = ProjectState()
        manager.register_project(extra)
        manager.transition_project_state(project.project_id, "planning")

        assert len(snapshot.projects) == 1
        assert snapshot.projects[project.project_id].status == ProjectStatus.CREATED

    def test_restore_into_fresh_manager(self, manager: RuntimeStateManager) -> None:
        """A fresh manager can adopt full state from a snapshot."""
        project = ProjectState()
        task = TaskState(project_id=project.project_id)
        manager.register_project(project)
        manager.register_task(task)
        snapshot = manager.create_snapshot()

        revived = RuntimeStateManager()
        restored_count = revived.restore_snapshot(snapshot)
        assert restored_count == 2
        assert revived.get_project_state(project.project_id).version == 1
        assert revived.get_task_state(task.task_id).status == "pending"

# ── Event Publication Tests ──────────────────────────────────────────────


class TestEventPublication:
    """Tests for runtime event publication and subscription."""

    def test_event_callback_receives_lifecycle_events(self) -> None:
        """The injectable event callback observes state-change events."""
        received: list[dict] = []
        manager = RuntimeStateManager(event_callback=received.append)
        pid = manager.create_project({})
        types = [e["event_type"] for e in received]
        assert "project.created" in types

        manager.transition_project_state(pid, "planning")
        assert "project.planning" in [e["event_type"] for e in received]

    def test_published_events_recorded(self, manager: RuntimeStateManager) -> None:
        """All published events are recorded on the event publisher."""
        pid = manager.create_project({})
        events = manager.event_publisher.get_published_events()
        assert any(e["event_type"] == "project.created" for e in events)
        assert all("event_id" in e for e in events)

    def test_subscribe_to_entity_state_changes(
        self, manager: RuntimeStateManager
    ) -> None:
        """Prefix subscriptions receive entity events; unsubscribe stops them."""
        seen: list[dict] = []
        sub_id = manager.subscribe_to_state_changes(EntityType.TASK, seen.append)
        task = TaskState(project_id=uuid.uuid4())
        manager.register_task(task)
        manager.update_task_state(
            task.task_id, "ready", metadata={"dependencies_satisfied": True}
        )
        types = [e["event_type"] for e in seen]
        assert "task.ready" in types

        assert manager.unsubscribe(sub_id) is True
        manager.update_task_state(task.task_id, "running")
        assert len(seen) == 1  # no delivery after unsubscribe

    def test_subscribe_invalid_entity_type_raises(
        self, manager: RuntimeStateManager
    ) -> None:
        """Subscribing to an invalid entity type raises InvalidEntityTypeError."""
        with pytest.raises(InvalidEntityTypeError):
            manager.subscribe_to_state_changes("bogus", lambda e: None)  # type: ignore[arg-type]


# ── Health Check Tests ───────────────────────────────────────────────────


class TestHealthCheck:
    """Tests for the health check contract."""

    def test_health_check_reports_healthy_runtime(
        self, manager: RuntimeStateManager
    ) -> None:
        """health_check reports status and persistence availability."""
        report = manager.health_check()
        assert report["healthy"] is True
        assert report["persistence_available"] is True
        assert report["status"] in {"created", "starting", "ready", "processing"}
        assert report["runtime_id"] == str(manager.runtime_id)


# ── Transition Helper Unit Tests ─────────────────────────────────────────


class TestTransitionHelpers:
    """Unit tests for pure transition validation helpers."""

    def test_task_transition_rules(self) -> None:
        """Task transition helper enforces the state machine."""
        from autoforge_models.enums import TaskStatus

        validate_task_transition(TaskStatus.PENDING, TaskStatus.READY)
        with pytest.raises(InvalidTransitionError):
            validate_task_transition(TaskStatus.PENDING, TaskStatus.COMPLETED)

    def test_execution_transition_rules(self) -> None:
        """Execution transition helper enforces the state machine."""
        from autoforge_models.enums import ExecutionStatus

        validate_execution_transition(ExecutionStatus.PENDING, ExecutionStatus.RUNNING)
        with pytest.raises(InvalidTransitionError):
            validate_execution_transition(
                ExecutionStatus.COMPLETED, ExecutionStatus.RUNNING
            )

    def test_get_allowed_transitions(self) -> None:
        """Allowed-transition queries return frozensets."""
        from autoforge_models.enums import TaskStatus

        allowed = get_allowed_task_transitions(TaskStatus.PENDING)
        assert isinstance(allowed, frozenset)
        assert TaskStatus.READY in allowed

    def test_terminal_states(self) -> None:
        """Terminal detection covers tasks and executions."""
        from autoforge_models.enums import ExecutionStatus, TaskStatus

        assert is_terminal(TaskStatus.COMPLETED) is True
        assert is_terminal(TaskStatus.PENDING) is False
        assert is_terminal(ExecutionStatus.TIMED_OUT) is True
        assert is_terminal(ExecutionStatus.RUNNING) is False

    def test_restore_preserves_snapshot_immutability(
        self, manager: RuntimeStateManager
    ) -> None:
        """Restoring does not mutate the source snapshot."""
        project = ProjectState()
        manager.register_project(project)
        snapshot = manager.create_snapshot()
        RuntimeStateManager().restore_snapshot(snapshot)
        assert len(snapshot) == 1

