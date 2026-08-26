"""Persistence Layer — persists state to durable storage.

Implements the persistence model from Runtime State Manager Specification v1.0, Section 15.
"""

from __future__ import annotations

import copy
import uuid
from typing import Any

from autoforge_runtime.exceptions import EntityNotFoundError, PersistenceError
from autoforge_runtime.models import (
    CheckpointState,
    EntityType,
    ProjectState,
    RecoveryState,
    StateModel,
    StateTransition,
    TaskState,
    WorkerState,
    WorkflowState,
    EngineeringLoopState,
)


class CacheLayer:
    """In-memory cache for frequently accessed state."""

    def __init__(self) -> None:
        """Initialize the cache layer."""
        self._cache: dict[tuple[EntityType, uuid.UUID], StateModel] = {}

    def get(self, entity_type: EntityType, entity_id: uuid.UUID) -> StateModel | None:
        """Get state from cache."""
        return self._cache.get((entity_type, entity_id))

    def set(self, entity_type: EntityType, entity_id: uuid.UUID, state: StateModel) -> None:
        """Set state in cache."""
        self._cache[(entity_type, entity_id)] = state

    def invalidate(self, entity_type: EntityType, entity_id: uuid.UUID) -> None:
        """Invalidate cache entry."""
        self._cache.pop((entity_type, entity_id), None)

    def clear(self) -> None:
        """Clear the cache."""
        self._cache.clear()


class PersistentStore:
    """Durable storage for all state."""

    def __init__(self) -> None:
        """Initialize the persistent store."""
        self._projects: dict[uuid.UUID, ProjectState] = {}
        self._workflows: dict[uuid.UUID, WorkflowState] = {}
        self._loops: dict[uuid.UUID, EngineeringLoopState] = {}
        self._tasks: dict[uuid.UUID, TaskState] = {}
        self._workers: dict[uuid.UUID, WorkerState] = {}
        self._checkpoints: dict[uuid.UUID, CheckpointState] = {}
        self._recoveries: dict[uuid.UUID, RecoveryState] = {}

    def write(self, entity_type: EntityType, entity_id: uuid.UUID, state: StateModel) -> None:
        """Write state to the persistent store."""
        if entity_type == EntityType.PROJECT:
            self._projects[entity_id] = copy.deepcopy(state)  # type: ignore[assignment]
        elif entity_type == EntityType.WORKFLOW:
            self._workflows[entity_id] = copy.deepcopy(state)  # type: ignore[assignment]
        elif entity_type == EntityType.LOOP:
            self._loops[entity_id] = copy.deepcopy(state)  # type: ignore[assignment]
        elif entity_type == EntityType.TASK:
            self._tasks[entity_id] = copy.deepcopy(state)  # type: ignore[assignment]
        elif entity_type == EntityType.WORKER:
            self._workers[entity_id] = copy.deepcopy(state)  # type: ignore[assignment]
        elif entity_type == EntityType.CHECKPOINT:
            self._checkpoints[entity_id] = copy.deepcopy(state)  # type: ignore[assignment]
        elif entity_type == EntityType.RECOVERY:
            self._recoveries[entity_id] = copy.deepcopy(state)  # type: ignore[assignment]
        else:
            raise PersistenceError(f"Unsupported entity type: {entity_type.value}")

    def read(self, entity_type: EntityType, entity_id: uuid.UUID) -> StateModel:
        """Read state from the persistent store."""
        store = self._get_store(entity_type)
        if entity_id not in store:
            raise EntityNotFoundError(
                f"{entity_type.value.capitalize()} with ID {entity_id} not found",
                details={"entity_id": str(entity_id), "entity_type": entity_type.value},
            )
        return copy.deepcopy(store[entity_id])

    def read_all(self, entity_type: EntityType) -> list[StateModel]:
        """Read all states of a given type."""
        store = self._get_store(entity_type)
        return [copy.deepcopy(s) for s in store.values()]

    def delete(self, entity_type: EntityType, entity_id: uuid.UUID) -> None:
        """Delete state from the persistent store."""
        store = self._get_store(entity_type)
        store.pop(entity_id, None)

    def snapshot_store(self, entity_type: EntityType) -> dict[uuid.UUID, StateModel]:
        """Return a shallow copy of one entity store, keyed by entity ID."""
        return dict(self._get_store(entity_type))

    def _get_store(self, entity_type: EntityType) -> dict[uuid.UUID, StateModel]:
        """Get the store for an entity type."""
        if entity_type == EntityType.PROJECT:
            return self._projects  # type: ignore[return-value]
        if entity_type == EntityType.WORKFLOW:
            return self._workflows  # type: ignore[return-value]
        if entity_type == EntityType.LOOP:
            return self._loops  # type: ignore[return-value]
        if entity_type == EntityType.TASK:
            return self._tasks  # type: ignore[return-value]
        if entity_type == EntityType.WORKER:
            return self._workers  # type: ignore[return-value]
        if entity_type == EntityType.CHECKPOINT:
            return self._checkpoints  # type: ignore[return-value]
        if entity_type == EntityType.RECOVERY:
            return self._recoveries  # type: ignore[return-value]
        raise PersistenceError(f"Unsupported entity type: {entity_type.value}")


