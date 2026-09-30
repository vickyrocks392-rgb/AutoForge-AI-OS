"""
DEF-18L-03 regression: the ORIGINAL user request must reach every engineering
loop.

``KernelExecutionEngineAdapter.execute_loop`` already builds a loop task's
``input_data`` from ``context["request_text"]``. O-2 never populated that key, so
the model received a generic task name ("Core Implementation") instead of the
project specification, and produced a deliverable that could not satisfy the
request. These tests pin that O-2 now carries the request into the loop context,
read from the authoritative Runtime state.
"""

from __future__ import annotations

import sys
import uuid
from pathlib import Path
from typing import Any

import pytest

_ROOT = Path(__file__).resolve().parents[3]
for _pkg in ["events", "runtime", "models", "kernel"]:
    _src = _ROOT / "packages" / _pkg / "src"
    if _src.exists() and str(_src) not in sys.path:
        sys.path.insert(0, str(_src))

from autoforge_kernel.interfaces import ExecutableWorkflow  # noqa: E402
from autoforge_kernel.orchestration import DefaultOrchestrationEngine  # noqa: E402


REQUEST = "Build a small token counting library with a CLI and pytest tests."


class _Recorder:
    """Loop orchestrator that records the context it was handed."""

    def __init__(self) -> None:
        self.contexts: list[dict[str, Any]] = []

    async def orchestrate_loop(self, project_id, loop_type, loop_context):
        self.contexts.append(loop_context)
        return {"status": "complete", "loop_type": loop_type}


class _State:
    def __init__(self, state: dict[str, Any]) -> None:
        self._state = state

    async def get_project_state(self, project_id):
        return self._state

    async def transition_state(self, **kwargs):
        return None


def _engine(state: dict[str, Any], recorder: _Recorder) -> DefaultOrchestrationEngine:
    return DefaultOrchestrationEngine(
        loop_orchestrator=recorder,
        runtime_state_manager=_State(state),
    )


@pytest.mark.asyncio
async def test_request_text_reaches_loop_context_from_runtime_state_shape():
    """The real Runtime state shape is ``request["description"]``.

    This is the shape ``KernelRuntimeFacade`` actually projects, and the one
    the production composition root produces.
    """
    recorder = _Recorder()
    engine = _engine({"request": {"name": "p", "description": REQUEST}}, recorder)
    wf = ExecutableWorkflow(
        workflow_id=uuid.uuid4(),
        loops=[{"type": "coding", "name": "Core Implementation"}],
    )
    await engine.orchestrate(uuid.uuid4(), wf)
    assert recorder.contexts[0]["request_text"] == REQUEST


@pytest.mark.asyncio
async def test_request_text_reaches_loop_context_from_description():
    """A state written with a top-level ``description`` still works."""
    recorder = _Recorder()
    engine = _engine({"description": REQUEST, "metadata": {}}, recorder)
    wf = ExecutableWorkflow(
        workflow_id=uuid.uuid4(),
        loops=[{"type": "coding", "name": "Core Implementation"}],
    )
    await engine.orchestrate(uuid.uuid4(), wf)

    assert recorder.contexts, "the loop must have been orchestrated"
    assert recorder.contexts[0]["request_text"] == REQUEST


@pytest.mark.asyncio
async def test_request_text_falls_back_to_metadata_original_request():
    """State written without ``description`` still carries the request."""
    recorder = _Recorder()
    engine = _engine({"metadata": {"original_request": REQUEST}}, recorder)
    wf = ExecutableWorkflow(
        workflow_id=uuid.uuid4(),
        loops=[{"type": "coding", "name": "Core Implementation"}],
    )
    await engine.orchestrate(uuid.uuid4(), wf)
    assert recorder.contexts[0]["request_text"] == REQUEST


@pytest.mark.asyncio
async def test_every_loop_receives_the_request():
    """All loops, not just the first, must receive the request."""
    recorder = _Recorder()
    engine = _engine({"description": REQUEST, "metadata": {}}, recorder)
    wf = ExecutableWorkflow(
        workflow_id=uuid.uuid4(),
        loops=[
            {"type": "architecture", "name": "A"},
            {"type": "coding", "name": "B"},
            {"type": "qa", "name": "C"},
        ],
    )
    await engine.orchestrate(uuid.uuid4(), wf)
    assert len(recorder.contexts) == 3
    assert all(c["request_text"] == REQUEST for c in recorder.contexts)


@pytest.mark.asyncio
async def test_missing_request_degrades_without_raising():
    """Absent request text must not break orchestration (fail-soft, not fail-hard)."""
    recorder = _Recorder()
    engine = _engine({}, recorder)
    wf = ExecutableWorkflow(
        workflow_id=uuid.uuid4(),
        loops=[{"type": "coding", "name": "Core Implementation"}],
    )
    await engine.orchestrate(uuid.uuid4(), wf)
    assert recorder.contexts[0]["request_text"] == ""


@pytest.mark.asyncio
async def test_state_read_failure_does_not_block_orchestration():
    """A state read error degrades to the previous behaviour, it does not stop."""

    class _Boom:
        async def get_project_state(self, project_id):
            raise RuntimeError("runtime unavailable")

        async def transition_state(self, **kwargs):
            return None

    recorder = _Recorder()
    engine = DefaultOrchestrationEngine(
        loop_orchestrator=recorder, runtime_state_manager=_Boom()
    )
    wf = ExecutableWorkflow(
        workflow_id=uuid.uuid4(),
        loops=[{"type": "coding", "name": "Core Implementation"}],
    )
    await engine.orchestrate(uuid.uuid4(), wf)
    assert recorder.contexts[0]["request_text"] == ""
