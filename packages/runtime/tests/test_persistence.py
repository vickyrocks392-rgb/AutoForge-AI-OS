"""Tests for the durable persistence layer (Phase 18-J, step 18-J.1).

These tests validate the runtime persistence model of the Runtime State
Manager Specification v1.0 (Section 15) for the SQLite-backed implementation:

    - the cache layer, the persistent store and the history store together
    - durable round trips for every runtime state entity type
    - restart survival of state, history and schema version
    - transactions: atomic commit, rollback, nested savepoints, cache coherence
    - optimistic concurrency (``expected_version``) and row revisions
    - idempotent history replay and append-ordered history queries
    - backup, integrity/health reporting and clear semantics
    - the backward-compatible surface used by existing callers
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Iterator
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from autoforge_runtime import (
    CacheLayer,
    CheckpointState,
    CheckpointType,
    EngineeringLoopState,
    EntityType,
    HistoryStore,
    LoopType,
    PersistenceLayer,
    PersistentStore,
    ProjectState,
    RecoveryState,
    RuntimeStateManager,
    SQLiteStorage,
    TaskState,
    WorkerState,
    WorkflowState,
)
from autoforge_runtime.exceptions import (
    EntityNotFoundError,
    PersistenceError,
    VersionConflictError,
)
from autoforge_runtime.models import StateModel, StateTransition
from autoforge_runtime.persistence import entity_id_of


# ── Fixtures & helpers ───────────────────────────────────────────────────


@pytest.fixture
def layer(tmp_path: Path) -> Iterator[PersistenceLayer]:
    """Create a durable persistence layer backed by a temporary database."""
    persistence = PersistenceLayer(tmp_path / "runtime_state.sqlite3")
    yield persistence
    persistence.close()


def _project() -> ProjectState:
    """Build a project state."""
    return ProjectState(request={"name": "durable"})


def _workflow() -> WorkflowState:
    """Build a workflow state."""
    return WorkflowState(project_id=uuid.uuid4(), task_graph={"nodes": [1, 2]})


def _loop() -> EngineeringLoopState:
    """Build an engineering loop state."""
    return EngineeringLoopState(
        workflow_id=uuid.uuid4(),
        project_id=uuid.uuid4(),
        loop_type=list(LoopType)[0],
    )


def _task() -> TaskState:
    """Build a task state carrying nested metadata."""
    return TaskState(
        project_id=uuid.uuid4(),
        metadata={"title": "Implement", "nested": {"values": [1, 2, 3]}},
    )


def _worker() -> WorkerState:
    """Build a worker state."""
    return WorkerState(worker_type="codegen", capabilities=["python"])


def _checkpoint() -> CheckpointState:
    """Build a checkpoint state with a nested snapshot payload."""
    return CheckpointState(
        project_id=uuid.uuid4(),
        checkpoint_type=CheckpointType.MANUAL,
        state_snapshot={"projects": {"count": 1}},
    )


def _recovery() -> RecoveryState:
    """Build a recovery state."""
    return RecoveryState(project_id=uuid.uuid4(), error_message="boom")


#: One factory per persistable entity type.
ENTITY_FACTORIES: dict[EntityType, Callable[[], StateModel]] = {
    EntityType.PROJECT: _project,
    EntityType.WORKFLOW: _workflow,
    EntityType.LOOP: _loop,
    EntityType.TASK: _task,
    EntityType.WORKER: _worker,
    EntityType.CHECKPOINT: _checkpoint,
    EntityType.RECOVERY: _recovery,
}


def _transition(
    entity_id: uuid.UUID, from_state: str = "created", to_state: str = "planning"
) -> StateTransition:
    """Build a project transition record."""
    return StateTransition(
        entity_type=EntityType.PROJECT,
        entity_id=entity_id,
        from_state=from_state,
        to_state=to_state,
    )


# ── Durable storage ──────────────────────────────────────────────────────


class TestDurableStorage:
    """Round-trip, identity and integrity guarantees of the durable store."""

    @pytest.mark.parametrize("entity_type", list(ENTITY_FACTORIES))
    def test_state_round_trip_is_lossless(
        self, layer: PersistenceLayer, entity_type: EntityType
    ) -> None:
        """Every runtime state model survives a durable round trip."""
        state = ENTITY_FACTORIES[entity_type]()
        entity_id = entity_id_of(entity_type, state)

        layer.write_state(entity_type, entity_id, state)
        stored = layer.read_state(entity_type, entity_id)

        assert stored.model_dump() == state.model_dump()
        assert stored.model_dump_json() == state.model_dump_json()

    def test_read_all_preserves_insertion_order(self, layer: PersistenceLayer) -> None:
        """Entities come back in the order they were first written."""
        projects = [ProjectState() for _ in range(3)]
        for project in projects:
            layer.write_state(EntityType.PROJECT, project.project_id, project)

        assert [s.project_id for s in layer.read_all(EntityType.PROJECT)] == [
            p.project_id for p in projects
        ]

    def test_snapshot_store_is_keyed_by_entity_id(self, layer: PersistenceLayer) -> None:
        """``snapshot_store`` returns the {id: state} mapping snapshots need."""
        project = ProjectState()
        layer.write_state(EntityType.PROJECT, project.project_id, project)

        store = layer.snapshot_store(EntityType.PROJECT)

        assert list(store) == [project.project_id]
        assert isinstance(store[project.project_id], ProjectState)

    def test_snapshot_store_detaches_from_stored_state(self, layer: PersistenceLayer) -> None:
        """Mutating a returned snapshot copy cannot corrupt durable state."""
        project = ProjectState()
        layer.write_state(EntityType.PROJECT, project.project_id, project)

        store = layer.snapshot_store(EntityType.PROJECT)
        store[project.project_id].metadata["touched"] = True

        assert layer.read_state(EntityType.PROJECT, project.project_id).metadata == {}

    def test_read_missing_entity_raises_with_details(self, layer: PersistenceLayer) -> None:
        """Missing state raises EntityNotFoundError with structured details."""
        missing = uuid.uuid4()

        with pytest.raises(EntityNotFoundError) as excinfo:
            layer.read_state(EntityType.TASK, missing)

        assert excinfo.value.details == {"entity_id": str(missing), "entity_type": "task"}

    def test_identifier_mismatch_is_rejected(self, layer: PersistenceLayer) -> None:
        """State may not be stored under an identifier it does not carry."""
        task = TaskState(project_id=uuid.uuid4())

        with pytest.raises(PersistenceError, match="mismatch"):
            layer.write_state(EntityType.TASK, uuid.uuid4(), task)

    def test_unsupported_entity_type_is_rejected(self, layer: PersistenceLayer) -> None:
        """Entity types without a state model fail fast."""
        with pytest.raises(PersistenceError, match="Unsupported entity type"):
            layer.read_all("not-a-real-entity-type")

    def test_delete_reports_whether_a_row_existed(self, layer: PersistenceLayer) -> None:
        """Delete returns True/False and removes all traces of the entity."""
        project = ProjectState()
        layer.write_state(EntityType.PROJECT, project.project_id, project)

        assert layer.delete_state(EntityType.PROJECT, project.project_id) is True
        assert layer.delete_state(EntityType.PROJECT, project.project_id) is False
        assert layer.exists(EntityType.PROJECT, project.project_id) is False
        assert layer.count(EntityType.PROJECT) == 0


# ── Restart survival ─────────────────────────────────────────────────────


class TestRestartSurvival:
    """Durable state, history and schema survive a store restart."""

    def test_state_and_history_survive_restart(self, tmp_path: Path) -> None:
        """A fresh layer on the same file sees the committed state."""
        db_path = tmp_path / "restart.sqlite3"
        first = PersistenceLayer(db_path)
        project = ProjectState()
        first.write_state(
            EntityType.PROJECT, project.project_id, project.model_copy(update={"version": 7})
        )
        first.write_history(_transition(project.project_id))
        first.close()

        revived = PersistenceLayer(db_path)

        assert revived.is_durable is True
        assert revived.read_state(EntityType.PROJECT, project.project_id).version == 7
        assert [t.to_state for t in revived.history.read_all()] == ["planning"]
        revived.close()

    def test_durability_pragmas_and_schema_version(self, layer: PersistenceLayer) -> None:
        """File databases use WAL + synchronous=FULL and record the schema."""
        health = layer.store.health_check()

        assert health["durable"] is True
        assert health["journal_mode"] == "WAL"
        assert health["synchronous"] == "FULL"
        assert health["schema_version"] == "1"

    def test_env_var_enables_durable_default(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``AUTOFORGE_RUNTIME_STATE_DB`` switches the default to a file."""
        db_path = tmp_path / "env.sqlite3"
        monkeypatch.setenv("AUTOFORGE_RUNTIME_STATE_DB", str(db_path))

        persistence = PersistenceLayer()

        assert persistence.db_path == str(db_path)
        assert persistence.is_durable is True
        assert db_path.exists()
        persistence.close()

    def test_default_layer_is_isolated_in_memory(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Without configuration each layer owns a private volatile store."""
        monkeypatch.delenv("AUTOFORGE_RUNTIME_STATE_DB", raising=False)
        first = PersistenceLayer()
        second = PersistenceLayer()
        project = ProjectState()

        first.write_state(EntityType.PROJECT, project.project_id, project)

        assert first.db_path == ":memory:"
        assert first.is_durable is False
        assert second.count(EntityType.PROJECT) == 0

    def test_runtime_state_manager_recovers_state_after_restart(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A restarted RuntimeStateManager reads back durable state/history."""
        monkeypatch.setenv("AUTOFORGE_RUNTIME_STATE_DB", str(tmp_path / "manager.sqlite3"))
        manager = RuntimeStateManager()
        project_id = manager.create_project({"request": {"name": "restart"}})
        manager.transition_project_state(project_id, "planning")

        restarted = RuntimeStateManager()

        assert restarted.get_project_state(project_id).status.value == "planning"
        assert [
            (t.from_state, t.to_state)
            for t in restarted.get_runtime_history(EntityType.PROJECT, project_id)
        ] == [("created", "planning")]
        assert len(restarted.create_snapshot()) == 1
        assert restarted.health_check()["persistence_available"] is True

    def test_manager_accepts_an_explicit_database_path(self, tmp_path: Path) -> None:
        """``RuntimeStateManager(db_path=...)`` opts into durability directly."""
        db_path = tmp_path / "explicit.sqlite3"
        manager = RuntimeStateManager(db_path=db_path)
        project_id = manager.create_project({"request": {"name": "explicit"}})

        restarted = RuntimeStateManager(db_path=db_path)

        assert restarted.persistence.db_path == str(db_path)
        assert restarted.get_project_state(project_id).project_id == project_id


# ── Cache coherence ──────────────────────────────────────────────────────


class TestCacheCoherence:
    """The cache never exposes state the durable store does not hold."""

    def test_cache_is_populated_on_read(self, layer: PersistenceLayer) -> None:
        """A store read repopulates the cache for subsequent hits."""
        project = ProjectState()
        layer.write_state(EntityType.PROJECT, project.project_id, project)
        layer.cache.clear()

        first = layer.read_state(EntityType.PROJECT, project.project_id)
        second = layer.read_state(EntityType.PROJECT, project.project_id)

        assert first.project_id == second.project_id == project.project_id
        assert layer.cache.stats()["hits"] == 1
        assert layer.cache.stats()["entries"] == 1

    def test_cached_values_are_detached_copies(self, layer: PersistenceLayer) -> None:
        """Callers cannot mutate cached state through a returned reference."""
        project = ProjectState()
        layer.write_state(EntityType.PROJECT, project.project_id, project)

        first = layer.cache.get(EntityType.PROJECT, project.project_id)
        first.metadata["touched"] = True

        assert layer.cache.get(EntityType.PROJECT, project.project_id).metadata == {}

    def test_delete_invalidates_cache(self, layer: PersistenceLayer) -> None:
        """Deleting state removes the cached copy as well."""
        project = ProjectState()
        layer.write_state(EntityType.PROJECT, project.project_id, project)

        layer.delete_state(EntityType.PROJECT, project.project_id)

        assert layer.cache.get(EntityType.PROJECT, project.project_id) is None

    def test_invalidate_type_removes_only_that_type(self, layer: PersistenceLayer) -> None:
        """Type-scoped invalidation leaves other entity types cached."""
        project = ProjectState()
        task = TaskState(project_id=uuid.uuid4())
        layer.write_state(EntityType.PROJECT, project.project_id, project)
        layer.write_state(EntityType.TASK, task.task_id, task)

        assert layer.cache.invalidate_type(EntityType.PROJECT) == 1
        assert layer.cache.keys() == [(EntityType.TASK, task.task_id)]

    def test_rollback_discards_uncommitted_cache_entries(self, layer: PersistenceLayer) -> None:
        """A rolled-back write never survives in the cache."""
        project = ProjectState()
        layer.write_state(EntityType.PROJECT, project.project_id, project)

        with pytest.raises(RuntimeError):
            with layer.transaction():
                layer.write_state(
                    EntityType.PROJECT,
                    project.project_id,
                    project.model_copy(update={"version": 5}),
                )
                raise RuntimeError("simulated failure")

        assert layer.read_state(EntityType.PROJECT, project.project_id).version == 1
        assert layer.cache.get(EntityType.PROJECT, project.project_id).version == 1

    def test_outer_rollback_discards_committed_inner_scope(self, layer: PersistenceLayer) -> None:
        """An inner savepoint commit is still discarded by an outer rollback."""
        project = ProjectState()
        layer.write_state(EntityType.PROJECT, project.project_id, project)

        with pytest.raises(RuntimeError):
            with layer.transaction():
                layer.write_state(
                    EntityType.PROJECT,
                    project.project_id,
                    project.model_copy(update={"version": 2}),
                )
                with layer.transaction():
                    layer.write_state(
                        EntityType.PROJECT,
                        project.project_id,
                        project.model_copy(update={"version": 3}),
                    )
                raise RuntimeError("outer failure")

        assert layer.store.get_version(EntityType.PROJECT, project.project_id) == 1
        assert layer.read_state(EntityType.PROJECT, project.project_id).version == 1


# ── Transactions ─────────────────────────────────────────────────────────


class TestTransactions:
    """Explicit transactions provide atomic, rollback-safe writes."""

    def test_commit_persists_and_closes_transaction(self, layer: PersistenceLayer) -> None:
        """Committed writes are visible afterwards and the scope is closed."""
        project = ProjectState()

        with layer.transaction():
            assert layer.in_transaction is True
            assert layer.store.transaction_depth == 1
            layer.write_state(EntityType.PROJECT, project.project_id, project)

        assert layer.in_transaction is False
        assert layer.count(EntityType.PROJECT) == 1

    def test_rollback_discards_state_and_history(self, layer: PersistenceLayer) -> None:
        """A failed transaction leaves neither state nor history behind."""
        project = ProjectState()
        layer.write_state(EntityType.PROJECT, project.project_id, project)

        with pytest.raises(RuntimeError):
            with layer.transaction():
                layer.write_state(
                    EntityType.PROJECT,
                    project.project_id,
                    project.model_copy(update={"version": 4}),
                )
                layer.write_history(_transition(project.project_id))
                raise RuntimeError("failure")

        assert layer.store.get_version(EntityType.PROJECT, project.project_id) == 1
        assert layer.history.count() == 0

    def test_nested_rollback_keeps_outer_writes(self, layer: PersistenceLayer) -> None:
        """An inner savepoint rollback preserves the outer transaction."""
        project = ProjectState()
        layer.write_state(EntityType.PROJECT, project.project_id, project)

        with layer.transaction():
            layer.write_state(
                EntityType.PROJECT, project.project_id, project.model_copy(update={"version": 2})
            )
            with pytest.raises(ValueError):
                with layer.transaction():
                    layer.write_state(
                        EntityType.PROJECT,
                        project.project_id,
                        project.model_copy(update={"version": 3}),
                    )
                    raise ValueError("inner failure")

        assert layer.store.get_version(EntityType.PROJECT, project.project_id) == 2

    def test_commit_and_rollback_require_an_open_transaction(
        self, layer: PersistenceLayer
    ) -> None:
        """Committing or rolling back outside a transaction is an error."""
        with pytest.raises(PersistenceError):
            layer.store.commit()
        with pytest.raises(PersistenceError):
            layer.store.rollback()


# ── Optimistic concurrency ───────────────────────────────────────────────


class TestOptimisticConcurrency:
    """Version guards and row revisions protect against stale writes."""

    def test_stale_expected_version_is_rejected(self, layer: PersistenceLayer) -> None:
        """A write with an outdated version raises VersionConflictError."""
        project = ProjectState()
        layer.write_state(EntityType.PROJECT, project.project_id, project)

        with pytest.raises(VersionConflictError) as excinfo:
            layer.write_state(
                EntityType.PROJECT,
                project.project_id,
                project.model_copy(update={"version": 2}),
                expected_version=9,
            )

        assert excinfo.value.details["stored_version"] == 1

    def test_expected_version_rejects_missing_state(self, layer: PersistenceLayer) -> None:
        """A guarded write against absent state is a conflict, not an insert."""
        project = ProjectState()

        with pytest.raises(VersionConflictError):
            layer.write_state(
                EntityType.PROJECT, project.project_id, project, expected_version=1
            )

    def test_matching_expected_version_succeeds(self, layer: PersistenceLayer) -> None:
        """A guarded write succeeds when the version matches the store."""
        project = ProjectState()
        layer.write_state(EntityType.PROJECT, project.project_id, project)

        layer.write_state(
            EntityType.PROJECT,
            project.project_id,
            project.model_copy(update={"version": 2}),
            expected_version=1,
        )

        assert layer.get_version(EntityType.PROJECT, project.project_id) == 2

    def test_row_revision_increments_on_every_write(self, layer: PersistenceLayer) -> None:
        """Each write bumps the monotonic row revision."""
        project = ProjectState()

        assert layer.write_state(EntityType.PROJECT, project.project_id, project) == 1
        assert layer.write_state(EntityType.PROJECT, project.project_id, project) == 2
        assert layer.store.get_revision(EntityType.PROJECT, project.project_id) == 2


# ── History store ────────────────────────────────────────────────────────


class TestHistoryStore:
    """The history store is an append-only, replay-safe audit trail."""

    def test_append_and_query_by_entity(self, layer: PersistenceLayer) -> None:
        """Appended transitions round-trip losslessly."""
        entity_id = uuid.uuid4()
        transition = _transition(entity_id)

        assert layer.write_history(transition) is True
        assert [
            t.model_dump()
            for t in layer.history.read_by_entity(EntityType.PROJECT, entity_id)
        ] == [transition.model_dump()]

    def test_replay_is_idempotent(self, layer: PersistenceLayer) -> None:
        """Replaying the same transition never duplicates the audit trail."""
        transition = _transition(uuid.uuid4())

        assert layer.write_history(transition) is True
        assert layer.write_history(transition) is False
        assert layer.history.count() == 1

    def test_history_is_append_ordered(self, layer: PersistenceLayer) -> None:
        """History queries return entries in append order."""
        entity_id = uuid.uuid4()
        first = _transition(entity_id, "created", "planning")
        second = _transition(entity_id, "planning", "running")
        layer.write_history(first)
        layer.write_history(second)

        assert [t.transition_id for t in layer.history.read_all()] == [
            first.transition_id,
            second.transition_id,
        ]
        assert [
            t.transition_id for t in layer.history.read_by_entity_type(EntityType.PROJECT)
        ] == [first.transition_id, second.transition_id]

    def test_history_time_range_query(self, layer: PersistenceLayer) -> None:
        """Time-range queries select recorded transitions only."""
        layer.write_history(_transition(uuid.uuid4()))
        now = datetime.now(timezone.utc)

        assert (
            len(
                layer.history.read_between(
                    now - timedelta(minutes=5), now + timedelta(minutes=5)
                )
            )
            == 1
        )
        assert (
            layer.history.read_between(
                now + timedelta(minutes=5), now + timedelta(minutes=10)
            )
            == []
        )

    def test_clear_history_keeps_entities(self, layer: PersistenceLayer) -> None:
        """Clearing history does not touch entity state."""
        project = ProjectState()
        layer.write_state(EntityType.PROJECT, project.project_id, project)
        layer.write_history(_transition(project.project_id))

        layer.history.clear()

        assert layer.history.count() == 0
        assert layer.count(EntityType.PROJECT) == 1

    def test_standalone_history_store_owns_its_storage(self) -> None:
        """``HistoryStore()`` still works without an injected storage."""
        store = HistoryStore()
        transition = _transition(uuid.uuid4())

        store.write(transition)

        assert store.count() == 1
        assert store.read_all()[0].transition_id == transition.transition_id
        assert len(store) == 1
        store.close()


# ── Maintenance ──────────────────────────────────────────────────────────


class TestMaintenance:
    """Backup, health reporting and clear semantics."""

    def test_backup_copies_state_and_history(self, layer: PersistenceLayer, tmp_path: Path) -> None:
        """A backup is a complete, independently readable database."""
        project = ProjectState()
        layer.write_state(EntityType.PROJECT, project.project_id, project)
        layer.write_history(_transition(project.project_id))

        backup_path = layer.backup(tmp_path / "backup.sqlite3")
        restored = PersistenceLayer(backup_path)

        assert backup_path.exists()
        assert restored.count(EntityType.PROJECT) == 1
        assert restored.history.count() == 1
        restored.close()

    def test_backup_of_volatile_store_is_usable(self, tmp_path: Path) -> None:
        """An in-memory store can be snapshotted to a durable file."""
        volatile = PersistenceLayer()
        project = ProjectState()
        volatile.write_state(EntityType.PROJECT, project.project_id, project)

        path = volatile.backup(tmp_path / "snapshot.sqlite3")
        restored = PersistenceLayer(path)

        assert (
            restored.read_state(EntityType.PROJECT, project.project_id).project_id
            == project.project_id
        )
        restored.close()

    def test_health_check_reports_store_state(self, layer: PersistenceLayer) -> None:
        """Health reporting exposes integrity, counts and cache stats."""
        project = ProjectState()
        layer.write_state(EntityType.PROJECT, project.project_id, project)
        layer.write_history(_transition(project.project_id))

        health = layer.health_check()

        assert health["healthy"] is True
        assert health["readable"] is True
        assert health["integrity"] == "ok"
        assert health["entities"] == 1
        assert health["transitions"] == 1
        assert health["cache"]["entries"] == 1

    def test_clear_removes_state_history_and_cache(self, layer: PersistenceLayer) -> None:
        """Clear empties every persistence tier."""
        project = ProjectState()
        layer.write_state(EntityType.PROJECT, project.project_id, project)
        layer.write_history(_transition(project.project_id))

        layer.clear()

        assert layer.store.count(EntityType.PROJECT) == 0
        assert layer.history.count() == 0
        assert len(layer.cache) == 0


# ── Legacy surface ───────────────────────────────────────────────────────


class TestLegacySurface:
    """The pre-existing persistence API stays available to existing callers."""

    def test_persistent_store_alias_targets_sqlite_storage(self) -> None:
        """``PersistentStore`` (the documented class name) still works."""
        assert PersistentStore is SQLiteStorage
        store = PersistentStore()
        project = ProjectState()

        assert store.write(EntityType.PROJECT, project.project_id, project) == 1
        assert store.read(EntityType.PROJECT, project.project_id).project_id == project.project_id
        assert list(store.snapshot_store(EntityType.PROJECT)) == [project.project_id]
        assert store.delete(EntityType.PROJECT, project.project_id) is True
        store.close()

    def test_layer_exposes_store_cache_and_history(self, layer: PersistenceLayer) -> None:
        """The classic ``store``/``cache``/``history`` attributes remain."""
        assert isinstance(layer.store, SQLiteStorage)
        assert isinstance(layer.cache, CacheLayer)
        assert isinstance(layer.history, HistoryStore)

    def test_runtime_manager_writes_through_the_persistence_layer(self) -> None:
        """The state manager reads back what it wrote, via the layer."""
        manager = RuntimeStateManager()
        project_id = manager.create_project({"request": {"name": "legacy"}})

        state = manager.persistence.read_state(EntityType.PROJECT, project_id)

        assert state.project_id == project_id

    def test_default_runtime_manager_stays_isolated(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An unconfigured manager never adopts another run's state."""
        monkeypatch.delenv("AUTOFORGE_RUNTIME_STATE_DB", raising=False)

        assert len(RuntimeStateManager().create_snapshot()) == 0