class HistoryStore:
    """Stores complete state transition history."""

    def __init__(self) -> None:
        """Initialize the history store."""
        self._transitions: list[StateTransition] = []

    def write(self, transition: StateTransition) -> None:
        """Write a transition to the history store."""
        self._transitions.append(transition)

    def read_all(self) -> list[StateTransition]:
        """Read all transitions."""
        return list(self._transitions)

    def read_by_entity(self, entity_type: EntityType, entity_id: uuid.UUID) -> list[StateTransition]:
        """Read transitions for a specific entity."""
        return [
            t for t in self._transitions
            if t.entity_type == entity_type and t.entity_id == entity_id
        ]

    def read_by_entity_type(self, entity_type: EntityType) -> list[StateTransition]:
        """Read transitions for a specific entity type."""
        return [t for t in self._transitions if t.entity_type == entity_type]

    def clear(self) -> None:
        """Clear the history store."""
        self._transitions.clear()


class PersistenceLayer:
    """Coordinates persistence operations across cache, store, and history."""

    def __init__(self) -> None:
        """Initialize the persistence layer."""
        self.cache = CacheLayer()
        self.store = PersistentStore()
        self.history = HistoryStore()

    def write_state(self, entity_type: EntityType, entity_id: uuid.UUID, state: StateModel) -> None:
        """Write state to persistent storage and update cache."""
        self.store.write(entity_type, entity_id, state)
        self.cache.set(entity_type, entity_id, state)

    def read_state(self, entity_type: EntityType, entity_id: uuid.UUID) -> StateModel:
        """Read state, checking cache first then persistent store."""
        cached = self.cache.get(entity_type, entity_id)
        if cached is not None:
            return copy.deepcopy(cached)
        state = self.store.read(entity_type, entity_id)
        self.cache.set(entity_type, entity_id, state)
        return state

    def read_all(self, entity_type: EntityType) -> list[StateModel]:
        """Read all states of a given type."""
        return self.store.read_all(entity_type)

    def delete_state(self, entity_type: EntityType, entity_id: uuid.UUID) -> None:
        """Delete state from store and invalidate cache."""
        self.store.delete(entity_type, entity_id)
        self.cache.invalidate(entity_type, entity_id)

    def write_history(self, transition: StateTransition) -> None:
        """Write a transition to the history store."""
        self.history.write(transition)

    def write_checkpoint(self, checkpoint: CheckpointState) -> None:
        """Write a checkpoint to the persistent store."""
        self.store.write(EntityType.CHECKPOINT, checkpoint.checkpoint_id, checkpoint)
        self.cache.set(EntityType.CHECKPOINT, checkpoint.checkpoint_id, checkpoint)

    def snapshot_store(self, entity_type: EntityType) -> dict[uuid.UUID, StateModel]:
        """Return a shallow copy of one persistent store, keyed by entity ID."""
        return self.store.snapshot_store(entity_type)

    def clear(self) -> None:
        """Clear all persistence data."""
        self.cache.clear()
        self.history.clear()