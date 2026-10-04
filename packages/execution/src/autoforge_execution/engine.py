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
from enum import Enum
import logging
import time

logger = logging.getLogger("autoforge.execution.engine")
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
from autoforge_execution.durable import DurableExecutionRecorder
from autoforge_execution.environment import WorkspaceEnvironment
from autoforge_execution.events import EventSinkProtocol, ExecutionEvents
from autoforge_execution.governance import ExecutionGovernance
from autoforge_execution.models import (
    RAGRetrievalEngine,
    ArtifactRecord,
    EvaluationResult,
    LoopConfig,
    WorkerType,
)

#: Durable boundary written once a dispatched work unit finished running but
#: *before* its outcome is committed. A crash between the two leaves durable
#: evidence that the unit ran without claiming its outcome was committed.
DISPATCH_BOUNDARY_LABEL = "dispatch-completed"


class RuntimeFacadeProtocol(Protocol):
    """Protocol for recording execution state into Runtime."""

    def record_task_state(self, task_id: str, state: dict[str, Any]) -> None:
        ...

    def record_workflow_state(self, workflow_id: uuid.UUID, state: dict[str, Any]) -> None:
        ...


class DurabilityPolicy(str, Enum):
    """Policy for handling failures in the durable execution persistence path."""
    FAIL_CLOSED = "fail_closed"
    DEGRADED = "degraded"


class DurabilityPersistenceError(Exception):
    """Raised when durable execution persistence operations fail."""


