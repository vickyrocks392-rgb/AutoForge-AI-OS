"""AI Infrastructure Platform wiring within the composition root.

Wires the AI Infrastructure Platform into the AutoForge composition
root WITHOUT forcing existing subsystems to depend on it:

- :class:`RuntimeCheckpointAdapter` adapts the frozen Runtime State Manager to
  the ``RuntimeCheckpointPort`` protocol consumed by the Execution Continuity
  Manager.
- :class:`build_ai_infrastructure` constructs the full AI Infrastructure stack
  (Capability Registry + reference catalog / workforce catalog, Model Router, Executor Registry,
  Execution Continuity Manager) and returns the injectable services.
- :class:`AIInfrastructureServices` holds the wired components so they can be
  injected into the Kernel (via Kernel adapters) or other consumers.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from autoforge_ai_infrastructure import (
    ExecutionContinuityService,
    ExecutorRegistry,
    InMemoryCapabilityRegistry,
    ModelRouterService,
    OpenAICompatibleProviderAdapter,
    RetryPolicy,
)
from autoforge_ai_infrastructure.adapters.local_runtime import (
    LocalRuntimeProviderAdapter,
    bind_local_runtime_adapters,
    bind_optional_ollama_adapter,
)
from autoforge_ai_infrastructure.events import AIInfrastructureEvents
from autoforge_ai_infrastructure.kernel_adapter import (
    KernelContinuityManager,
    KernelModelRouter,
)
from autoforge_ai_infrastructure.reference_catalog import install_reference_catalog
from autoforge_composition.checkpoint_port_adapter import RuntimeCheckpointAdapter
from autoforge_workforce.model_allocator import (
    CapacityAwareRouter,
    ModelCapacityManager,
    register_workforce_models,
)


__all__ = [
    "AIInfrastructureServices",
    "build_ai_infrastructure",
    "bind_default_provider_adapters",
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
    capacity_router: CapacityAwareRouter | None = None
    capacity_manager: ModelCapacityManager | None = None


def bind_default_provider_adapters(
    executor_registry: ExecutorRegistry,
    *,
    local_runtime_base_url: str | None = None,
    node_endpoints: dict[str, str] | None = None,
    secrets_manager: Any | None = None,
    bind_optional_ollama: bool = False,
) -> None:
    """Bind standard local and cloud provider adapters to ExecutorRegistry.

    Gate 4 (Ollama removal): the canonical local nodes are now bound to a
    **local OpenAI-compatible runtime** — llama.cpp ``llama-server`` or MLX —
    via :class:`LocalRuntimeProviderAdapter`. Ollama is no longer a default or
    required dependency. A deployment that genuinely runs an Ollama daemon can
    still opt in with ``bind_optional_ollama=True``; provider neutrality is
    preserved, Ollama is simply not mandatory.

    ``node_endpoints`` optionally maps a provider id (``local-m1``,
    ``local-hp``, or any additional LAN node such as ``local-mac-mini-m6``) to
    its own endpoint, so each node can expose an independent LAN endpoint. When
    a provider has no explicit entry it falls back to ``local_runtime_base_url``.
    """
    # 1-2. Local nodes (M1, HP) and any additional configured LAN nodes.
    bind_local_runtime_adapters(
        executor_registry,
        local_runtime_base_url=local_runtime_base_url,
        node_endpoints=node_endpoints,
    )

    # 3. Optional, explicitly requested Ollama provider adapter.
    if bind_optional_ollama:
        bind_optional_ollama_adapter(executor_registry)

    # 4. OpenAI-compatible cloud
    openai_adapter = OpenAICompatibleProviderAdapter(
        provider_id="openai-compatible",
        secrets_manager=secrets_manager,
    )
    executor_registry.bind("openai-compatible", openai_adapter)


def build_ai_infrastructure(
    *,
    runtime: Any | None = None,
    default_policy: Any | None = None,
    retry_policy: RetryPolicy | None = None,
    event_sink: Any | None = None,
    sleeper: Any | None = None,
    include_workforce_models: bool = False,
    bind_adapters: bool = False,
    local_runtime_base_url: str | None = None,
    node_endpoints: dict[str, str] | None = None,
    secrets_manager: Any | None = None,
    bind_optional_ollama: bool = False,
) -> AIInfrastructureServices:
    """Construct the AI Infrastructure Platform.

    Args:
        runtime: Optional :class:`RuntimeStateManager` for checkpoint adaptation.
        default_policy: Optional routing policy injected into the Model Router.
        retry_policy: Optional ``RetryPolicy`` for the continuity manager.
        event_sink: Optional :class:`CanonicalEventSink` for canonical event publication.
        sleeper: Optional callable for async sleep.
        include_workforce_models: If True, registers canonical workforce models alongside reference catalog.
        bind_adapters: If True, binds standard provider adapters (local OpenAI-compatible runtime, cloud).
        local_runtime_base_url: Base URL for the local OpenAI-compatible runtime
            (llama.cpp ``llama-server`` or MLX). Defaults to
            ``AUTOFORGE_LOCAL_RUNTIME_URL`` then ``http://127.0.0.1:8080/v1``.
        node_endpoints: Optional mapping of provider id (e.g. ``local-m1``, ``local-hp``,
            ``local-mac-mini-m6``) to that node's own endpoint, enabling an
            independent endpoint per LAN inference node.
        secrets_manager: Optional SecretsManager for cloud adapter credentials.
        bind_optional_ollama: Gate 4 — opt-in only. When True an additional
            ``local-ollama`` provider adapter is bound for deployments that run
            an Ollama daemon. Ollama is never bound by default.

    Returns:
        :class:`AIInfrastructureServices` ready for dependency injection.
    """
    # 1. Capability Registry + catalog registration.
    registry = InMemoryCapabilityRegistry()
    install_reference_catalog(registry)
    if include_workforce_models:
        register_workforce_models(registry)

    # 2. Model Router (selection only; no execution).
    router = ModelRouterService(registry, default_policy=default_policy)

    # 3. Executor Registry (provider-neutral execution seam).
    executor_registry = ExecutorRegistry()
    if bind_adapters:
        bind_default_provider_adapters(
            executor_registry,
            local_runtime_base_url=local_runtime_base_url,
            node_endpoints=node_endpoints,
            secrets_manager=secrets_manager,
            bind_optional_ollama=bind_optional_ollama,
        )

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

    # 8. Capacity-aware allocation layer.
    capacity_manager = ModelCapacityManager(max_concurrency=2)
    capacity_router = CapacityAwareRouter(registry, capacity_manager)

    return AIInfrastructureServices(
        registry=registry,
        router=router,
        executor_registry=executor_registry,
        continuity=continuity,
        kernel_router=kernel_router,
        kernel_continuity=kernel_continuity,
        capacity_router=capacity_router,
        capacity_manager=capacity_manager,
    )
