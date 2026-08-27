"""
Unit tests for EngineeringWorker lifecycle.
"""

import sys
import pytest

from autoforge_workflows.models import TaskDefinition

from autoforge_execution.ai_adapter import AIInfrastructureAdapter
from autoforge_execution.context import ExecutionContext
from autoforge_execution.environment import WorkspaceEnvironment
from autoforge_execution.models import WorkerStatus, WorkerType
from autoforge_execution.worker import EngineeringWorker


@pytest.fixture
def worker_setup(tmp_path):
    env = WorkspaceEnvironment(tmp_path)
    ai = AIInfrastructureAdapter()
    worker = EngineeringWorker(
        worker_id="test-worker-1",
        worker_type=WorkerType.CODING,
        environment=env,
        ai_provider=ai,
    )
    return worker, env, ai


def test_worker_initial_state(worker_setup):
    worker, _, _ = worker_setup
    assert worker.worker_id == "test-worker-1"
    assert worker.worker_type == WorkerType.CODING
    assert worker.status == WorkerStatus.CREATED


def test_worker_prepare_transition(worker_setup):
    worker, _, _ = worker_setup
    worker.prepare("task-42", attempt_number=2)
    assert worker.status == WorkerStatus.READY
    assert worker.state.task_id == "task-42"
    assert worker.state.attempt_number == 2


@pytest.mark.asyncio
async def test_worker_execute_task_success(worker_setup):
    worker, env, _ = worker_setup
    
    task_def = TaskDefinition(
        task_id="task-test-success",
        name="Test Success Task",
        input_data={
            "files": [{"path": "hello.py", "content": "print('hello from worker')"}],
            "commands": [[sys.executable, "hello.py"]],
        },
    )
    context = ExecutionContext.from_task_definition(task_def, env.root)

    passed, artifacts, eval_res = await worker.execute_task(context)
    assert passed
    assert worker.status == WorkerStatus.COMPLETED
    assert len(artifacts) > 0
    assert eval_res is not None
    assert eval_res.passed
    assert worker.state.finished_at is not None


@pytest.mark.asyncio
async def test_worker_cancellation(worker_setup):
    worker, _, _ = worker_setup
    worker.prepare("task-cancel")
    worker.cancel("User cancelled task")

    assert worker.is_cancelled()
    assert worker.state.cancellation_requested
