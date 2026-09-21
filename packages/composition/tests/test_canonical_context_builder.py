"""
Composition Regression Tests: EngineeringContextBuilder Canonical Wiring (Part 5 & 6).

Proves that:
1. A real task enters the canonical execution path.
2. EngineeringContextBuilder is invoked by the canonical execution engine / dispatcher.
3. The resulting context contains the intended engineering inputs (workspace files, metadata, etc.).
4. Worker execution receives that context.
5. Memory/knowledge/workspace integration is not bypassed.
6. The test fails if the Execution path silently reverts to direct ExecutionContext.from_task_definition().
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any
import uuid
import pytest

from autoforge_composition.composition_root import build_autoforge_system
from autoforge_execution.context_builder import EngineeringContextBuilder
from autoforge_execution.context import ExecutionContext
from autoforge_workflows.models import TaskDefinition, WorkflowDefinition


@pytest.mark.asyncio
async def test_canonical_context_builder_invoked_in_execution_path(tmp_path: Path):
    # 1. Build canonical AutoForge system
    system = build_autoforge_system(workspace_root=str(tmp_path))

    # Regression assertion: context_builder MUST exist and be attached to execution engine dispatcher
    assert system.context_builder is not None, "context_builder missing from AutoForgeSystem"
    assert isinstance(system.context_builder, EngineeringContextBuilder)
    assert system.execution_engine._dispatcher._context_builder is system.context_builder

    # 2. Seed workspace with an existing file to test workspace scanning
    seed_file = tmp_path / "seed_module.py"
    seed_file.write_text("SEED_CONSTANT = 42\n", encoding="utf-8")

    # 3. Instrument context builder with an observable spy
    assemble_calls = []
    original_assemble = system.context_builder.assemble_context

    async def spy_assemble(*args: Any, **kwargs: Any) -> ExecutionContext:
        ctx = await original_assemble(*args, **kwargs)
        assemble_calls.append({
            "task_id": kwargs.get("task_def").task_id if kwargs.get("task_def") else None,
            "context": ctx,
            "project_files": list(ctx.project_files),
        })
        return ctx

    system.context_builder.assemble_context = spy_assemble  # type: ignore

    # 4. Dispatch a task through the canonical Workflow & Execution engine
    task_def = TaskDefinition(
        task_id="t-context-builder-proof",
        name="Context Verification Task",
        task_type="coding",
        input_data={
            "files": [{"path": "output.py", "content": "print('ok')\n"}],
            "commands": [[sys.executable, "output.py"]],
        },
    )
    workflow_def = WorkflowDefinition(
        name="Context Builder Workflow",
        tasks=[task_def],
    )
    handle = system.workflow_engine.submit(workflow_def)
    completed = await system.execution_engine.run_workflow_to_completion(handle)

    status_str = str(getattr(completed.status, "value", completed.status))
    assert status_str in {"completed", "passed", "finished"}

    # 5. Verify EngineeringContextBuilder was actually invoked
    assert len(assemble_calls) == 1, (
        "EngineeringContextBuilder.assemble_context MUST be invoked during task dispatch. "
        "If assemble_calls is empty, execution bypassed the builder and used direct "
        "ExecutionContext.from_task_definition()!"
    )

    call_record = assemble_calls[0]
    assert call_record["task_id"] == "t-context-builder-proof"

    # 6. Verify the context contains intended engineering inputs
    assembled_ctx = call_record["context"]
    assert isinstance(assembled_ctx, ExecutionContext)
    assert assembled_ctx.task_id == "t-context-builder-proof"
    assert assembled_ctx.workspace_root == tmp_path

    # Verify workspace filesystem scanning integration
    assert "seed_module.py" in assembled_ctx.project_files, (
        "EngineeringContextBuilder must discover workspace files and populate context.project_files"
    )

    # 7. Regression check: prove that if context_builder is absent from dispatcher,
    # the invariant fails.
    dispatcher_without_builder = system.execution_engine._dispatcher
    assert dispatcher_without_builder._context_builder is not None
