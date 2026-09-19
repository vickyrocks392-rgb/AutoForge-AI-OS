"""
Model Allocation and Capacity Management for the AI Workforce.
"""

from __future__ import annotations
import asyncio
import uuid
import logging
from typing import Any, Callable, Dict, List, Set, Tuple
from pydantic import Field

from autoforge_models.base import AutoForgeBaseModel
from autoforge_ai_infrastructure.interfaces import CapabilityRegistryPort
from autoforge_ai_infrastructure.metadata import (
    CapabilityIds,
    CapabilityMetadata,
    ProviderMetadata,
    ProviderStatus,
    ProviderType,
    DeploymentMode,
    ModelMetadata,
    ModelStatus,
    CostSpec,
    LatencyProfile,
    Modality,
    RoutingRequest,
)
from autoforge_ai_infrastructure.router import ModelRouterService, CandidateScore
from autoforge_workflows.models import TaskDefinition
from autoforge_ai_infrastructure.reference_catalog import register_reference_capabilities

logger = logging.getLogger(__name__)

def register_workforce_models(registry: CapabilityRegistryPort) -> None:
    """
    Register local nodes (M1, HP, future Mac mini) and their capabilities.
    """
    # Register standard capabilities if not already present
    from autoforge_ai_infrastructure.reference_catalog import _CAPABILITIES
    for capability_id, display_name, description in _CAPABILITIES:
        if registry.get_capability(capability_id) is None:
            registry.register_capability(
                CapabilityMetadata(
                    capability_id=capability_id,
                    display_name=display_name,
                    description=description,
                )
            )

    # 1. Register Providers/Nodes
    registry.register_provider(
        ProviderMetadata(
            provider_id="local-m1",
            display_name="Apple Mac M1 local Node",
            provider_type=ProviderType.LOCAL_RUNTIME,
            endpoint=None,
            supported_capabilities=frozenset({
                CapabilityIds.TEXT_GENERATION,
                CapabilityIds.CODE_GENERATION,
                CapabilityIds.REASONING,
                CapabilityIds.STRUCTURED_OUTPUT,
                CapabilityIds.TOOL_USE,
            }),
            deployment_modes=frozenset({DeploymentMode.LOCAL}),
        )
    )
    
    registry.register_provider(
        ProviderMetadata(
            provider_id="local-hp",
            display_name="HP local Node",
            provider_type=ProviderType.LOCAL_RUNTIME,
            endpoint=None,
            supported_capabilities=frozenset({
                CapabilityIds.TEXT_GENERATION,
                CapabilityIds.CODE_GENERATION,
            }),
            deployment_modes=frozenset({DeploymentMode.LOCAL}),
        )
    )

    registry.register_provider(
        ProviderMetadata(
            provider_id="local-mac-mini-m6",
            display_name="Future Apple Mac mini M6 Node (Simulated)",
            provider_type=ProviderType.LOCAL_RUNTIME,
            status=ProviderStatus.UNAVAILABLE,
            endpoint=None,
            supported_capabilities=frozenset({
                CapabilityIds.TEXT_GENERATION,
                CapabilityIds.CODE_GENERATION,
                CapabilityIds.REASONING,
                CapabilityIds.STRUCTURED_OUTPUT,
            }),
            deployment_modes=frozenset({DeploymentMode.LOCAL}),
        )
    )

    # 2. Register Models
    registry.register_model(
        ModelMetadata(
            model_id="qwen2.5-coder-7b",
            display_name="Qwen2.5-Coder 7B Q3_K_M",
            provider_id="local-m1",
            family="qwen",
            version="2.5",
            status=ModelStatus.ACTIVE,
            context_window_tokens=32768,
            max_output_tokens=4096,
            capabilities=frozenset({
                CapabilityIds.TEXT_GENERATION,
                CapabilityIds.CODE_GENERATION,
                CapabilityIds.STRUCTURED_OUTPUT,
                CapabilityIds.TOOL_USE,
            }),
            input_modalities=frozenset({Modality.TEXT}),
            output_modalities=frozenset({Modality.TEXT}),
            cost=CostSpec(),
            latency=LatencyProfile(typical_latency_ms=1000),
            throughput_tokens_per_second=11.18, # Measured value
            quality_tier=3,
            reliability=0.98,
            deployment_modes=frozenset({DeploymentMode.LOCAL}),
        )
    )

    registry.register_model(
        ModelMetadata(
            model_id="ornith-9b",
            display_name="Ornith 9B IQ3_M",
            provider_id="local-m1",
            family="ornith",
            version="1.0",
            status=ModelStatus.ACTIVE,
            context_window_tokens=16384,
            max_output_tokens=2048,
            capabilities=frozenset({
                CapabilityIds.TEXT_GENERATION,
                CapabilityIds.REASONING,
                CapabilityIds.STRUCTURED_OUTPUT,
            }),
            input_modalities=frozenset({Modality.TEXT}),
            output_modalities=frozenset({Modality.TEXT}),
            cost=CostSpec(),
            latency=LatencyProfile(typical_latency_ms=1200),
            throughput_tokens_per_second=10.71, # Measured value
            quality_tier=3,
            reliability=0.97,
            deployment_modes=frozenset({DeploymentMode.LOCAL}),
        )
    )

    registry.register_model(
        ModelMetadata(
            model_id="qwen2.5-coder-3b",
            display_name="Qwen2.5-Coder 3B Q4_K_M",
            provider_id="local-hp",
            family="qwen",
            version="2.5",
            status=ModelStatus.ACTIVE,
            context_window_tokens=16384,
            max_output_tokens=2048,
            capabilities=frozenset({
                CapabilityIds.TEXT_GENERATION,
                CapabilityIds.CODE_GENERATION,
            }),
            input_modalities=frozenset({Modality.TEXT}),
            output_modalities=frozenset({Modality.TEXT}),
            cost=CostSpec(),
            latency=LatencyProfile(typical_latency_ms=800),
            throughput_tokens_per_second=12.90, # Measured value
            quality_tier=2,
            reliability=0.95,
            deployment_modes=frozenset({DeploymentMode.LOCAL}),
        )
    )

    # Future Mac mini simulation node model registration (unmeasured performance, no fake benchmarking)
    registry.register_model(
        ModelMetadata(
            model_id="mac-mini-m6-node",
            display_name="Mac mini M6 model profile",
            provider_id="local-mac-mini-m6",
            family="simulation",
            version="m6",
            status=ModelStatus.ACTIVE,
            context_window_tokens=65536,
            max_output_tokens=8192,
            capabilities=frozenset({
                CapabilityIds.TEXT_GENERATION,
                CapabilityIds.CODE_GENERATION,
                CapabilityIds.REASONING,
                CapabilityIds.STRUCTURED_OUTPUT,
            }),
            input_modalities=frozenset({Modality.TEXT}),
            output_modalities=frozenset({Modality.TEXT}),
            cost=CostSpec(),
            latency=LatencyProfile(typical_latency_ms=300),
            throughput_tokens_per_second=None, # UNKNOWN, no fake benchmarking data!
            quality_tier=4,
            reliability=0.99,
            deployment_modes=frozenset({DeploymentMode.LOCAL}),
        )
    )


