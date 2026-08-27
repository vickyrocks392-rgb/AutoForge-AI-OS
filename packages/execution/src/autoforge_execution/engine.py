"""
Execution Engine — central orchestrator for the Execution Platform (Phase 10).

Coordinates:
- Worker Dispatcher
- Worker Lifecycle
- Engineering Loop
- Execution Environment
- Artifact Pipeline
- Workflow Engine Integration
- Runtime State Integration
- Canonical Event Emission
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from autoforge_workflows.engine import WorkflowEngine, WorkflowHandle
from autoforge_workflows.models import TaskDefinition, WorkflowTaskStatus
from autoforge_workflows.queue import QueueEntry

from autoforge_execution.ai_adapter import AIEngineeringProvider, AIInfrastructureAdapter
from autoforge_execution.artifacts import ArtifactPipeline
from autoforge_execution.dispatcher import WorkerDispatcher
from autoforge_execution.environment import WorkspaceEnvironment
from autoforge_execution.events import EventSinkProtocol, ExecutionEvents
from autoforge_execution.governance import ExecutionGovernance
from autoforge_execution.models import (
    ArtifactRecord,
    EvaluationResult,
    LoopConfig,
    WorkerType,
)


class RuntimeFacadeProtocol(Protocol):
    """Protocol for recording execution state into Runtime."""

    def record_task_state(self, task_id: str, state: dict[str, Any]) -> None:
        ...

    def record_workflow_state(self, workflow_id: uuid.UUID, state: dict[str, Any]) -> None:
        ...


@dataclass
class ExecutionEngineConfig:
    """Configuration options for the ExecutionEngine."""

    max_concurrent_workers: int = 4
    default_loop_config: LoopConfig = field(default_factory=LoopConfig)
    auto_checkpoint: bool = True


class ExecutionEngine:
    """
    Coordinates engineering execution across workers, connectors, and workflows.
    """

    def __init__(
        self,
        environment: WorkspaceEnvironment,
        *,
        ai_provider: AIEngineeringProvider | None = None,
        workflow_engine: WorkflowEngine | None = None,
        config: ExecutionEngineConfig | None = None,
        artifact_pipeline: ArtifactPipeline | None = None,
        governance: ExecutionGovernance | None = None,
        event_sink: EventSinkProtocol | None = None,
        runtime_facade: RuntimeFacadeProtocol | None = None,
    ) -> None:
        self._env = environment
        self._ai = ai_provider or AIInfrastructureAdapter()
        self._workflow_engine = workflow_engine
        self._config = config or ExecutionEngineConfig()
        self._event_sink = event_sink
        self._runtime_facade = runtime_facade

        self._artifacts = artifact_pipeline or ArtifactPipeline(event_sink)
        self._governance = governance or ExecutionGovernance()
        self._events = ExecutionEvents(event_sink)

        self._dispatcher = WorkerDispatcher(
            environment=self._env,
            ai_provider=self._ai,
            max_concurrent_workers=self._config.max_concurrent_workers,
            artifact_pipeline=self._artifacts,
            governance=self._governance,
            loop_config=self._config.default_loop_config,
            event_sink=self._event_sink,
        )

    @property
    def environment(self) -> WorkspaceEnvironment:
        return self._env

    @property
    def dispatcher(self) -> WorkerDispatcher:
        return self._dispatcher

    @property
    def artifacts(self) -> ArtifactPipeline:
        return self._artifacts

    @property
    def governance(self) -> ExecutionGovernance:
        return self._governance

    async def execute_task_definition(
        self,
        task_def: TaskDefinition,
        *,
        workflow_id: uuid.UUID | None = None,
        correlation_id: uuid.UUID | None = None,
        attempt_number: int = 1,
        worker_type: WorkerType = WorkerType.CODING,
    ) -> tuple[bool, list[ArtifactRecord], EvaluationResult | None]:
        """
        Execute a standalone TaskDefinition through an autonomous engineering worker.
        """
        execution_id = uuid.uuid4()
        task_uuid = uuid.uuid4()
        project_id = workflow_id or uuid.uuid4()
        start_time = time.perf_counter()

        self._events.emit_execution_started(
            execution_id=execution_id,
            task_id=task_uuid,
            project_id=project_id,
            input_data=task_def.input_data,
            max_duration_seconds=self._config.default_loop_config.timeout_seconds,
            correlation_id=correlation_id,
        )

        passed, artifacts, eval_res, worker = await self._dispatcher.dispatch_task(
            task_def=task_def,
            workflow_id=workflow_id,
            correlation_id=correlation_id,
            attempt_number=attempt_number,
            worker_type=worker_type,
        )

        duration = time.perf_counter() - start_time
        art_ids = [a.artifact_id for a in artifacts]

        if passed:
            self._events.emit_execution_completed(
                execution_id=execution_id,
                task_id=task_uuid,
                project_id=project_id,
                duration_seconds=duration,
                artifact_ids=art_ids,
                correlation_id=correlation_id,
            )
        else:
            err_msg = worker.state.last_error_message or "Task execution failed"
            self._events.emit_execution_failed(
                execution_id=execution_id,
                task_id=task_uuid,
                project_id=project_id,
                error_code=worker.state.last_error_code or "TASK_FAILED",
                error_message=err_msg,
                duration_seconds=duration,
                correlation_id=correlation_id,
            )

        # Record to Runtime if facade provided
        if self._runtime_facade:
            try:
                self._runtime_facade.record_task_state(task_def.task_id, worker.state.to_snapshot())
            except Exception:
                pass

        return passed, artifacts, eval_res

    async def execute_ready_workflow_tasks(
        self,
        handle: WorkflowHandle,
        dispatches: list[QueueEntry],
    ) -> list[tuple[str, bool, list[ArtifactRecord], EvaluationResult | None]]:
        """
        Execute a batch of dispatched tasks from a WorkflowEngine tick and report outcomes back.
        """
        if not self._workflow_engine:
            raise ValueError("WorkflowEngine must be attached to execute workflow tasks")

        results = []
        pending_queue = list(dispatches)

        while pending_queue:
            entry = pending_queue.pop(0)
            task_state = handle.get_task_state(entry.task_id)
            if not task_state:
                continue

            # Transition task to RUNNING before execution
            if task_state.status == WorkflowTaskStatus.READY:
                task_state.status = WorkflowTaskStatus.RUNNING
                task_state.started_at = datetime.now(timezone.utc)
                task_state.attempt_number += 1

            passed, artifacts, eval_res = await self.execute_task_definition(
                task_def=task_state.definition,
                workflow_id=handle.workflow_id,
                correlation_id=task_state.correlation_id,
                attempt_number=task_state.attempt_number,
            )

            # Report outcome back to WorkflowEngine
            if passed:
                decision = self._workflow_engine.report_task_success(
                    workflow_id=handle.workflow_id,
                    task_id=entry.task_id,
                    result={"artifacts": [str(a.artifact_id) for a in artifacts]},
                )
                if decision.dispatch:
                    pending_queue.extend(decision.dispatch)
            else:
                decision = self._workflow_engine.report_task_failure(
                    workflow_id=handle.workflow_id,
                    task_id=entry.task_id,
                    error_code="EXECUTION_FAILED",
                    error_message=eval_res.failures[0] if (eval_res and eval_res.failures) else "Execution failed",
                )
                if decision.dispatch:
                    pending_queue.extend(decision.dispatch)

            results.append((entry.task_id, passed, artifacts, eval_res))

        return results

    async def run_workflow_to_completion(
        self,
        handle: WorkflowHandle,
        *,
        max_ticks: int = 100,
    ) -> WorkflowHandle:
        """
        Execute an entire workflow until terminal state (COMPLETED or FAILED).
        """
        if not self._workflow_engine:
            raise ValueError("WorkflowEngine must be attached to execute workflow tasks")

        tick_count = 0
        while not handle.is_complete and not handle.is_failed and not handle.is_paused and tick_count < max_ticks:
            tick_count += 1
            decision = self._workflow_engine.tick(handle.workflow_id)
            dispatches = list(decision.dispatch)

            # Check if any tasks were pre-dispatched into RUNNING or READY during submission
            if not dispatches:
                for tid, ts in handle._task_states.items():
                    if ts.status in {WorkflowTaskStatus.RUNNING, WorkflowTaskStatus.READY}:
                        dispatches.append(
                            QueueEntry.create(
                                task_id=tid,
                                workflow_id=str(handle.workflow_id),
                                priority=ts.definition.priority,
                                sequence=0,
                            )
                        )

            if dispatches:
                await self.execute_ready_workflow_tasks(handle, dispatches)
            else:
                if handle.is_complete or handle.is_failed or handle.is_paused:
                    break
                await asyncio.sleep(0.01)

        return handle
