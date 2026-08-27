"""AutoForge composition root.

The single place where the platform's subsystems are instantiated and wired
together with real dependency injection:

    Event Platform (transport)
        -> CanonicalEventBus (adapter boundary, ADR-001)
        -> RuntimeStateManager (authoritative runtime state, ADR-002)
        -> KernelRuntimeFacade (Kernel's service ABC over the runtime)
        -> CanonicalKernelEventBus (Kernel's bus ABC over the transport)
        -> Kernel (orchestrator)

Runtime state-change callbacks are lifted into canonical domain events so
the whole system speaks ONE event vocabulary end to end.

This module intentionally contains NO business logic: it only constructs
and connects.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from autoforge_events.base import BaseEvent as DomainBaseEvent
from autoforge_events.event_types import EventCategory, EventType

from autoforge_event_platform import EventPlatform
from autoforge_event_platform.adapter import CanonicalEventBus

from autoforge_kernel.kernel import Kernel
from autoforge_kernel.request_intake import (
    DefaultIdentifierGenerator,
    DefaultProjectInitializer,
    DefaultRequestNormalizer,
    DefaultRequestValidator,
)

from autoforge_runtime import RuntimeStateManager

from autoforge_composition.event_bus_adapter import CanonicalKernelEventBus
from autoforge_composition.execution_wiring import build_execution_engine
from autoforge_composition.runtime_facade import KernelRuntimeFacade
from autoforge_composition.workflow_wiring import build_workflow_engine

from autoforge_execution.engine import ExecutionEngine
from autoforge_workflows.engine import WorkflowEngine

__all__ = ["AutoForgeSystem", "build_autoforge_system"]

# Prefix of a runtime-emitted event name -> canonical category. Runtime
# events are named "<entity>.<state>" by the StateTransitionEngine.
_CATEGORY_BY_PREFIX: dict[str, EventCategory] = {
    "project": EventCategory.PROJECT,
    "task": EventCategory.TASK,
    "checkpoint": EventCategory.CHECKPOINT,
    "loop": EventCategory.LOOP,
    "workflow": EventCategory.SYSTEM_EVENT,
    "worker": EventCategory.SYSTEM_EVENT,
    "execution": EventCategory.EXECUTION,
    "artifact": EventCategory.ARTIFACT,
    "recovery": EventCategory.FAILURE,
    "runtime": EventCategory.SERVICE,
}

# Aggregate-type label per prefix for lifted runtime events.
_AGGREGATE_BY_PREFIX = {
    "project": "Project",
    "task": "Task",
    "checkpoint": "Checkpoint",
    "workflow": "Workflow",
    "loop": "EngineeringLoop",
    "worker": "Worker",
    "execution": "ExecutionSession",
    "artifact": "Artifact",
    "recovery": "Recovery",
}


def _lift_runtime_event(payload: dict[str, Any]) -> DomainBaseEvent | None:
    """Convert a raw runtime callback payload into a canonical event.

    Returns None when the runtime emits an internal diagnostic with no
    canonical counterpart (e.g. ``snapshot.*``); those remain observable on
    ``runtime.event_publisher`` directly and are NOT silently re-typed.
    """
    raw_type = str(payload.get("event_type", ""))
    try:
        event_type = EventType(raw_type)
    except ValueError:
        return None

    prefix = raw_type.split(".", 1)[0]
    category = _CATEGORY_BY_PREFIX.get(prefix, EventCategory.SYSTEM_EVENT)

    entity_id = (
        payload.get("entity_id")
        or payload.get("project_id")
        or payload.get("task_id")
        or payload.get("checkpoint_id")
        or payload.get("runtime_id")
    )
    aggregate_id = (
        uuid.UUID(str(entity_id)) if entity_id else uuid.uuid4()
    )

    metadata = {
        k: v
        for k, v in payload.items()
        if k not in {"event_id", "event_type", "occurred_at"}
    }

    correlation_raw = payload.get("correlation_id")
    return DomainBaseEvent(
        event_type=event_type,
        event_category=category,
        aggregate_id=aggregate_id,
        aggregate_type=_AGGREGATE_BY_PREFIX.get(prefix, "Runtime"),
        correlation_id=(
            uuid.UUID(str(correlation_raw)) if correlation_raw else None
        ),
        metadata=metadata,
    )


@dataclass
class AutoForgeSystem:
    """A fully wired AutoForge foundation process."""

    kernel: Kernel
    runtime: RuntimeStateManager
    runtime_facade: KernelRuntimeFacade
    events: CanonicalEventBus
    event_platform: EventPlatform
    event_bus: CanonicalKernelEventBus
    workflow_engine: WorkflowEngine
    execution_engine: ExecutionEngine

    #: Raw runtime diagnostics that had no canonical counterpart during lift.
    skipped_runtime_events: list[dict[str, Any]]

    async def initialize(self) -> None:
        """Initialise runtime + kernel through the composed boundary."""
        self.runtime.initialize()
        self.runtime.start()
        await self.kernel.initialize()

    async def shutdown(self, reason: str = "shutdown") -> None:
        """Shut the composed system down cleanly."""
        await self.kernel.shutdown(reason)
        self.runtime.stop(reason)


def build_autoforge_system(
    *,
    kernel_version: str = "1.0.0",
    config: dict[str, Any] | None = None,
    workspace_root: str | None = None,
) -> AutoForgeSystem:
    """Construct and wire the AutoForge foundation stack.

    Every dependency is injected; no subsystem constructs another and no
    business logic lives here.
    """
    # 1. Transport infrastructure.
    platform = EventPlatform()

    # 2. Canonical event boundary over the transport.
    canonical_bus = CanonicalEventBus(
        platform.event_bus,
        default_source="autoforge-runtime",
        schema_registry=platform.schema_registry,
    )

    # 3. Authoritative runtime; its state changes become canonical events.
    skipped: list[dict[str, Any]] = []

    def _on_runtime_event(payload: dict[str, Any]) -> None:
        event = _lift_runtime_event(payload)
        if event is None:
            skipped.append(payload)
            return
        canonical_bus.publish(event)

    runtime = RuntimeStateManager(event_callback=_on_runtime_event)

    # 4. Kernel-facing adapters (dependency inversion boundary).
    facade = KernelRuntimeFacade(runtime)
    kernel_bus = CanonicalKernelEventBus(canonical_bus)

    # 5. The orchestrator, injected with everything above.
    kernel = Kernel(
        event_bus=kernel_bus,
        runtime_state_manager=facade,
        request_validator=DefaultRequestValidator(),
        request_normalizer=DefaultRequestNormalizer(),
        project_initializer=DefaultProjectInitializer(event_bus=kernel_bus),
        identifier_generator=DefaultIdentifierGenerator(),
    )

    # 6. Workflow Engine — wired with event bus and runtime for state projection.
    workflow_engine = build_workflow_engine(
        canonical_bus=canonical_bus,
        runtime=runtime,
        max_concurrent_tasks=(config or {}).get("max_concurrent_tasks", 4),
        auto_checkpoint=True,
    )

    # 7. Execution Engine — wired with environment, workflow engine, events, and runtime.
    execution_engine = build_execution_engine(
        workspace_root=workspace_root,
        canonical_bus=canonical_bus,
        runtime=runtime,
        workflow_engine=workflow_engine,
        max_concurrent_workers=(config or {}).get("max_concurrent_workers", 4),
    )

    return AutoForgeSystem(
        kernel=kernel,
        runtime=runtime,
        runtime_facade=facade,
        events=canonical_bus,
        event_platform=platform,
        event_bus=kernel_bus,
        workflow_engine=workflow_engine,
        execution_engine=execution_engine,
        skipped_runtime_events=skipped,
    )