class ModelCapacityManager:
    """
    Capacity & concurrency tracker for models and nodes.
    Input: active runs, concurrency limit, health constraints.
    """
    def __init__(self, max_concurrency: int = 1, offline_nodes: set[str] | None = None) -> None:
        self._max_concurrency = max_concurrency
        self._active_runs: dict[str, int] = {} # model_id -> active runs
        self._offline_nodes: set[str] = set(offline_nodes) if offline_nodes is not None else {"local-mac-mini-m6"} # Future M6 is offline by default
        self._lock = asyncio.Lock()
        self._waiting_queues: dict[str, list[asyncio.Event]] = {} # model_id -> list of waiting events

    async def is_available(self, model_id: str, provider_id: str) -> bool:
        """
        Check if model is healthy and has capacity.
        """
        async with self._lock:
            if provider_id in self._offline_nodes:
                return False
            active = self._active_runs.get(model_id, 0)
            return active < self._max_concurrency

    async def acquire_slot(self, model_id: str, provider_id: str, timeout_seconds: float | None = None) -> bool:
        """
        Acquire slot. If capacity is full, wait/queue.
        """
        # Register waiting event
        event = asyncio.Event()
        async with self._lock:
            if provider_id in self._offline_nodes:
                return False
            active = self._active_runs.get(model_id, 0)
            if active < self._max_concurrency:
                self._active_runs[model_id] = active + 1
                return True
            
            # Queue the waiter
            if model_id not in self._waiting_queues:
                self._waiting_queues[model_id] = []
            self._waiting_queues[model_id].append(event)

        if timeout_seconds:
            try:
                await asyncio.wait_for(event.wait(), timeout=timeout_seconds)
            except asyncio.TimeoutError:
                async with self._lock:
                    if model_id in self._waiting_queues and event in self._waiting_queues[model_id]:
                        self._waiting_queues[model_id].remove(event)
                return False
        else:
            await event.wait()
        
        async with self._lock:
            active = self._active_runs.get(model_id, 0)
            self._active_runs[model_id] = active + 1
            return True

    async def release_slot(self, model_id: str) -> None:
        """
        Release a slot, notifying the next waiter in queue.
        """
        async with self._lock:
            active = self._active_runs.get(model_id, 0)
            if active > 0:
                self._active_runs[model_id] = active - 1
            
            if model_id in self._waiting_queues and self._waiting_queues[model_id]:
                event = self._waiting_queues[model_id].pop(0)
                event.set()

    def set_node_health(self, provider_id: str, online: bool) -> None:
        """
        Mark a node online/offline.
        """
        if online:
            self._offline_nodes.discard(provider_id)
        else:
            self._offline_nodes.add(provider_id)


