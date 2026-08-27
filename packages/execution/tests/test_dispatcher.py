"""
Unit tests for WorkerDispatcher.
"""

import sys
import pytest

from autoforge_workflows.models import TaskDefinition

from autoforge_execution.ai_adapter import AIInfrastructureAdapter
from autoforge_execution.dispatcher import WorkerDispatcher
from autoforge_execution.environment import WorkspaceEnvironment
from autoforge_execution.errors import ConcurrencyLimitExceededError, WorkerNotFoundError
from autoforge_execution.models import WorkerStatus, WorkerType


@pytest.fixture
def dispatcher_setup(tmp_path):
    env = WorkspaceEnvironment(tmp_path)
    ai = AIInfrastructureAdapter()
    dispatcher = WorkerDispatcher(
        environment=env,
        ai_provider=ai,
        max_concurrent_workers=2,
    )
    return dispatcher, env


def test_dispatcher_create_worker(dispatcher_setup):
    dispatcher, _ = dispatcher_setup
    w1 = dispatcher.create_worker(WorkerType.CODING)
    assert w1.worker_id in dispatcher._active_workers
    assert dispatcher.get_worker(w1.worker_id) == w1


def test_dispatcher_concurrency_limit(dispatcher_setup):
    dispatcher, _ = dispatcher_setup
    w1 = dispatcher.create_worker(WorkerType.CODING)
    w2 = dispatcher.create_worker(WorkerType.TESTING)

    # Set both to RUNNING
    w1.state.status = WorkerStatus.RUNNING
    w2.state.status = WorkerStatus.RUNNING

    with pytest.raises(ConcurrencyLimitExceededError):
        dispatcher.create_worker(WorkerType.GENERAL)


@pytest.mark.asyncio
async def test_dispatcher_dispatch_task(dispatcher_setup):
    dispatcher, env = dispatcher_setup
    task_def = TaskDefinition(
        task_id="dispatch-t1",
        name="Dispatch Task",
        input_data={
            "files": [{"path": "msg.py", "content": "print('dispatched')"}],
            "commands": [[sys.executable, "msg.py"]],
        },
    )
    passed, artifacts, eval_res, worker = await dispatcher.dispatch_task(task_def)
    assert passed
    assert worker.status == WorkerStatus.COMPLETED
    assert len(artifacts) > 0


def test_dispatcher_cancel_all(dispatcher_setup):
    dispatcher, _ = dispatcher_setup
    w1 = dispatcher.create_worker(WorkerType.CODING)
    w1.state.status = WorkerStatus.RUNNING

    dispatcher.cancel_all("System shutdown")
    assert w1.status == WorkerStatus.CANCELLED
