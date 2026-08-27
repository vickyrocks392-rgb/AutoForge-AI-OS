"""
Workflow Engine wiring — Phase 9.

Provides:
- ``WorkflowEngineRuntimeFacade``: bridges WorkflowEngine → RuntimeStateManager.
- ``WorkflowEngineEventSink``: bridges WorkflowEngine → CanonicalEventBus.
- ``build_workflow_engine()``: factory that wires both bridges and returns a
  fully configured ``WorkflowEngine`` ready for injection into AutoForgeSystem.

Design rationale
----------------
The WorkflowEngine is designed to be self-contained (useful for testing) but
can optionally receive:

1. An ``event_sink`` to publish canonical events via the existing event bus.
2. A ``runtime_facade`` to record workflow/task state into the Runtime.

This module provides production implementations of both protocols, using the
existing composition infrastructure rather than introducing new dependencies.

Neither bridge introduces business logic — they are pure adapters.

Phase 10 note
-------------
When Phase 10 (Engineering Workers / Execution Engine) is implemented, it will
register itself as a dispatcher consumer of ``WorkflowEngine.tick()`` dispatch
lists.  The wiring for that belongs in a Phase 10 wiring module, not here.
"""

from __future__ import annotations

import uuid
from typing import Any

from autoforge_event_platform.adapter import CanonicalEventBus
from autoforge_events.base import BaseEvent
from autoforge_events.event_types import EventCategory, EventType
from autoforge_runtime import RuntimeStateManager

from autoforge_workflows.engine import WorkflowEngine, WorkflowEngineConfig
from autoforge_workflows.scheduler import SchedulerConfig

__all__ = [
    "WorkflowEngineEventSink",
    "WorkflowEngineRuntimeFacade",
    "build_workflow_engine",
]


class WorkflowEngineEventSink:
    """
    Bridges ``WorkflowEngine`` canonical events to the platform's
    ``CanonicalEventBus``.

    The engine emits events as ``BaseEvent`` objects constructed from the
    existing frozen event vocabulary.  This sink simply forwards them.

    Event sink failures MUST NOT propagate to the engine — the engine's
    internal try/except already catches exceptions, but this class adds
    an additional safety layer.
    """

    def __init__(self, event_bus: CanonicalEventBus) -> None:
        self._bus = event_bus

    def publish(self, event: Any) -> None:
        """Forward a workflow engine event to the canonical event bus."""
        try:
            if isinstance(event, BaseEvent):
                self._bus.publish(event)
        except Exception:
            # Intentionally swallowed — event bus failures must never
            # break workflow orchestration.
            pass


class WorkflowEngineRuntimeFacade:
    """
    Bridges ``WorkflowEngine`` state projections to the ``RuntimeStateManager``.

    When the WorkflowEngine advances a workflow or task, it calls
    ``record_workflow_state`` / ``record_task_state`` on this facade.
    The facade translates that into Runtime checkpointing calls so that
    Runtime remains the authoritative state store.

    In Phase 9, this uses Runtime's checkpoint mechanism to store
    workflow snapshots.  Phase 10 can extend this to create and update
    Runtime ``Task`` entities directly.
    """

    def __init__(self, runtime: RuntimeStateManager) -> None:
        self._runtime = runtime

    def record_workflow_state(
        self,
        workflow_id: uuid.UUID,
        state: dict[str, Any],
    ) -> None:
        """
        Record workflow-level state into the Runtime checkpoint store.

        Args:
            workflow_id: The workflow UUID.
            state: State dictionary (from WorkflowSnapshot.to_dict()).
        """
        try:
            checkpoint_id = str(workflow_id)
            # Use Runtime's checkpoint mechanism as a KV store.
            # CheckpointManager.store() accepts an entity_id + state dict.
            if hasattr(self._runtime, "checkpoint_manager"):
                self._runtime.checkpoint_manager.store(
                    entity_id=checkpoint_id,
                    state_snapshot=state,
                    checkpoint_type="workflow",
                )
        except Exception:
            # Never let Runtime storage failures break the workflow engine.
            pass

    def record_task_state(
        self,
        task_id: str,
        state: dict[str, Any],
    ) -> None:
        """
        Record task-level state into the Runtime.

        In Phase 9 this is a no-op if the Runtime doesn't have a
        direct task state API accessible from the snapshot.
        Phase 10 will extend this to create/update Runtime Task entities.

        Args:
            task_id: The task ID.
            state: Task state snapshot.
        """
        # Phase 10 extension point.
        # Currently a no-op because Phase 9 doesn't create Runtime Task
        # entities — that is Phase 10's responsibility.
        pass


def build_workflow_engine(
    *,
    canonical_bus: CanonicalEventBus | None = None,
    runtime: RuntimeStateManager | None = None,
    max_concurrent_tasks: int = 4,
    auto_checkpoint: bool = True,
) -> WorkflowEngine:
    """
    Construct and wire a ``WorkflowEngine`` for production use.

    Args:
        canonical_bus: If provided, workflow lifecycle events are published
            to the canonical event bus.
        runtime: If provided, workflow/task state is projected into the
            Runtime checkpoint store.
        max_concurrent_tasks: Default concurrency limit for the scheduler.
        auto_checkpoint: Whether to auto-snapshot on every state change.

    Returns:
        A fully wired and configured ``WorkflowEngine``.
    """
    event_sink = WorkflowEngineEventSink(canonical_bus) if canonical_bus else None
    runtime_facade = WorkflowEngineRuntimeFacade(runtime) if runtime else None

    config = WorkflowEngineConfig(
        scheduler_config=SchedulerConfig(
            global_max_concurrent=max_concurrent_tasks,
        ),
        auto_checkpoint=auto_checkpoint,
        # No dict-based checkpoint store in production — the Runtime facade
        # handles persistence via Runtime's own checkpoint mechanism.
        checkpoint_store=None,
    )

    return WorkflowEngine(
        config=config,
        event_sink=event_sink,
        runtime_facade=runtime_facade,
    )
