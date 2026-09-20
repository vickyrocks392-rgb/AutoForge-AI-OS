"""
Execution Platform wiring — Phase 10.

Provides:
- ``ExecutionPlatformEventSink``: bridges ExecutionEngine → CanonicalEventBus.
- ``ExecutionPlatformRuntimeFacade``: bridges ExecutionEngine → RuntimeStateManager.
- ``build_execution_engine()``: factory that wires Environment, AI Infrastructure,
  Connectors, WorkflowEngine, and Event Platform into a fully configured ExecutionEngine.
"""

from __future__ import annotations

import tempfile
import uuid
from pathlib import Path
from typing import Any

from autoforge_ai_infrastructure.execution import RoutedModelExecutor
from autoforge_ai_infrastructure.router import ModelRouterService
from autoforge_connectors.filesystem import WorkspaceFilesystem
from autoforge_connectors.git import GitConnector
from autoforge_event_platform.adapter import CanonicalEventBus
from autoforge_events.base import BaseEvent
from autoforge_runtime import RuntimeStateManager
from autoforge_runtime.execution_store import DurableExecutionStore
from autoforge_runtime.persistence import PersistenceLayer
from autoforge_workflows.engine import WorkflowEngine

from autoforge_execution.ai_adapter import AIInfrastructureAdapter
from autoforge_execution.artifacts import ArtifactPipeline
from autoforge_execution.engine import ExecutionEngine, ExecutionEngineConfig
from autoforge_execution.environment import WorkspaceEnvironment
from autoforge_execution.governance import ExecutionGovernance, GovernancePolicy

__all__ = [
    "ExecutionPlatformEventSink",
    "ExecutionPlatformRuntimeFacade",
    "build_durable_execution_store",
    "build_execution_engine",
]



class ExecutionPlatformEventSink:
    """
    Bridges ``ExecutionEngine`` canonical events to the platform's ``CanonicalEventBus``.
    """

    def __init__(self, event_bus: CanonicalEventBus) -> None:
        self._bus = event_bus

    def publish(self, event: Any) -> None:
        try:
            if isinstance(event, BaseEvent):
                self._bus.publish(event)
        except Exception:
            pass


class ExecutionPlatformRuntimeFacade:
    """
    Bridges ``ExecutionEngine`` task & worker states into ``RuntimeStateManager``.
    """

    def __init__(self, runtime: RuntimeStateManager) -> None:
        self._runtime = runtime

    def record_task_state(self, task_id: str, state: dict[str, Any]) -> None:
        try:
            if hasattr(self._runtime, "checkpoint_manager"):
                self._runtime.checkpoint_manager.store(
                    entity_id=task_id,
                    state_snapshot=state,
                    checkpoint_type="worker_task",
                )
        except Exception:
            pass

    def record_workflow_state(self, workflow_id: uuid.UUID, state: dict[str, Any]) -> None:
        try:
            if hasattr(self._runtime, "checkpoint_manager"):
                self._runtime.checkpoint_manager.store(
                    entity_id=str(workflow_id),
                    state_snapshot=state,
                    checkpoint_type="execution_workflow",
                )
        except Exception:
            pass


def build_durable_execution_store(
    runtime: RuntimeStateManager | PersistenceLayer | None = None,
    *,
    owner_id: str | None = None,
) -> DurableExecutionStore:
    """Build a durable execution store on the *existing* runtime foundation.

    Accepts a ``RuntimeStateManager`` (its persistence layer is reused) or a
    ``PersistenceLayer`` directly. This is deliberately the same database as
    every other runtime entity: one durable foundation, no second store.
    """
    if isinstance(runtime, PersistenceLayer):
        return DurableExecutionStore(runtime, owner_id=owner_id)
    if runtime is not None:
        return DurableExecutionStore(runtime.persistence, owner_id=owner_id)
    return DurableExecutionStore(PersistenceLayer(), owner_id=owner_id)


def build_execution_engine(
    workspace_root: str | Path | None = None,
    *,
    canonical_bus: CanonicalEventBus | None = None,
    runtime: RuntimeStateManager | None = None,
    workflow_engine: WorkflowEngine | None = None,
    model_router: ModelRouterService | None = None,
    model_executor: RoutedModelExecutor | None = None,
    capacity_router: Any | None = None,
    governance_policy: GovernancePolicy | None = None,
    max_concurrent_workers: int = 4,
    durable_store: DurableExecutionStore | None = None,
) -> ExecutionEngine:
    """
    Construct and wire a production ``ExecutionEngine``.

    ``durable_store`` (Phase 18-J.2): when provided, dispatched work units are
    recorded with canonical durable execution identity (execution / attempt /
    boundary) through the runtime PersistenceLayer. Build it with
    :func:`build_durable_execution_store` so it shares the runtime's own
    persistence layer.
    """
    root_path = Path(workspace_root) if workspace_root else Path(tempfile.mkdtemp(prefix="autoforge_exec_"))
    root_path.mkdir(parents=True, exist_ok=True)

    filesystem = WorkspaceFilesystem(root_path)
    git = GitConnector(root_path)
    env = WorkspaceEnvironment(root_path, filesystem=filesystem, git=git)

    event_sink = ExecutionPlatformEventSink(canonical_bus) if canonical_bus else None
    runtime_facade = ExecutionPlatformRuntimeFacade(runtime) if runtime else None

    ai_adapter = AIInfrastructureAdapter(
        router=model_router,
        model_executor=model_executor,
        capacity_router=capacity_router,
    )

    artifacts = ArtifactPipeline(event_sink=event_sink)
    governance = ExecutionGovernance(policy=governance_policy)

    config = ExecutionEngineConfig(
        max_concurrent_workers=max_concurrent_workers,
        durable_recorder=durable_store,
    )

    engine = ExecutionEngine(
        environment=env,
        ai_provider=ai_adapter,
        workflow_engine=workflow_engine,
        config=config,
        artifact_pipeline=artifacts,
        governance=governance,
        event_sink=event_sink,
        runtime_facade=runtime_facade,
    )

    from autoforge_workforce.dispatch import WorkforceDispatcher
    engine._dispatcher = WorkforceDispatcher(
        environment=env,
        ai_provider=ai_adapter,
        max_concurrent_workers=max_concurrent_workers,
        artifact_pipeline=artifacts,
        governance=governance,
        loop_config=config.default_loop_config,
        event_sink=event_sink,
    )

    return engine
