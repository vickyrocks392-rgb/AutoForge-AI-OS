"""
Immutable runtime snapshots for the AutoForge AI Runtime State Manager.

Snapshots provide point-in-time, immutable captures of the entire runtime
state. They capture the runtime-owned *state models* (ProjectState,
TaskState, WorkflowState, ...) — the same vocabulary owned by the
RuntimeStateManager and its PersistenceLayer — so that there is exactly ONE
snapshot mechanism and ONE state vocabulary in the runtime.

Snapshots are used for checkpoint/restore operations and for providing
consistent read-only views of the runtime state. They are memory-only;
durability across process restarts is provided by CheckpointManager
serialization.
"""

from __future__ import annotations

import copy
import uuid
from collections.abc import Mapping
from types import MappingProxyType
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_serializer

from autoforge_runtime.models import (
    CheckpointState,
    EngineeringLoopState,
    EntityType,
    ProjectState,
    RecoveryState,
    StateModel,
    TaskState,
    WorkerState,
    WorkflowState,
)

# Snapshot field name ↔ persistence entity type ↔ state-model pairing.
# Kept as an explicit table so the snapshot layout and the persistence
# layout stay in lockstep.
SNAPSHOT_STORES: tuple[tuple[str, EntityType, type[StateModel]], ...] = (
    ("projects", EntityType.PROJECT, ProjectState),
    ("workflows", EntityType.WORKFLOW, WorkflowState),
    ("loops", EntityType.LOOP, EngineeringLoopState),
    ("tasks", EntityType.TASK, TaskState),
    ("workers", EntityType.WORKER, WorkerState),
    ("checkpoints", EntityType.CHECKPOINT, CheckpointState),
    ("recoveries", EntityType.RECOVERY, RecoveryState),
)


class RuntimeSnapshot(BaseModel):
    """
    An immutable, point-in-time capture of the entire runtime state.

    Snapshots are created by the RuntimeStateManager and contain deep copies
    of all registered state entities at the moment of capture. They are fully
    immutable — the model is frozen and all collections are Mapping types to
    prevent mutation.

    Snapshots are memory-only. They are not persisted to disk by this module.
    """

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
    )

    snapshot_id: uuid.UUID = Field(
        default_factory=uuid.uuid4,
        description="Unique identifier for this snapshot.",
    )

    projects: Mapping[uuid.UUID, ProjectState] = Field(
        default_factory=dict,
        description="Snapshot of all registered project states, keyed by ID.",
    )

    workflows: Mapping[uuid.UUID, WorkflowState] = Field(
        default_factory=dict,
        description="Snapshot of all registered workflow states, keyed by ID.",
    )

    loops: Mapping[uuid.UUID, EngineeringLoopState] = Field(
        default_factory=dict,
        description="Snapshot of all engineering loop states, keyed by ID.",
    )

    tasks: Mapping[uuid.UUID, TaskState] = Field(
        default_factory=dict,
        description="Snapshot of all registered task states, keyed by ID.",
    )

    workers: Mapping[uuid.UUID, WorkerState] = Field(
        default_factory=dict,
        description="Snapshot of all worker states, keyed by ID.",
    )

    checkpoints: Mapping[uuid.UUID, CheckpointState] = Field(
        default_factory=dict,
        description="Snapshot of all checkpoint states, keyed by ID.",
    )

    recoveries: Mapping[uuid.UUID, RecoveryState] = Field(
        default_factory=dict,
        description="Snapshot of all recovery states, keyed by ID.",
    )

    def __len__(self) -> int:
        """Return the total number of entities in this snapshot."""
        return sum(len(getattr(self, field)) for field, _, _ in SNAPSHOT_STORES)

    @field_serializer(*(field for field, _, _ in SNAPSHOT_STORES))
    @staticmethod
    def _serialize_store(value: Any) -> dict[str, Any]:
        """Serialize immutable stores as plain JSON-safe dictionaries."""
        return {str(k): v for k, v in value.items()}


def _deep_freeze_mapping(data: dict[Any, Any]) -> Mapping[Any, Any]:
    """
    Create a truly immutable mapping from a dictionary of Pydantic models.

    Each value is deep-copied to ensure the snapshot is fully isolated from
    the live runtime state, and the mapping itself is wrapped in a
    ``MappingProxyType`` so item assignment/mutation is rejected.
    """
    frozen: dict[Any, Any] = {key: copy.deepcopy(value) for key, value in data.items()}
    return MappingProxyType(frozen)


def create_snapshot(stores: Mapping[str, dict[uuid.UUID, StateModel]]) -> RuntimeSnapshot:
    """
    Create an immutable snapshot from the current runtime state dictionaries.

    This function performs deep copies of all entities to ensure the snapshot
    is fully isolated from the live state. The resulting snapshot is completely
    immutable and safe to pass across async boundaries.

    The snapshot is assembled with ``model_construct`` so that the immutable
    ``MappingProxyType`` collections are preserved as-is (Pydantic field
    validation would otherwise coerce them back into mutable dicts). All
    values are already-validated ``StateModel`` instances, so skipping
    re-validation is safe.

    Args:
        stores: Mapping of store field name (e.g. ``"projects"``) to the
            corresponding entity dictionary from the runtime persistence layer.

    Returns:
        A fully immutable RuntimeSnapshot instance.
    """
    kwargs: dict[str, Any] = {}
    for field, _entity_type, _model in SNAPSHOT_STORES:
        kwargs[field] = _deep_freeze_mapping(dict(stores.get(field, {})))
    return RuntimeSnapshot.model_construct(**kwargs)


def restore_snapshot(snapshot: RuntimeSnapshot) -> dict[str, dict[uuid.UUID, StateModel]]:
    """
    Extract mutable copies of all entities from a snapshot for restoration.

    This is the inverse of :func:`create_snapshot`. It takes an immutable
    snapshot and returns mutable dictionaries keyed by store name that can be
    written back into a runtime persistence layer.

    Args:
        snapshot: The RuntimeSnapshot to restore from.

    Returns:
        A dictionary with one entry per snapshot store (e.g. ``"projects"``,
        ``"tasks"``, ...) containing a mutable dict of entities keyed by UUID.
    """
    restored: dict[str, dict[uuid.UUID, StateModel]] = {}
    for field, _entity_type, _model in SNAPSHOT_STORES:
        mapping: Mapping[uuid.UUID, Any] = getattr(snapshot, field)
        restored[field] = {k: copy.deepcopy(v) for k, v in mapping.items()}
    return restored