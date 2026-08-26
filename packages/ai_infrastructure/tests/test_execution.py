"""Tests for the provider-neutral execution boundary."""

from __future__ import annotations

import pytest

import autoforge_ai_infrastructure as ai
from autoforge_ai_infrastructure.execution import (
    ExecutionRequest,
    ExecutionTarget,
    ExecutorRegistry,
    RoutedModelExecutor,
    execute_attempt,
)
from autoforge_ai_infrastructure.metadata import (
    CapabilityIds,
    RoutingRequest,
)
from tests.helpers import (
    FakeExecutor,
    NeverCompletingExecutor,
)


async def test_executor_registry_bind_and_get():
    reg = ExecutorRegistry()
    executor = FakeExecutor()
    reg.bind("p1", executor)
    assert reg.get("p1") is executor
    assert reg.bound_providers() == ["p1"]
    reg.unbind("p1")
    assert reg.bound_providers() == []


async def test_executor_registry_rejects_non_protocol():
    reg = ExecutorRegistry()
    class NotAnExecutor:
        pass
    with pytest.raises(TypeError):
        reg.bind("p1", NotAnExecutor())


async def test_unbound_executor_raises_provider_unavailable():
    reg = ExecutorRegistry()
    with pytest.raises(ai.ExecutorNotBoundError):
        reg.get("ghost")


async def test_execute_attempt_success():
    reg = ExecutorRegistry()
    reg.bind("p1", FakeExecutor())
    request = ExecutionRequest(payload={"prompt": "hi"})
    target = ExecutionTarget(model_id="m1", provider_id="p1")
    result = await execute_attempt(reg, request, target)
    assert result.model_id == "m1"
    assert result.attempts == 1
    assert result.failovers == 0


async def test_execute_attempt_timeout():
    reg = ExecutorRegistry()
    reg.bind("p1", NeverCompletingExecutor())
    request = ExecutionRequest(payload={"prompt": "hi"}, timeout_seconds=0.01)
    target = ExecutionTarget(model_id="m1", provider_id="p1")
    with pytest.raises(ai.ExecutionTimeoutError):
        await execute_attempt(reg, request, target)


async def test_execute_attempt_no_timeout_wait_for():
    reg = ExecutorRegistry()
    reg.bind("p1", FakeExecutor())
    request = ExecutionRequest(payload={"prompt": "hi"})  # no budget
    target = ExecutionTarget(model_id="m1", provider_id="p1")
    result = await execute_attempt(reg, request, target)
    assert result.provider_id == "p1"


async def test_routed_model_executor_selects_and_executes(registry):
    from autoforge_ai_infrastructure.router import ModelRouterService

    router = ModelRouterService(registry)
    reg = ExecutorRegistry()
    reg.bind("reference-local", FakeExecutor())
    routed = RoutedModelExecutor(router, reg)
    result = await routed.execute(
        ExecutionRequest(payload={"prompt": "hi"}),
        RoutingRequest(
            required_capabilities=frozenset({CapabilityIds.CODE_GENERATION})
        ),
    )
    assert result.model_id == "reference-local-mini-q4"