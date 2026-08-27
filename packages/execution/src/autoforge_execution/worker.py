"""
Engineering Worker — manages worker lifecycle and coordinates the engineering loop.

Transitions:
  CREATED → READY → RUNNING → COMPLETED | FAILED | CANCELLED | WAITING_APPROVAL
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import uuid
from typing import Any, Callable

from autoforge_workflows.models import TaskDefinition

from autoforge_execution.ai_adapter import AIEngineeringProvider
from autoforge_execution.artifacts import ArtifactPipeline
from autoforge_execution.context import ExecutionContext
from autoforge_execution.environment import WorkspaceEnvironment
from autoforge_execution.errors import WorkerCancelledError, WorkerError
from autoforge_execution.governance import ExecutionGovernance
from autoforge_execution.loop import EngineeringLoop
from autoforge_execution.models import (
    ArtifactRecord,
    EvaluationResult,
    LoopConfig,
    WorkerState,
    WorkerStatus,
    WorkerType,
)


class EngineeringWorker:
    """
    An autonomous engineering worker executing assigned workflow tasks.
    """

    def __init__(
        self,
        worker_id: str,
        worker_type: WorkerType,
        environment: WorkspaceEnvironment,
        ai_provider: AIEngineeringProvider,
        *,
        artifact_pipeline: ArtifactPipeline | None = None,
        governance: ExecutionGovernance | None = None,
        loop_config: LoopConfig | None = None,
        event_sink: Any = None,
    ) -> None:
        self._worker_id = worker_id
        self._worker_type = worker_type
        self._env = environment
        self._ai = ai_provider
        self._artifacts = artifact_pipeline or ArtifactPipeline(event_sink)
        self._governance = governance or ExecutionGovernance()
        self._loop_config = loop_config or LoopConfig()
        self._event_sink = event_sink

        self._state = WorkerState(
            worker_id=worker_id,
            worker_type=worker_type,
            task_id="",
            status=WorkerStatus.CREATED,
        )
        self._cancellation_flag = False

    @property
    def worker_id(self) -> str:
        return self._worker_id

    @property
    def worker_type(self) -> WorkerType:
        return self._worker_type

    @property
    def state(self) -> WorkerState:
        return self._state

    @property
    def status(self) -> WorkerStatus:
        return self._state.status

    def prepare(
        self,
        task_id: str,
        *,
        workflow_id: uuid.UUID | None = None,
        correlation_id: uuid.UUID | None = None,
        attempt_number: int = 1,
    ) -> None:
        """
        Transition worker from CREATED to READY for a specific task.
        """
        if self._state.status != WorkerStatus.CREATED:
            raise WorkerError(
                f"Worker '{self._worker_id}' cannot prepare from status '{self._state.status.value}'"
            )
        self._state.task_id = task_id
        self._state.workflow_id = workflow_id
        self._state.correlation_id = correlation_id
        self._state.attempt_number = attempt_number
        self._state.status = WorkerStatus.READY

    def cancel(self, reason: str = "Execution cancelled") -> None:
        """
        Signal cancellation to the running worker.
        """
        self._cancellation_flag = True
        self._state.cancellation_requested = True
        if self._state.status == WorkerStatus.RUNNING:
            self._state.status = WorkerStatus.CANCELLED
            self._state.last_error_message = reason
            self._state.finished_at = datetime.now(timezone.utc)

    def is_cancelled(self) -> bool:
        return self._cancellation_flag

    async def execute_task(
        self,
        context: ExecutionContext,
    ) -> tuple[bool, list[ArtifactRecord], EvaluationResult | None]:
        """
        Run the worker through its engineering loop on the given task context.
        """
        if self._state.status != WorkerStatus.READY:
            self.prepare(
                context.task_id,
                workflow_id=context.workflow_id,
                correlation_id=context.correlation_id,
                attempt_number=context.attempt_number,
            )

        self._state.status = WorkerStatus.RUNNING
        self._state.started_at = datetime.now(timezone.utc)

        # Build loop
        loop = EngineeringLoop(
            environment=self._env,
            ai_provider=self._ai,
            artifact_pipeline=self._artifacts,
            governance=self._governance,
            config=self._loop_config,
            on_iteration_callback=self._on_loop_iteration,
        )

        try:
            passed, artifacts, last_eval = await loop.run(
                context=context,
                worker_id=self._worker_id,
                is_cancelled=self.is_cancelled,
            )
            self._state.produced_artifacts.extend(artifacts)
            self._state.last_evaluation = last_eval
            self._state.finished_at = datetime.now(timezone.utc)

            if self._cancellation_flag:
                self._state.status = WorkerStatus.CANCELLED
            elif passed:
                self._state.status = WorkerStatus.COMPLETED
            else:
                self._state.status = WorkerStatus.FAILED
                if last_eval and last_eval.failures:
                    self._state.last_error_message = "; ".join(last_eval.failures[:3])

            return passed, artifacts, last_eval

        except Exception as exc:
            self._state.status = WorkerStatus.FAILED
            self._state.last_error_message = str(exc)
            self._state.finished_at = datetime.now(timezone.utc)
            raise

    def _on_loop_iteration(self, iteration_record: Any) -> None:
        self._state.current_iteration = iteration_record.iteration
        self._state.iteration_history.append(iteration_record)
        if iteration_record.diagnosis:
            self._state.last_diagnosis = iteration_record.diagnosis