@dataclass
class ExecutionEngineConfig:
    """Configuration options for the ExecutionEngine."""

    max_concurrent_workers: int = 4
    default_loop_config: LoopConfig = field(default_factory=LoopConfig)
    auto_checkpoint: bool = True
    durable_recorder: DurableExecutionRecorder | None = None
    durability_policy: DurabilityPolicy = DurabilityPolicy.FAIL_CLOSED
    """Policy controlling whether persistence failures fail-closed or degrade observably."""

    #: Phase 19 wiring closure: the certified ``ActiveLearningResolver``.
    #: ``None`` (the default) means learning is disabled and every execution is
    #: byte-for-byte pre-learning behaviour. It is injected by
    #: ``composition_root.build_autoforge_system()`` and is *read-only*.
    learning_resolver: Any | None = None
    #: The learnable decision point the resolver is consulted for. One of the
    #: bounded ``LEARNABLE_TARGETS``; never an authority surface.
    learning_target: str = "prompt_strategy"
    #: ``(kind, key)`` identifying which active learning pointer applies.
    learning_kind: str = "pattern_template"
    learning_key: str = "default"



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
        rag_engine: RAGRetrievalEngine | None = None,
    ) -> None:
        self._env = environment
        self._ai = ai_provider or AIInfrastructureAdapter()
        self._workflow_engine = workflow_engine
        self._config = config or ExecutionEngineConfig()
        self._event_sink = event_sink
        self._runtime_facade = runtime_facade
        self._rag_engine = rag_engine

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
            rag_engine=self._rag_engine,
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

    @property
    def learning_resolver(self) -> Any | None:
        """The injected production ``ActiveLearningResolver``, if wired.

        Exposed so the composition root and integration tests can assert the
        *real* production object graph contains it. The resolver itself is
        read-only; the engine gains no authority through it.
        """
        return self._config.learning_resolver

    def set_learning_resolver(
        self,
        resolver: Any | None,
        *,
        target: str | None = None,
        kind: str | None = None,
        key: str | None = None,
    ) -> None:
        """Inject the production learning resolver (Phase 19 wiring closure).

        Called by ``composition_root`` after the certified SecurityPlatform and
        durable learning store exist. This is a *read-only* reference: the engine
        gains no authority, and the resolver itself cannot promote, approve,
        activate, roll back or grant anything. Injecting ``None`` restores the
        exact pre-learning behaviour.
        """
        if resolver is None:
            # Explicitly disabling learning must actually clear it, so the
            # "learning disabled" path is real rather than a no-op.
            self._config.learning_resolver = None
            return
        self._config.learning_resolver = resolver
        if target is not None:
            self._config.learning_target = target
        if kind is not None:
            self._config.learning_kind = kind
        if key is not None:
            self._config.learning_key = key

    def resolve_learning(self, project_id: uuid.UUID) -> Any | None:
        """Consult the production learning resolver for one execution.

        Returns the resolver's ``ProductionResolution``, or ``None`` when
        learning is disabled (no resolver wired). Never raises: the certified
        Phase 19 contract is that every failure degrades to baseline behaviour,
        so a learning outage can never stop engineering execution.
        """
        resolver = self._config.learning_resolver
        if resolver is None:
            return None
        return resolver.resolve(
            project_id=project_id,
            kind=self._config.learning_kind,
            key=self._config.learning_key,
            target=self._config.learning_target,
        )

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

        # ── Durable execution identity (Phase 18-J.2) ────────────────────
        # The work unit (workflow + task) IS the logical execution: identity
        # is derived from that key, so a retry (attempt 2, 3, ...) extends
        # the same execution instead of minting a new one. The durable start
        # is committed BEFORE dispatch, and the outcome events below are
        # published only AFTER their durable commit — durable state is
        # authoritative, events are derived publications.
        recorder = self._config.durable_recorder
        durable_state = None
        if recorder is not None and workflow_id is not None:
            try:
                durable_state = recorder.begin_execution(
                    workflow_id=workflow_id,
                    task_id=task_def.task_id,
                    correlation_id=correlation_id,
                    attempt_number=attempt_number,
                    worker_type=worker_type.value if hasattr(worker_type, "value") else str(worker_type),
                    max_attempts=getattr(task_def.retry_policy, "max_attempts", None),
                    metadata={"project_id": str(project_id)},
                )
                if durable_state is not None:
                    execution_id = durable_state.execution_id
            except Exception as ex:
                logger.error("Durable execution begin_execution failed: %s", ex, exc_info=True)
                if self._config.durability_policy == DurabilityPolicy.FAIL_CLOSED:
                    self._events.emit_execution_failed(
                        execution_id=execution_id,
                        task_id=task_uuid,
                        project_id=project_id,
                        error_code="DURABILITY_PERSISTENCE_FAILURE",
                        error_message=f"Durable execution recording failed: {ex}",
                        duration_seconds=time.perf_counter() - start_time,
                        correlation_id=correlation_id,
                    )
                    raise DurabilityPersistenceError(f"Durable execution recording failed: {ex}") from ex
                else:
                    task_def.metadata["durability_status"] = "DEGRADED"
                    task_def.metadata["durability_error"] = str(ex)
                    durable_state = None

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

        # ── Durable boundary: the unit ran, its outcome is not yet committed
        if recorder is not None and durable_state is not None:
            try:
                recorder.record_checkpoint(
                    durable_state.execution_id,
                    label=DISPATCH_BOUNDARY_LABEL,
                    boundary_state={
                        "attempt_number": attempt_number,
                        "worker_id": worker.worker_id if hasattr(worker, "worker_id") else None,
                        "ran_to_completion": True,
                    },
                    created_by="execution_engine",
                )
            except Exception as ex:
                logger.error("Durable execution record_checkpoint failed: %s", ex, exc_info=True)
                if self._config.durability_policy == DurabilityPolicy.FAIL_CLOSED:
                    raise DurabilityPersistenceError(f"Durable checkpoint recording failed: {ex}") from ex
                task_def.metadata["durability_status"] = "DEGRADED"

        duration = time.perf_counter() - start_time
        art_ids = [a.artifact_id for a in artifacts]

        if passed:
            # Durable commit FIRST, then the derived event publication.
            if recorder is not None and durable_state is not None:
                try:
                    recorder.complete_attempt(
                        durable_state.execution_id,
                        result={
                            "artifact_ids": art_ids,
                            "duration_seconds": duration,
                        },
                    )
                except Exception as ex:
                    logger.error("Durable execution complete_attempt failed: %s", ex, exc_info=True)
                    if self._config.durability_policy == DurabilityPolicy.FAIL_CLOSED:
                        raise DurabilityPersistenceError(f"Durable complete_attempt recording failed: {ex}") from ex
                    task_def.metadata["durability_status"] = "DEGRADED"
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
            # A retryable task failure keeps the logical execution running so
            # the workflow engine's next retry continues the SAME execution;
            # the workflow-level terminal-failure reconciliation belongs to a
            # later phase (18-J.3).
            if recorder is not None and durable_state is not None:
                try:
                    max_attempts = getattr(task_def.retry_policy, "max_attempts", None)
                    retryable = max_attempts is None or attempt_number < max_attempts
                    recorder.fail_attempt(
                        durable_state.execution_id,
                        error_code=worker.state.last_error_code or "TASK_FAILED",
                        error_message=err_msg,
                        retryable=retryable,
                        result={"duration_seconds": duration},
                    )
                except Exception as ex:
                    logger.error("Durable execution fail_attempt failed: %s", ex, exc_info=True)
                    if self._config.durability_policy == DurabilityPolicy.FAIL_CLOSED:
                        raise DurabilityPersistenceError(f"Durable fail_attempt recording failed: {ex}") from ex
                    task_def.metadata["durability_status"] = "DEGRADED"
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
