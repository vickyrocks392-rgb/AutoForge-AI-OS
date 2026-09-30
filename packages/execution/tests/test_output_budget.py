"""DEF-18L-02 regression: the routed model's declared output budget must be
honoured.

The Capability Registry declares ``max_output_tokens`` for every model, but the
execution request carried no budget. The local runtime therefore applied its own
small default and returned ``finish_reason="length"`` -- a truncated response
with no parseable ``file_edits`` -- so real multi-file deliverables could not be
produced at all. The 18-L greenfield run demonstrated this against the M6.

The fix derives the budget from the model the router ACTUALLY selected, so it
stays provider-neutral and adds no new constant. These tests pin that behaviour
without contacting any model.
"""

from __future__ import annotations

import sys
import uuid
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[3]
for _pkg in ["events", "runtime", "models", "connectors", "workflows",
             "execution", "artifacts", "persistence", "ai_infrastructure",
             "workforce"]:
    _src = _ROOT / "packages" / _pkg / "src"
    if _src.exists() and str(_src) not in sys.path:
        sys.path.insert(0, str(_src))

from autoforge_ai_infrastructure.execution import (  # noqa: E402
    ExecutionRequest,
    ExecutionTarget,
    ExecutorRegistry,
)
from autoforge_execution.ai_adapter import AIInfrastructureAdapter  # noqa: E402
from autoforge_execution.context import ExecutionContext  # noqa: E402
from autoforge_ai_infrastructure.metadata import RoutingRequest  # noqa: E402


class _CapturingExecutor:
    """Minimal ModelExecutor that records the payload it was asked to run."""

    def __init__(self) -> None:
        self.seen: list[dict] = []

    async def execute(self, request, target):
        self.seen.append({
            "parameters": dict(request.parameters or {}),
            "model_id": target.model_id,
            "provider_id": target.provider_id,
        })
        raise RuntimeError("captured")  # stop before any real execution


class _Model:
    def __init__(self, model_id: str, provider_id: str, max_output_tokens):
        self.model_id = model_id
        self.provider_id = provider_id
        self.max_output_tokens = max_output_tokens


class _Candidate:
    def __init__(self, model):
        self.model = model


class _Decision:
    def __init__(self, model):
        self.selected = _Candidate(model)
        self.alternatives = []


class _Router:
    def __init__(self, model):
        self._m = model

    def route(self, routing):
        return _Decision(self._m)


def _adapter(model, executor):
    return AIInfrastructureAdapter(router=_Router(model), model_executor=executor)


def _ctx():
    return ExecutionContext(
        task_id="t-18l-02",
        task_name="Implement module",
        task_type="coding",
        workflow_id=uuid.uuid4(),
    )


@pytest.mark.asyncio
async def test_declared_output_budget_is_applied_to_request():
    """The selected model's max_output_tokens must reach the request."""
    cap = _CapturingExecutor()
    adapter = _adapter(_Model("m1", "local", 4096), ExecutorRegistry())
    adapter._executor.bind("local", cap)

    req = ExecutionRequest(payload={"x": 1}, parameters={"temperature": 0.1})
    with pytest.raises(RuntimeError):
        await adapter._execute_request(
            req,
            RoutingRequest(required_capabilities=frozenset({"code_generation"})),
        )

    assert cap.seen, "executor must have been invoked"
    assert cap.seen[0]["parameters"]["max_tokens"] == 4096


@pytest.mark.asyncio
async def test_explicit_caller_budget_is_never_overridden():
    """An explicit request budget wins over the declared default."""
    cap = _CapturingExecutor()
    adapter = _adapter(_Model("m1", "local", 4096), ExecutorRegistry())
    adapter._executor.bind("local", cap)

    req = ExecutionRequest(
        payload={"x": 1},
        parameters={"temperature": 0.1, "max_tokens": 64},
    )
    with pytest.raises(RuntimeError):
        await adapter._execute_request(
            req,
            RoutingRequest(required_capabilities=frozenset({"code_generation"})),
        )

    assert cap.seen[0]["parameters"]["max_tokens"] == 64


@pytest.mark.asyncio
async def test_missing_declared_budget_leaves_request_unchanged():
    """A model with no declared budget must not gain an invented limit."""
    cap = _CapturingExecutor()
    adapter = _adapter(_Model("m1", "local", None), ExecutorRegistry())
    adapter._executor.bind("local", cap)

    req = ExecutionRequest(payload={"x": 1}, parameters={"temperature": 0.1})
    with pytest.raises(RuntimeError):
        await adapter._execute_request(
            req,
            RoutingRequest(required_capabilities=frozenset({"code_generation"})),
        )

    assert "max_tokens" not in cap.seen[0]["parameters"]
