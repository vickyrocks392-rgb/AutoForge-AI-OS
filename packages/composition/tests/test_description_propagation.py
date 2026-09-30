"""
DEF-18L-04 regression: the project specification must reach the canonical
Context Engineering prompt.

``EngineeringContextBuilder`` assembles the model's context from
``task_def.name`` and ``task_def.description`` (context_builder.py:235,306).
``KernelExecutionEngineAdapter.execute_loop`` never populated ``description``,
so the globally-enabled, certified Context Engineering path built its prompt
from the loop name alone ("Core Implementation") and the model produced an
unrelated generic project. These tests pin the fix at the adapter boundary.
"""

from __future__ import annotations

import sys
import uuid
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[3]
for _pkg in ["events", "runtime", "models", "workflows", "execution", "kernel",
             "composition", "ai_infrastructure", "connectors", "artifacts",
             "persistence", "workforce", "security", "review", "orchestration",
             "event_platform"]:
    _src = _ROOT / "packages" / _pkg / "src"
    if _src.exists() and str(_src) not in sys.path:
        sys.path.insert(0, str(_src))

from autoforge_composition.kernel_adapters import (  # noqa: E402
    KernelExecutionEngineAdapter,
)

REQUEST = "Build a greenfield Python package named 'tokenizer_lite' with a CLI."


class _SpyEngine:
    def __init__(self) -> None:
        self.task_def = None

    async def execute_task_definition(self, task_def, workflow_id=None,
                                      worker_type=None):
        self.task_def = task_def
        return True, [], None


def _ctx(**over):
    ctx = {
        "project_id": str(uuid.uuid4()),
        "workflow_id": str(uuid.uuid4()),
        "loop": {"type": "coding", "name": "Core Implementation"},
        "request_text": REQUEST,
    }
    ctx.update(over)
    return ctx


@pytest.mark.asyncio
async def test_description_carries_the_request_text():
    """O-2 passes ``loop_input=loop_context`` (the loop is nested under "loop")."""
    spy = _SpyEngine()
    ad = KernelExecutionEngineAdapter(concrete_engine=spy)
    ctx = _ctx()
    await ad.execute_loop("coding", ctx, ctx)
    assert spy.task_def.description == REQUEST


@pytest.mark.asyncio
async def test_explicit_loop_description_wins():
    """A loop-specific description must take precedence over the request."""
    spy = _SpyEngine()
    ad = KernelExecutionEngineAdapter(concrete_engine=spy)
    ctx = _ctx(loop={
        "type": "coding",
        "name": "Core Implementation",
        "description": "SPECIFIC LOOP DESCRIPTION",
    })
    await ad.execute_loop("coding", ctx, ctx)
    assert spy.task_def.description == "SPECIFIC LOOP DESCRIPTION"


@pytest.mark.asyncio
async def test_input_data_is_preserved_unchanged():
    """The repair must not disturb the existing input_data contract."""
    spy = _SpyEngine()
    ad = KernelExecutionEngineAdapter(concrete_engine=spy)
    ctx = _ctx(loop={
        "type": "coding",
        "name": "Core Implementation",
        "input_data": {"description": REQUEST, "commands": [["echo", "hi"]]},
    })
    await ad.execute_loop("coding", ctx, ctx)
    assert spy.task_def.input_data["description"] == REQUEST
    assert spy.task_def.input_data["commands"] == [["echo", "hi"]]


@pytest.mark.asyncio
async def test_absent_request_yields_empty_description_not_a_crash():
    spy = _SpyEngine()
    ad = KernelExecutionEngineAdapter(concrete_engine=spy)
    ctx = _ctx(request_text="")
    ctx.pop("request_text")
    await ad.execute_loop("coding", ctx, ctx)
    assert spy.task_def.description == ""
