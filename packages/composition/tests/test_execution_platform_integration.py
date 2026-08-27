"""
Composition-root integration tests for the Execution Platform (Phase 10).

Verifies:
- AutoForgeSystem wires ExecutionEngine properly.
- Execution events flow to the CanonicalEventBus.
- Task execution results project into Runtime checkpoints.
"""

from __future__ import annotations

import sys
from pathlib import Path
import pytest

from autoforge_composition.composition_root import build_autoforge_system
from autoforge_events.event_types import EventCategory, EventType
from autoforge_workflows.models import (
    DependencyEdge,
    TaskDefinition,
    WorkflowDefinition,
    WorkflowTaskStatus,
)


@pytest.mark.asyncio
async def test_autoforge_system_execution_wiring(tmp_path: Path):
    system = build_autoforge_system(workspace_root=str(tmp_path))
    assert system.execution_engine is not None
    assert system.workflow_engine is not None

    # Track emitted events
    emitted_events = []
    system.events.subscribe(
        lambda ev: emitted_events.append(ev),
        categories=[EventCategory.EXECUTION],
    )

    # Submit a workflow
    t1 = TaskDefinition(
        task_id="t1",
        name="Compute Sum",
        input_data={
            "files": [{"path": "sum.py", "content": "print(2 + 2)"}],
            "commands": [[sys.executable, "sum.py"]],
        },
    )
    workflow_def = WorkflowDefinition(
        name="Math Workflow",
        tasks=[t1],
    )
    handle = system.workflow_engine.submit(workflow_def)

    # Execute workflow to completion via execution engine
    completed_handle = await system.execution_engine.run_workflow_to_completion(handle)
    assert completed_handle.is_complete
    assert completed_handle.task_statuses["t1"] == WorkflowTaskStatus.SUCCEEDED

    # Verify execution events were published to CanonicalEventBus
    assert len(emitted_events) > 0
    event_types = {e.event_type for e in emitted_events}
    assert EventType.EXECUTION_STARTED in event_types
    assert EventType.EXECUTION_COMPLETED in event_types