class CapacityAwareRouter:
    """
    Capacity-aware and local-first router.
    Separates routing policies, filters deterministically, and applies capacity check.
    """
    def __init__(self, registry: CapabilityRegistryPort, capacity_manager: ModelCapacityManager) -> None:
        self._registry = registry
        self._router_service = ModelRouterService(registry)
        self._capacity_manager = capacity_manager

    @property
    def capacity_manager(self) -> ModelCapacityManager:
        return self._capacity_manager

    @property
    def router_service(self) -> ModelRouterService:
        return self._router_service

    async def route_task(
        self,
        task_requirements: dict[str, Any],
        *,
        privacy_policy: str | None = None,
    ) -> tuple[ModelMetadata, CandidateScore]:
        """
        Perform deterministic filtering, routing prioritization, and return selected model.
        """
        # Extract requirements
        required_caps = (
            task_requirements.get("required_capabilities")
            or task_requirements.get("capabilities")
            or []
        )
        min_context = (
            task_requirements.get("min_context_window_tokens")
            or task_requirements.get("min_context")
            or 1024
        )
        structured_output = (
            task_requirements.get("structured_output")
            or task_requirements.get("structured_output_required")
            or False
        )
        reasoning = (
            task_requirements.get("reasoning")
            or task_requirements.get("reasoning_required")
            or False
        )
        coding = (
            task_requirements.get("coding")
            or task_requirements.get("coding_required")
            or False
        )
        tool_use = (
            task_requirements.get("tool_use")
            or task_requirements.get("tool_use_required")
            or False
        )
        quality_tier = (
            task_requirements.get("quality_priority")
            or task_requirements.get("quality_tier")
        )
        latency_prio = task_requirements.get("latency_priority")
        reliability_min = task_requirements.get("reliability_minimum")
        preferred_caps = task_requirements.get("preferred_capabilities") or []

        # 1. Deterministic filtering from registry
        query_caps = set(required_caps)
        if structured_output:
            query_caps.add(CapabilityIds.STRUCTURED_OUTPUT)
        if reasoning:
            query_caps.add(CapabilityIds.REASONING)
        if coding:
            query_caps.add(CapabilityIds.CODE_GENERATION)
        if tool_use:
            query_caps.add(CapabilityIds.TOOL_USE)
        if not query_caps:
            query_caps.add(CapabilityIds.TEXT_GENERATION)

        effective_privacy = privacy_policy or task_requirements.get("privacy_policy", "local_only")
        allowed_modes = (
            frozenset({DeploymentMode.LOCAL})
            if effective_privacy in {"local_only", "local_preferred"}
            else None
        )

        req = RoutingRequest(
            required_capabilities=frozenset(query_caps),
            preferred_capabilities=frozenset(preferred_caps),
            min_context_window_tokens=min_context,
            allowed_deployment_modes=allowed_modes,
            quality_priority=int(quality_tier) if quality_tier is not None else None,
            latency_priority=latency_prio,
            reliability_minimum=float(reliability_min) if reliability_min is not None else None,
        )

        decision = self._router_service.route(req)
        
        # Check capacity/failover starting from selected candidate down to alternatives
        candidates = [decision.selected] + decision.alternatives
        for candidate in candidates:
            model = candidate.model
            # Query capacity manager
            if await self._capacity_manager.is_available(model.model_id, model.provider_id):
                return model, candidate
        
        # Fallback/Failover: Try to acquire first candidate slot (which queues/defers)
        best_candidate = decision.selected
        return best_candidate.model, best_candidate
