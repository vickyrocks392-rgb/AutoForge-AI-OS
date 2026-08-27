"""
Worker Dispatcher — coordinates dispatching workflow tasks to engineering workers.

Responsibilities:
- Accept eligible tasks (QueueEntry) from WorkflowEngine / WorkflowScheduler.
- Instantiate or select suitable engineering worker instances.
- Enforce concurrency constraints (bounded parallel workers).
- Preserve task, workflow, and correlation identities.
- Propagate cancellation signals.
- Report task outcomes back to the WorkflowEngine.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any, Callable

from autoforge_workflows.engine import WorkflowEngine
from autoforge_workflows.models import TaskDefinition
from autoforge_workflows.queue import QueueEntry

from autoforge_execution.ai_adapter import AIEngineeringProvider
from autoforge_execution.artifacts import ArtifactPipeline
from autoforge_execution.context import ExecutionContext
from autoforge_execution.environment import WorkspaceEnvironment
from autoforge_execution.errors import (
    ConcurrencyLimitExceededError,
    DispatchError,
    WorkerNotFoundError,
)
from autoforge_execution.governance import ExecutionGovernance
from autoforge_execution.models import (
    ArtifactRecord,
    EvaluationResult,
    LoopConfig,
    WorkerStatus,
    WorkerType,
)
from autoforge_execution.worker import EngineeringWorker


class WorkerDispatcher:
    """
    Dispatches workflow tasks to worker instances and tracks active executions.
    """

    def __init__(
        self,
        environment: WorkspaceEnvironment,
        ai_provider: AIEngineeringProvider,
        *,
        max_concurrent_workers: int = 4,
        artifact_pipeline: ArtifactPipeline | None = None,
        governance: ExecutionGovernance | None = None,
        loop_config: LoopConfig | None = None,
        event_sink: Any = None,
    ) -> None:
        self._env = environment
        self._ai = ai_provider
        self._max_concurrent = max_concurrent_workers
        self._artifacts = artifact_pipeline or ArtifactPipeline(event_sink)
        self._governance = governance or ExecutionGovernance()
        self._loop_config = loop_config or LoopConfig()
        self._event_sink = event_sink

        self._active_workers: dict[str, EngineeringWorker] = {}
        self._worker_counter = 0

    @property
    def active_worker_count(self) -> int:
        return len([w for w in self._active_workers.values() if w.status == WorkerStatus.RUNNING])

    @property
    def max_concurrent_workers(self) -> int:
        return self._max_concurrent

    def get_worker(self, worker_id: str) -> EngineeringWorker | None:
        return self._active_workers.get(worker_id)

    def create_worker(
        self,
        worker_type: WorkerType = WorkerType.CODING,
        *,
        worker_id: str | None = None,
    ) -> EngineeringWorker:
        """
        Instantiate and register a new worker.
        """
        if self.active_worker_count >= self._max_concurrent:
            raise ConcurrencyLimitExceededError(
                f"Cannot create worker: active worker count ({self.active_worker_count}) reached limit ({self._max_concurrent})",
                details={"active": self.active_worker_count, "limit": self._max_concurrent},
            )

        if not worker_id:
            self._worker_counter += 1
            worker_id = f"worker_{worker_type.value}_{self._worker_counter}_{uuid.uuid4().hex[:6]}"

        worker = EngineeringWorker(
            worker_id=worker_id,
            worker_type=worker_type,
            environment=self._env,
            ai_provider=self._ai,
            artifact_pipeline=self._artifacts,
            governance=self._governance,
            loop_config=self._loop_config,
            event_sink=self._event_sink,
        )
        self._active_workers[worker_id] = worker
        return worker

    async def dispatch_task(
        self,
        task_def: TaskDefinition,
        *,
        workflow_id: uuid.UUID | None = None,
        correlation_id: uuid.UUID | None = None,
        attempt_number: int = 1,
        worker_type: WorkerType | None = None,
    ) -> tuple[bool, list[ArtifactRecord], EvaluationResult | None, EngineeringWorker]:
        """
        Dispatch a task definition to an engineering worker and run it.
        """
        # Map task type string to WorkerType
        w_type = worker_type or WorkerType.CODING
        if task_def.task_type in {"review", "qa"}:
            w_type = WorkerType.REVIEW
        elif task_def.task_type in {"research", "plan"}:
            w_type = WorkerType.RESEARCH

        worker = self.create_worker(worker_type=w_type)

        context = ExecutionContext.from_task_definition(
            task_def=task_def,
            workspace_root=self._env.root,
            workflow_id=workflow_id,
            correlation_id=correlation_id,
            attempt_number=attempt_number,
        )

        passed, artifacts, eval_res = await worker.execute_task(context)
        return passed, artifacts, eval_res, worker

    def cancel_worker(self, worker_id: str, reason: str = "Cancelled by dispatcher") -> None:
        worker = self._active_workers.get(worker_id)
        if not worker:
            raise WorkerNotFoundError(f"Worker '{worker_id}' not found")
        worker.cancel(reason)

    def cancel_all(self, reason: str = "Dispatcher cancelled all active workers") -> None:
        for worker in list(self._active_workers.values()):
            if worker.status == WorkerStatus.RUNNING:
                worker.cancel(reason)
