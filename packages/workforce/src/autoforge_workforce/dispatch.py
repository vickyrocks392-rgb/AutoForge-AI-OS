"""
Workforce Dispatcher matching specialized workers to tasks.
"""

from __future__ import annotations
import uuid
from typing import Any

from autoforge_execution.dispatcher import WorkerDispatcher
from autoforge_execution.errors import ConcurrencyLimitExceededError, DispatchError, WorkerNotFoundError
from autoforge_execution.models import WorkerStatus, WorkerType as BaseWorkerType, ArtifactRecord, EvaluationResult
from autoforge_execution.context import ExecutionContext
from autoforge_execution.environment import WorkspaceEnvironment
from autoforge_execution.ai_adapter import AIEngineeringProvider
from autoforge_execution.artifacts import ArtifactPipeline
from autoforge_execution.governance import ExecutionGovernance
from autoforge_execution.models import LoopConfig
from autoforge_workflows.models import TaskDefinition

from autoforge_workforce.registry import WORKER_REGISTRY
from autoforge_workforce.workers import WorkforceWorker

class WorkforceDispatcher(WorkerDispatcher):
    """
    Dispatcher that selects, instantiates, and executes tasks using specialized workforce workers.
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
        context_builder: Any | None = None,
    ) -> None:
        super().__init__(
            environment=environment,
            ai_provider=ai_provider,
            max_concurrent_workers=max_concurrent_workers,
            artifact_pipeline=artifact_pipeline,
            governance=governance,
            loop_config=loop_config,
            event_sink=event_sink,
            context_builder=context_builder,
        )
        self._workforce_workers: dict[str, WorkforceWorker] = {}
        self._workforce_counter = 0

    @property
    def active_worker_count(self) -> int:
        return len([w for w in self._workforce_workers.values() if w.status == WorkerStatus.RUNNING])

    def get_worker(self, worker_id: str) -> WorkforceWorker | None:
        return self._workforce_workers.get(worker_id)

    def create_specialized_worker(
        self,
        specialized_type: str,
        *,
        worker_id: str | None = None,
    ) -> WorkforceWorker:
        """
        Instantiate a specialized workforce worker.
        """
        if self.active_worker_count >= self._max_concurrent:
            raise ConcurrencyLimitExceededError(
                f"Cannot create worker: active worker count ({self.active_worker_count}) reached limit ({self._max_concurrent})"
            )

        worker_class = WORKER_REGISTRY.lookup(specialized_type)
        if not worker_class:
            raise DispatchError(f"Specialized worker type '{specialized_type}' is not registered.")

        if not worker_id:
            self._workforce_counter += 1
            worker_id = f"special_worker_{specialized_type}_{self._workforce_counter}_{uuid.uuid4().hex[:6]}"

        # Instantiate specialized worker subclass
        worker = worker_class(
            environment=self._env,
            ai_provider=self._ai,
            artifact_pipeline=self._artifacts,
            governance=self._governance,
            loop_config=self._loop_config,
            event_sink=self._event_sink,
            worker_id=worker_id,
        )

        self._workforce_workers[worker_id] = worker
        return worker

    async def dispatch_task(
        self,
        task_def: TaskDefinition,
        *,
        workflow_id: uuid.UUID | None = None,
        correlation_id: uuid.UUID | None = None,
        attempt_number: int = 1,
        worker_type: str | None = None,
    ) -> tuple[bool, list[ArtifactRecord], EvaluationResult | None, WorkforceWorker]:
        """
        Dispatch a task definition to a specialized worker and run it.
        """
        # Resolve target worker type
        if WORKER_REGISTRY.lookup(task_def.task_type):
            target_type = task_def.task_type
        else:
            w_candidate = worker_type.value if hasattr(worker_type, "value") else worker_type
            if w_candidate and WORKER_REGISTRY.lookup(w_candidate):
                target_type = w_candidate
            elif task_def.task_type == "architecture":
                target_type = "architecture_engineer"
            elif task_def.task_type in {"review", "qa", "testing"}:
                target_type = "qa_engineer"
            elif task_def.task_type in {"research", "plan", "planning"}:
                target_type = "research_engineer"
            else:
                target_type = "backend_engineer"

        # Deterministic capability matching / task compatibility validation
        if not WORKER_REGISTRY.check_task_compatibility(target_type, task_def.task_type):
            raise DispatchError(f"Worker type '{target_type}' is not compatible with task type '{task_def.task_type}'")

        # Check permissions before instantiating/running
        expertise = WORKER_REGISTRY.get_expertise(target_type)
        if expertise and not WORKER_REGISTRY.validate_permission(target_type, "read", "fs"):
            raise DispatchError(f"Worker type '{target_type}' lacks required filesystem permissions.")

        # Create worker
        worker = self.create_specialized_worker(specialized_type=target_type)

        # Resolve effective model requirements from worker profile + task requirements
        from autoforge_workforce.capabilities import resolve_effective_requirements
        task_model_reqs = task_def.input_data.get("model_requirements") or task_def.metadata.get("model_requirements")
        effective_reqs = resolve_effective_requirements(worker.model_profile, task_model_reqs)

        if self._context_builder is not None and hasattr(self._context_builder, "assemble_context"):
            context = await self._context_builder.assemble_context(
                task_def=task_def,
                workspace_root=self._env.root,
                workflow_id=workflow_id,
                correlation_id=correlation_id,
                attempt_number=attempt_number,
                effective_model_requirements=effective_reqs.to_dict(),
            )
        else:
            context = ExecutionContext.from_task_definition(
                task_def=task_def,
                workspace_root=self._env.root,
                workflow_id=workflow_id,
                correlation_id=correlation_id,
                attempt_number=attempt_number,
                effective_model_requirements=effective_reqs.to_dict(),
            )

        passed, artifacts, eval_res = await worker.execute_task(context)
        return passed, artifacts, eval_res, worker
