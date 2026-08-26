"""AI Infrastructure Platform wiring within the composition root.

Wires the Phase 7 AI Infrastructure Platform into the AutoForge composition
root WITHOUT forcing existing subsystems to depend on it:

- :class:`RuntimeCheckpointAdapter` adapts the frozen Runtime State Manager to
  the ``RuntimeCheckpointPort`` protocol consumed by the Execution Continuity
  Manager.
- :class:`build_ai_infrastructure` constructs the full AI Infrastructure stack
  (Capability Registry + reference catalog, Model Router, Executor Registry,
  Execution Continuity Manager) and returns the injectable services.
- :class:`AIInfrastructureServices` holds the wired components so they can be
  injected into the Kernel (via Kernel adapters) or other consumers.

The composition root calls this factory and injects the Kernel-facing adapters,
preserving the dependency-inversion boundary: the Kernel depends on ABCs in
``autoforge_kernel.interfaces``; the adapters live here.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from autoforge_ai_infrastructure import (
    ExecutionContinuityService,
    ExecutorRegistry,
    InMemoryCapabilityRegistry,
    ModelRouterService,
    RetryPolicy,
)
from autoforge_ai_infrastructure.events import AIInfrastructureEvents
from autoforge_ai_infrastructure.kernel_adapter import (
    KernelContinuityManager,
    KernelModelRouter,
)
from autoforge_ai_infrastructure.reference_catalog import install_reference_catalog
from autoforge_composition.checkpoint_port_adapter import RuntimeCheckpointAdapter


__all__ = [
    "AIInfrastructureServices",
    "build_ai_infrastructure",
]


@dataclass
class AIInfrastructureServices:
    """Injectable AI Infrastructure Platform components.

    The Kernel receives ``kernel_router`` and ``kernel_continuity`` — the
    dependency-inversion wrappers over the concrete platform services.
    """

    registry: InMemoryCapabilityRegistry
    router: ModelRouterService
    executor_registry: ExecutorRegistry
    continuity: ExecutionContinuityService
    kernel_router: KernelModelRouter
    kernel_continuity: KernelContinuityManager


def build_ai_infrastructure(
    *,
    runtime: Any | None = None,
    default_policy: Any | None = None,
    retry_policy: RetryPolicy | None = None,
    event_sink: Any | None = None,
    sleeper: Any | None = None,
) -> AIInfrastructureServices:
    """Construct the AI Infrastructure Platform with the reference catalog.

    Args:
        runtime: Optional :class:`RuntimeStateManager` — when provided, the
            Execution Continuity Manager is wired with a checkpoint adapter so
            checkpoint recovery delegates to the Runtime boundary. When omitted,
            continuity operates without durable checkpoints (valid in offline
            mode).
        default_policy: Optional routing policy injected into the Model Router.
        retry_policy: Optional ``RetryPolicy`` for the continuity manager.
        event_sink: Optional :class:`CanonicalEventSink` for canonical event
            publication through the existing Event Platform transport.
        sleeper: Optional callable ``(seconds: float) -> Awaitable[None]`` for
            backoff between retry attempts. When omitted, defaults to
            :func:`asyncio.sleep`.

    Returns:
        :class:`AIInfrastructureServices` ready for dependency injection.
    """
    # 1. Capability Registry + reference catalog (metadata only).
    registry = InMemoryCapabilityRegistry()
    install_reference_catalog(registry)

    # 2. Model Router (selection only; no execution).
    router = ModelRouterService(registry, default_policy=default_policy)

    # 3. Executor Registry (provider-neutral execution seam).
    executor_registry = ExecutorRegistry()

    # 4. Checkpoint adapter over the frozen Runtime boundary.
    checkpoint_port = (
        RuntimeCheckpointAdapter(runtime) if runtime is not None else None
    )

    # 5. Canonical event factory.
    events = AIInfrastructureEvents(sink=event_sink) if event_sink is not None else None

    # 6. Execution Continuity Manager (retry, failover, checkpoint recovery).
    continuity = ExecutionContinuityService(
        router=router,
        executors=executor_registry,
        retry_policy=retry_policy or RetryPolicy(max_attempts=3),
        events=events,
        checkpoints=checkpoint_port,
        sleeper=sleeper,
    )

    # 7. Kernel-facing dependency-inversion adapters.
    kernel_router = KernelModelRouter(router, registry)
    kernel_continuity = KernelContinuityManager(continuity)

    return AIInfrastructureServices(
        registry=registry,
        router=router,
        executor_registry=executor_registry,
        continuity=continuity,
        kernel_router=kernel_router,
        kernel_continuity=kernel_continuity,
    )
