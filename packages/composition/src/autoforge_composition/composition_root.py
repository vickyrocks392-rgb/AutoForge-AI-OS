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

import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path
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
from autoforge_runtime.artifact_catalog import DurableArtifactCatalog
from autoforge_runtime.physical_artifact_store import PhysicalArtifactStore
from autoforge_artifacts.durable_bridge import DurableArtifactStoreBridge

from autoforge_composition.ai_infrastructure_wiring import (
    bind_default_provider_adapters,
    build_ai_infrastructure,
)
from autoforge_composition.artifact_wiring import build_artifact_platform_from_bus
from autoforge_composition.event_bus_adapter import CanonicalKernelEventBus
from autoforge_composition.execution_wiring import build_execution_engine
from autoforge_composition.runtime_facade import KernelRuntimeFacade
from autoforge_composition.security_wiring import build_security_platform_from_bus
from autoforge_composition.workflow_wiring import build_workflow_engine

from autoforge_execution.engine import ExecutionEngine
from autoforge_artifacts.engine import ArtifactPlatformServices
from autoforge_security.engine import SecurityPlatform
from autoforge_workflows.engine import WorkflowEngine
from autoforge_review.engine import ReviewEngine as ConcreteReviewEngine

from autoforge_kernel.strategic_engine import DefaultStrategicEngine
from autoforge_kernel.intent_analysis import DefaultIntentAnalyzer
from autoforge_kernel.planning_coordination import DefaultPlanningCoordinator
from autoforge_kernel.orchestration import DefaultOrchestrationEngine
from autoforge_kernel.infrastructure import DefaultInfrastructureCoordinator
from autoforge_kernel.completion import DefaultCompletionModule
from autoforge_kernel.approval import DefaultApprovalCoordinator
from autoforge_kernel.recovery import DefaultRecoveryCoordinator
from autoforge_kernel.learning_engine import EngineeringLearningEngine
from autoforge_execution.context_builder import EngineeringContextBuilder

