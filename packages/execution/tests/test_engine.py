"""
Integration tests for ExecutionEngine and WorkflowEngine coordination.
"""

import sys
import pytest

from autoforge_workflows.engine import WorkflowEngine
from autoforge_workflows.models import (
    DependencyEdge,
    TaskDefinition,
    WorkflowDefinition,
    WorkflowTaskStatus,
)

from autoforge_execution.ai_adapter import AIInfrastructureAdapter
from autoforge_execution.engine import ExecutionEngine
from autoforge_execution.environment import WorkspaceEnvironment


@pytest.fixture
def execution_system(tmp_path):
    env = WorkspaceEnvironment(tmp_path)
    wf_engine = WorkflowEngine()
    ai = AIInfrastructureAdapter()
    exec_engine = ExecutionEngine(
        environment=env,
        ai_provider=ai,
        workflow_engine=wf_engine,
    )
    return exec_engine, wf_engine, env


@pytest.mark.asyncio
async def test_execute_standalone_task_definition(execution_system):
    exec_engine, _, _ = execution_system
    task_def = TaskDefinition(
        task_id="standalone-t1",
        name="Standalone Task",
        input_data={
            "files": [{"path": "standalone.py", "content": "print('standalone execution')"}],
            "commands": [[sys.executable, "standalone.py"]],
        },
    )
    passed, artifacts, eval_res = await exec_engine.execute_task_definition(task_def)
    assert passed
    assert eval_res is not None
    assert eval_res.passed
    assert len(artifacts) > 0


@pytest.mark.asyncio
async def test_workflow_engine_full_execution(execution_system):
    exec_engine, wf_engine, env = execution_system

    t1 = TaskDefinition(
        task_id="step1",
        name="Step 1 Generate Data",
        input_data={
            "files": [{"path": "data.txt", "content": "42"}],
            "commands": [[sys.executable, "-c", "assert open('data.txt').read().strip() == '42'"]],
        },
    )
    t2 = TaskDefinition(
        task_id="step2",
        name="Step 2 Process Data",
        input_data={
            "files": [{"path": "process.py", "content": "print('data processed')"}],
            "commands": [[sys.executable, "process.py"]],
        },
    )

    workflow_def = WorkflowDefinition(
        name="Two Step Pipeline",
        tasks=[t1, t2],
        dependencies=[
            DependencyEdge(upstream_task_id="step1", downstream_task_id="step2"),
        ],
    )

    handle = wf_engine.submit(workflow_def)
    assert handle.status == "running"

    completed_handle = await exec_engine.run_workflow_to_completion(handle)
    assert completed_handle.is_complete
    assert completed_handle.task_statuses["step1"] == WorkflowTaskStatus.SUCCEEDED
    assert completed_handle.task_statuses["step2"] == WorkflowTaskStatus.SUCCEEDED
    assert completed_handle.progress == 100.0
