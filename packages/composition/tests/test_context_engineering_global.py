"""
Gate 4B composition-level verification: Context Engineering is globally enabled.

These tests assert the *production* posture at the composition root, which is the
canonical configuration source of truth. They complement the unit-level default
tests in ``packages/execution/tests/test_context_rollout.py`` by proving the
default survives real wiring, and by pinning the supported rollback lever.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import pytest

from autoforge_composition.composition_root import build_autoforge_system
from autoforge_composition.context_allocation import RouterModelAllocationPort
from autoforge_workflows.models import TaskDefinition, WorkflowDefinition


def test_production_default_has_context_engineering_enabled():
    """A default-built system has Context Engineering ON (Gate 4B acceptance A)."""
    system = build_autoforge_system()
    assert system.context_builder is not None
    assert system.context_builder.enable_context_engineering is True


def test_default_wiring_uses_model_aware_allocation():
    """The composition root wires a router-backed budget allocator by default."""
    system = build_autoforge_system()
    assert isinstance(
        system.context_builder.model_allocator, RouterModelAllocationPort
    )


def test_explicit_config_false_is_a_supported_rollback():
    """config={'enable_context_engineering': False} disables CE with no code change."""
    system = build_autoforge_system(config={"enable_context_engineering": False})
    assert system.context_builder.enable_context_engineering is False


def test_explicit_config_true_matches_the_default():
    system = build_autoforge_system(config={"enable_context_engineering": True})
    assert system.context_builder.enable_context_engineering is True


def test_execution_dispatcher_receives_the_canonical_builder():
    """The composition-root engine and its dispatcher share one canonical builder."""
    system = build_autoforge_system()
    dispatcher = system.execution_engine._dispatcher
    assert dispatcher._context_builder is system.context_builder


@pytest.mark.asyncio
async def test_canonical_flow_reaches_the_context_builder():
    """A real dispatch assembles context through EngineeringContextBuilder."""
    ws = Path(tempfile.mkdtemp(prefix="af_gate4b_comp_"))
    (ws / "seed.py").write_text("SEED = 1\n", encoding="utf-8")

    system = build_autoforge_system(workspace_root=str(ws))
    await system.initialize()
    try:
        calls: list[str] = []
        original = system.context_builder.assemble_context

        async def spy(*args, **kwargs):
            ctx = await original(*args, **kwargs)
            calls.append(ctx.task_id)
            return ctx

        system.context_builder.assemble_context = spy  # type: ignore[method-assign]

        task_def = TaskDefinition(
            task_id="t-gate4b-comp",
            name="Gate 4B composition probe",
            task_type="coding",
            input_data={
                "files": [{"path": "out.py", "content": "print('ok')\n"}],
                "commands": [[sys.executable, "out.py"]],
                "fallback_policy": "allow_fallback",
            },
        )
        handle = system.workflow_engine.submit(
            WorkflowDefinition(name="Gate 4B comp", tasks=[task_def])
        )
        await system.execution_engine.run_workflow_to_completion(handle)

        assert calls == ["t-gate4b-comp"], (
            "canonical execution bypassed EngineeringContextBuilder"
        )
    finally:
        await system.shutdown()