from autoforge_composition.kernel_adapters import (
    KernelWorkflowEngineAdapter,
    KernelExecutionEngineAdapter,
    KernelReviewEngineAdapter,
    KernelModelRouterAdapter,
    KernelMemoryEngineAdapter,
    KernelKnowledgeEngineAdapter,
)

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
    artifact_platform: ArtifactPlatformServices
    security_platform: SecurityPlatform | None = None
    review_engine: ConcreteReviewEngine | None = None
    strategic_engine: DefaultStrategicEngine | None = None
    context_builder: EngineeringContextBuilder | None = None
    learning_engine: EngineeringLearningEngine | None = None
    planning_coordinator: DefaultPlanningCoordinator | None = None
    orchestration_engine: DefaultOrchestrationEngine | None = None
    completion_module: DefaultCompletionModule | None = None
    infrastructure_coordinator: DefaultInfrastructureCoordinator | None = None
    recovery_coordinator: DefaultRecoveryCoordinator | None = None
    approval_coordinator: DefaultApprovalCoordinator | None = None
    durable_catalog: DurableArtifactCatalog | None = None
    physical_store: PhysicalArtifactStore | None = None
    artifact_bridge: DurableArtifactStoreBridge | None = None

    #: Raw runtime diagnostics that had no canonical counterpart during lift.
    skipped_runtime_events: list[dict[str, Any]] = None

    def __post_init__(self) -> None:
        if self.skipped_runtime_events is None:
            self.skipped_runtime_events = []

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
    root_dir = Path(workspace_root) if workspace_root else Path(tempfile.mkdtemp(prefix="autoforge_ws_"))
    root_dir.mkdir(parents=True, exist_ok=True)
    db_path = (config or {}).get("db_path")
    if db_path is None and workspace_root:
        db_file = root_dir / ".autoforge" / "runtime_state.db"
        db_file.parent.mkdir(parents=True, exist_ok=True)
        db_path = db_file

    skipped: list[dict[str, Any]] = []

    def _on_runtime_event(payload: dict[str, Any]) -> None:
        event = _lift_runtime_event(payload)
        if event is None:
            skipped.append(payload)
            return
        canonical_bus.publish(event)

    runtime = RuntimeStateManager(event_callback=_on_runtime_event, db_path=db_path)

    # 3b. Authoritative Durable Artifact Infrastructure (Phase 18-K Canonical Wiring)
    artifact_root = root_dir / "artifacts"
    staging_root = artifact_root / ".staging"
    quarantine_root = artifact_root / ".quarantine"

    physical_store = PhysicalArtifactStore(
        artifact_root=artifact_root,
        staging_root=staging_root,
        quarantine_root=quarantine_root,
    )
    durable_catalog = DurableArtifactCatalog(
        persistence=runtime.persistence,
        physical_store=physical_store,
    )
    durable_bridge = DurableArtifactStoreBridge(
        catalog=durable_catalog,
        physical_store=physical_store,
    )

    # 4. Kernel-facing adapters (dependency inversion boundary).
    facade = KernelRuntimeFacade(runtime)
    kernel_bus = CanonicalKernelEventBus(canonical_bus)
    kernel_memory_engine = KernelMemoryEngineAdapter(runtime=runtime)
    kernel_knowledge_engine = KernelKnowledgeEngineAdapter()

    # 4b. Context Builder & Learning Engine (Phase 18-K Canonical Wiring).
    context_builder = EngineeringContextBuilder(
        runtime=runtime,
        memory_engine=kernel_memory_engine,
        knowledge_engine=kernel_knowledge_engine,
    )
    learning_engine = EngineeringLearningEngine(
        memory_engine=kernel_memory_engine,
        knowledge_engine=kernel_knowledge_engine,
        event_bus=kernel_bus,
        runtime=runtime,
    )

    # 5. Workflow Engine — wired with event bus and runtime for state projection.
    workflow_engine = build_workflow_engine(
        canonical_bus=canonical_bus,
        runtime=runtime,
        max_concurrent_tasks=(config or {}).get("max_concurrent_tasks", 4),
        auto_checkpoint=True,
    )

    # 6. AI Infrastructure — capability registry, router, executor registry.
    ai_infra = build_ai_infrastructure(
        runtime=runtime,
        include_workforce_models=True,
        bind_adapters=True,
    )

    # 7. Execution Engine — wired with environment, workflow engine, events, runtime,
    # durable artifact pipeline (catalog + store), and context builder.
    execution_engine = build_execution_engine(
        workspace_root=root_dir,
        canonical_bus=canonical_bus,
        runtime=runtime,
        workflow_engine=workflow_engine,
        model_router=ai_infra.router,
        model_executor=ai_infra.executor_registry,
        capacity_router=ai_infra.capacity_router,
        max_concurrent_workers=(config or {}).get("max_concurrent_workers", 4),
        durable_catalog=durable_catalog,
        physical_store=physical_store,
        context_builder=context_builder,
    )

    # 8. Artifact Platform — wired with canonical event bus and DurableArtifactStoreBridge.
    artifact_platform = build_artifact_platform_from_bus(
        canonical_bus=canonical_bus,
        store=durable_bridge,
    )

    # 9. Security Platform — wired with canonical event bus.
    security_platform = build_security_platform_from_bus(
        canonical_bus=canonical_bus,
    )

    # 10. Review Engine (concrete) — wired with canonical event bus.
    concrete_review_engine = ConcreteReviewEngine(event_sink=canonical_bus)

    # 11. Kernel Adapters — bridging platform engines to Kernel's abstract interfaces.
    kernel_workflow_engine = KernelWorkflowEngineAdapter(concrete_engine=workflow_engine)
    kernel_execution_engine = KernelExecutionEngineAdapter(concrete_engine=execution_engine)
    kernel_review_engine = KernelReviewEngineAdapter(concrete_engine=concrete_review_engine)
    kernel_model_router = KernelModelRouterAdapter(model_router=ai_infra.router)

    # 12. Strategic & Planning Coordination components.
    strategic_engine = DefaultStrategicEngine()
    intent_analyzer = DefaultIntentAnalyzer(knowledge_engine=kernel_knowledge_engine)
    planning_coordinator = DefaultPlanningCoordinator(
        strategic_engine=strategic_engine,
        workflow_engine=kernel_workflow_engine,
        event_bus=kernel_bus,
    )

    # 13. Orchestration & Execution components.
    orchestration_engine = DefaultOrchestrationEngine(
        execution_engine=kernel_execution_engine,
        review_engine=kernel_review_engine,
        event_bus=kernel_bus,
        runtime_state_manager=facade,
        model_router=kernel_model_router,
    )

    # 14. Shared Platform Services & Governance coordinators.
    infrastructure_coordinator = DefaultInfrastructureCoordinator(
        runtime_state_manager=facade,
        event_bus=kernel_bus,
        memory_engine=kernel_memory_engine,
        knowledge_engine=kernel_knowledge_engine,
        model_router=kernel_model_router,
    )
    completion_module = DefaultCompletionModule(
        review_engine=kernel_review_engine,
        event_bus=kernel_bus,
        runtime_state_manager=facade,
    )
    approval_coordinator = DefaultApprovalCoordinator(
        event_bus=kernel_bus,
        runtime_state_manager=facade,
    )
    recovery_coordinator = DefaultRecoveryCoordinator(
        event_bus=kernel_bus,
        runtime_state_manager=facade,
    )

    kernel_config = dict(config) if config else {}
    if "auto_execute" not in kernel_config:
        kernel_config["auto_execute"] = False

    # 16. The Kernel — fully wired with all platform engines, coordinators, and learning engine.
    kernel = Kernel(
        version=kernel_version,
        config=kernel_config,
        event_bus=kernel_bus,
        runtime_state_manager=facade,
        request_validator=DefaultRequestValidator(),
        request_normalizer=DefaultRequestNormalizer(),
        project_initializer=DefaultProjectInitializer(event_bus=kernel_bus),
        identifier_generator=DefaultIdentifierGenerator(),
        intent_analyzer=intent_analyzer,
        planning_coordinator=planning_coordinator,
        orchestration_engine=orchestration_engine,
        infrastructure_coordinator=infrastructure_coordinator,
        completion_module=completion_module,
        approval_coordinator=approval_coordinator,
        recovery_coordinator=recovery_coordinator,
        strategic_engine=strategic_engine,
        workflow_engine=kernel_workflow_engine,
        execution_engine=kernel_execution_engine,
        review_engine=kernel_review_engine,
        memory_engine=kernel_memory_engine,
        knowledge_engine=kernel_knowledge_engine,
        model_router=kernel_model_router,
        learning_engine=learning_engine,
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
        artifact_platform=artifact_platform,
        security_platform=security_platform,
        review_engine=concrete_review_engine,
        strategic_engine=strategic_engine,
        context_builder=context_builder,
        learning_engine=learning_engine,
        planning_coordinator=planning_coordinator,
        orchestration_engine=orchestration_engine,
        completion_module=completion_module,
        infrastructure_coordinator=infrastructure_coordinator,
        recovery_coordinator=recovery_coordinator,
        approval_coordinator=approval_coordinator,
        durable_catalog=durable_catalog,
        physical_store=physical_store,
        artifact_bridge=durable_bridge,
        skipped_runtime_events=skipped,
    )