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
    OllamaProviderAdapter,
    OpenAICompatibleProviderAdapter,
    RetryPolicy,
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
    ollama_base_url: str = "http://127.0.0.1:11434",
    node_endpoints: dict[str, str] | None = None,
    secrets_manager: Any | None = None,
) -> None:
    """Bind standard local and cloud provider adapters to ExecutorRegistry.

    ``node_endpoints`` optionally maps a provider id (``local-m1``,
    ``local-hp``, or any additional LAN node such as ``local-mac-mini-m6``)
    to its own Ollama base URL, so each node can expose an independent
    LAN endpoint. When a provider has no explicit entry it falls back to
    ``ollama_base_url``, preserving the original single-URL default exactly.
    """
    endpoints = dict(node_endpoints or {})

    # 1. Local M1 Ollama (independent endpoint when configured)
    local_m1_adapter = OllamaProviderAdapter(
        provider_id="local-m1",
        base_url=endpoints.get("local-m1", ollama_base_url),
    )
    executor_registry.bind("local-m1", local_m1_adapter)

    # 2. Local HP Ollama (independent endpoint when configured)
    local_hp_adapter = OllamaProviderAdapter(
        provider_id="local-hp",
        base_url=endpoints.get("local-hp", ollama_base_url),
    )
    executor_registry.bind("local-hp", local_hp_adapter)

    # 2a. Any additional LAN nodes provided (e.g. a third local Mac Mini node).
    #     Missing entries keep the single-URL default; no topology is created
    #     unless the caller explicitly configures one.
    for provider_id in sorted(endpoints):
        if provider_id in ("local-m1", "local-hp"):
            continue
        extra_adapter = OllamaProviderAdapter(
            provider_id=provider_id,
            base_url=endpoints[provider_id],
        )
        executor_registry.bind(provider_id, extra_adapter)

    # 3. OpenAI-compatible
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
    ollama_base_url: str = "http://127.0.0.1:11434",
    node_endpoints: dict[str, str] | None = None,
    secrets_manager: Any | None = None,
) -> AIInfrastructureServices:
    """Construct the AI Infrastructure Platform.

    Args:
        runtime: Optional :class:`RuntimeStateManager` for checkpoint adaptation.
        default_policy: Optional routing policy injected into the Model Router.
        retry_policy: Optional ``RetryPolicy`` for the continuity manager.
        event_sink: Optional :class:`CanonicalEventSink` for canonical event publication.
        sleeper: Optional callable for async sleep.
        include_workforce_models: If True, registers canonical workforce models alongside reference catalog.
        bind_adapters: If True, binds standard provider adapters (Ollama, OpenAI-compatible).
        ollama_base_url: Base URL for local Ollama instances (fallback when a node has no explicit endpoint).
        node_endpoints: Optional mapping of provider id (e.g. ``local-m1``, ``local-hp``,
            ``local-mac-mini-m6``) to that node's own Ollama base URL, enabling an
            independent endpoint per LAN inference node.
        secrets_manager: Optional SecretsManager for cloud adapter credentials.

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
            ollama_base_url=ollama_base_url,
            node_endpoints=node_endpoints,
            secrets_manager=secrets_manager,
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
