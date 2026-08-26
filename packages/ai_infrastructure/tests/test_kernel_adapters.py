"""Tests for the Kernel ABC adapters (dependency-inversion boundary)."""

from __future__ import annotations

import uuid

from autoforge_models.enums import ModelProvider
from autoforge_kernel.interfaces import (
    ExecutionContinuityManager,
    ModelRouter,
)

from autoforge_ai_infrastructure.kernel_adapter import (
    KernelContinuityManager,
    KernelModelRouter,
    routing_request_from_task,
)
from tests.helpers import reference_router


async def test_kernel_model_router_selects_local_profile(registry):
    router = reference_router(registry)
    adapter = KernelModelRouter(router, registry)
    profile = await adapter.select_model({"required_capabilities": ["code_generation"]})
    assert profile.model_name == "reference-local-mini-q4"
    assert profile.provider == ModelProvider.LOCAL
    assert profile.is_active is True


async def test_kernel_model_router_exclude_provider(registry):
    router = reference_router(registry)
    adapter = KernelModelRouter(router, registry)
    profile = await adapter.select_model(
        {"required_capabilities": ["code_generation"]},
        exclude_provider="reference-local",
    )
    assert profile.model_name == "reference-cloud-large-v2"


async def test_kernel_model_router_get_capabilities(registry, router):
    adapter = KernelModelRouter(router, registry)
    caps = await adapter.get_model_capabilities("reference-local-mini-q4")
    assert "code_generation" in caps["capabilities"]
    assert caps["locally_executable"] is True


async def test_kernel_model_router_health(registry, router):
    adapter = KernelModelRouter(router, registry)
    health = await adapter.get_provider_health()
    assert health["reference-local"]["local_capable"] is True
    assert health["reference-cloud"]["available"] is True


async def test_kernel_continuity_recover_no_context(registry):
    from autoforge_ai_infrastructure import ExecutionContinuityService, ExecutorRegistry
    from autoforge_ai_infrastructure.router import ModelRouterService

    service = ExecutionContinuityService(
        ModelRouterService(registry), ExecutorRegistry()
    )
    adapter = KernelContinuityManager(service)
    outcome = await adapter.retry(uuid.uuid4(), {})
    assert outcome["success"] is False


def test_routing_request_from_task_default_capability():
    req = routing_request_from_task({})
    assert "text_generation" in req.required_capabilities