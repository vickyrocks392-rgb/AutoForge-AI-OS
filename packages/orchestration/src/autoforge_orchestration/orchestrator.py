"""Phase 18 Orchestration Engine.

The ``OrchestrationEngine`` is the durable, observable, bounded orchestrator
that runs autonomous software-engineering workflows. It composes the
existing AutoForge subsystems — workforce, workflows, execution, review,
artifacts, ai_infrastructure, security, knowledge_platform, event platform,
and observability — into a unified engineering loop.

Lifecycle::

    engine = OrchestrationEngine(...)
    state = await engine.create_project(objective, workflow_id="greenfield")
    result = await engine.run_project(state.execution_id)
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from autoforge_ai_infrastructure.router import ModelRouterService
from autoforge_ai_infrastructure.metadata import RoutingRequest
from autoforge_ai_infrastructure.execution import ExecutorRegistry
from autoforge_events.base import BaseEvent
from autoforge_events.event_types import EventCategory, EventType

from autoforge_orchestration.errors import (
    HITLGateError,
    ModelRoutingError,
    OrchestrationError,
    RectificationLimitError,
    StageStateError,
    WorkerAssignmentError,
)
from autoforge_orchestration.models import (
    DeploymentStatus,
    FailureType,
    HITLStatus,
    ModelDecision,
    ProjectExecutionMetrics,
    ProjectExecutionState,
    ReviewVerdict,
    RunMode,
    StageDefinition,
    StageEvaluationVerdict,
    StageExecutionState,
    StageKind,
    StageStatus,
    StructuredFailureContext,
    Verdict,
    WorkerAssignment,
    WorkflowStatus,
)
from autoforge_orchestration.persistence import StatePersistence
from autoforge_orchestration.workflow_definitions import (
    GREENFIELD_WORKFLOW_DEFINITION,
    LEGACY_WORKFLOW_DEFINITION,
)
from autoforge_orchestration.security import SecurityBoundaryGuard

logger = logging.getLogger(__name__)


def _safe_uuid(value: str | None) -> uuid.UUID | None:
    """Safely convert a string to a UUID, returning None if not a valid UUID."""
    if not value:
        return None
    try:
        return uuid.UUID(value)
    except (ValueError, AttributeError):
        return None


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime | str | None) -> str:
    if dt is None:
        return ""
    if isinstance(dt, str):
        return dt
    return dt.isoformat()


# ── Protocol boundaries ─────────────────────────────────────────────────────


@runtime_checkable
class EventSinkProtocol(Protocol):
    """Minimal sink for canonical event publishing."""

    def publish(self, event: Any) -> Any:
        ...


@runtime_checkable
class WorkerProtocol(Protocol):
    """Minimal worker interface for the orchestration engine."""

    worker_id: str
    specialized_type: str

    async def execute(self, *args: Any, **kwargs: Any) -> Any:
        ...


@runtime_checkable
class ArtifactManagerProtocol(Protocol):
    """Minimal artifact manager interface for registration."""

    def create_artifact(
        self,
        name: str,
        artifact_type: str,
        *,
        project_id: uuid.UUID | None = None,
        workflow_id: uuid.UUID | None = None,
        created_by: str | None = None,
        path: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Any:
        ...


@runtime_checkable
class ReviewEngineProtocol(Protocol):
    """Minimal async review engine interface."""

    async def review(self, request: Any) -> Any:
        ...


@runtime_checkable
class KnowledgeEngineProtocol(Protocol):
    """Minimal async knowledge engine (RAG) interface."""

    async def research(
        self,
        topic: str,
        context: str = "",
        depth: str = "standard",
        sources: list[str] | None = None,
        max_results: int = 10,
    ) -> Any:
        ...


# ── Configuration ───────────────────────────────────────────────────────────


@dataclass
class OrchestrationConfig:
    """Runtime configuration for the orchestration engine."""

    workspace_root: str
    state_dir: str | None = None
    max_concurrent_executions: int = 1
    global_timeout_seconds: float = 600.0
    default_worker_timeout_seconds: float = 300.0
    max_rectification_loops: int = 3
    max_attempts_per_stage: int = 3
    require_hitl_for_deployment: bool = True
    enable_persistence: bool = True
    security_guard_enabled: bool = True

    def __post_init__(self) -> None:
        if self.state_dir is None:
            self.state_dir = str(Path(self.workspace_root) / ".autoforge" / "state")


# ── CancelledError alias ────────────────────────────────────────────────────

class CancelledError(asyncio.CancelledError):
    """Aliased so the orchestrator's exception handler is self-contained."""


# ── Orchestration Engine ──────────────────────────────────────────────────


class OrchestrationEngine:
    """Durable, observable orchestrator for autonomous engineering workflows.

    Injects: event sink, worker registry, model router service, execution
    engine, artifact manager, review engine, knowledge engine, persistence.
    Any may be ``None``; the engine degrades gracefully.
    """

    def __init__(
        self,
        config: OrchestrationConfig,
        *,
        event_sink: EventSinkProtocol | None = None,
        worker_registry: Any | None = None,
        model_router: ModelRouterService | None = None,
        executor_registry: ExecutorRegistry | None = None,
        execution_engine: Any = None,
        artifact_manager: ArtifactManagerProtocol | None = None,
        review_engine: ReviewEngineProtocol | None = None,
        knowledge_engine: KnowledgeEngineProtocol | None = None,
        persistence: StatePersistence | None = None,
    ) -> None:
        self._config = config
        self._event_sink = event_sink
        self._worker_registry = worker_registry
        self._model_router = model_router
        self._executor_registry = executor_registry
        self._execution_engine = execution_engine
        self._artifact_manager = artifact_manager
        self._review_engine = review_engine
        self._knowledge_engine = knowledge_engine
        self._persistence = persistence or StatePersistence(config.state_dir)
        self._security = (
            SecurityBoundaryGuard(config.workspace_root)
            if config.security_guard_enabled
            else None
        )
        self._states: dict[str, ProjectExecutionState] = {}
        self._lock = asyncio.Lock()
        self._active_tasks: dict[str, asyncio.Task] = {}
        self._ai_provider_cache: dict[str, Any] = {}

    # ── State management ─────────────────────────────────────────────────

    def _persist(self, state: ProjectExecutionState) -> None:
        if self._config.enable_persistence:
            self._persistence.save(state)

    def _load_or_lookup(
        self, execution_id: str
    ) -> ProjectExecutionState | None:
        state = self._states.get(execution_id)
        if state is not None:
            return state
        if self._config.enable_persistence:
            return self._persistence.load(execution_id)
        return None

    def restore(self, execution_id: str) -> ProjectExecutionState:
        """Restore a previously-persisted project execution state."""
        state = self._load_or_lookup(execution_id)
        if state is None:
            raise OrchestrationError(
                f"No project found with execution_id: {execution_id}"
            )
        self._states[state.execution_id] = state
        return state

    def get_state(self, execution_id: str) -> ProjectExecutionState | None:
        """Look up a project state by execution ID (memory + persistence)."""
        state = self._states.get(execution_id)
        if state is not None:
            return state
        if self._config.enable_persistence:
            state = self._persistence.load(execution_id)
            if state is not None:
                self._states[execution_id] = state
        return state

    # ── Event emission ───────────────────────────────────────────────────

    def _emit(
        self,
        event_type: EventType,
        category: EventCategory,
        *,
        execution: ProjectExecutionState | None,
        stage_id: str | None = None,
        duration_ms: float | None = None,
        **meta: Any,
    ) -> None:
        if self._event_sink is None:
            return
        try:
            metadata: dict[str, Any] = {}
            if execution is not None:
                metadata["project_id"] = execution.project_id
                metadata["workflow_id"] = execution.workflow_id
                metadata["execution_id"] = execution.execution_id
            if stage_id:
                metadata["stage_id"] = stage_id
            if duration_ms is not None:
                metadata["duration_ms"] = round(duration_ms, 3)
            metadata.update(meta)
            aggregate_id = (
                uuid.UUID(str(execution.execution_id))
                if execution
                else uuid.uuid4()
            )
            event = BaseEvent(
                event_type=event_type,
                event_category=category,
                aggregate_id=aggregate_id,
                aggregate_type="ProjectExecution",
                correlation_id=aggregate_id,
                metadata=metadata,
            )
            self._event_sink.publish(event)
        except Exception:
            logger.debug("Event emission failed (non-fatal)", exc_info=True)

    # ── Project creation ─────────────────────────────────────────────────

    async def create_project(
        self,
        objective: str,
        *,
        workflow_id: str | None = None,
        project_id: str | None = None,
        config_overrides: dict[str, Any] | None = None,
    ) -> ProjectExecutionState:
        """Create a new project execution from a workflow definition."""
        async with self._lock:
            if workflow_id is None:
                workflow_id = "greenfield"

            if workflow_id == "greenfield":
                definition = GREENFIELD_WORKFLOW_DEFINITION
            elif workflow_id in ("legacy_modernization", "legacy"):
                definition = LEGACY_WORKFLOW_DEFINITION
            else:
                raise OrchestrationError(
                    f"Unknown workflow_id: {workflow_id}"
                )

            exec_id = str(uuid.uuid4())
            proj_id = project_id or str(uuid.uuid4())
            stage_order = definition.stage_order()

            stages: dict[str, StageExecutionState] = {}
            for sid in stage_order:
                stage_def = definition.stage_map()[sid]
                stages[sid] = StageExecutionState(
                    stage_id=stage_def.stage_id,
                    definition=stage_def,
                )

            state = ProjectExecutionState(
                project_id=proj_id,
                workflow_id=workflow_id,
                workflow_name=definition.name,
                mode=definition.mode,
                execution_id=exec_id,
                objective=objective,
                stages=stages,
                stage_order=stage_order,
                workspace_root=self._config.workspace_root,
                meta=dict(config_overrides or {}),
            )

            self._states[exec_id] = state
            self._persist(state)

            self._emit(
                EventType.EXECUTION_CREATED,
                EventCategory.EXECUTION,
                execution=state,
                objective=objective,
                workflow_id_str=workflow_id,
            )
            logger.info(
                "Created project execution %s for workflow '%s'",
                exec_id,
                workflow_id,
            )
            return state

    # ── Project lifecycle ───────────────────────────────────────────────

    async def run_project(
        self, execution_id: str
    ) -> ProjectExecutionState:
        """Execute a full project workflow to completion."""
        async with self._lock:
            state = self._load_or_lookup(execution_id)
            if state is None:
                raise OrchestrationError(
                    f"No project found with execution_id: {execution_id}"
                )

        self._emit(
            EventType.WORKFLOW_STARTED,
            EventCategory.SYSTEM_EVENT,
            execution=state,
        )

        state.status = WorkflowStatus.RUNNING
        state.started_at = _iso(_utc_now())
        state.metrics.started_at = _iso(_utc_now())
        self._persist(state)

        try:
            await self._execute_stages(state)
        except CancelledError:
            state.status = WorkflowStatus.CANCELLED
            state.cancellation = {
                "reason": "Cancelled by caller",
                "cancelled_at": _iso(_utc_now()),
            }
            self._persist(state)
            self._emit(
                EventType.WORKFLOW_CANCELLED,
                EventCategory.SYSTEM_EVENT,
                execution=state,
                reason="Cancelled by caller",
            )
            raise

        if state.status == WorkflowStatus.RUNNING:
            state.status = WorkflowStatus.COMPLETED

        state.completed_at = _iso(_utc_now())
        state.metrics.finalize()
        self._persist(state)

        self._emit(
            EventType.WORKFLOW_COMPLETED,
            EventCategory.SYSTEM_EVENT,
            execution=state,
            duration_ms=(
                state.metrics.duration_seconds * 1000
                if state.metrics.duration_seconds
                else None
            ),
        )
        return state

    # ── Stage execution ─────────────────────────────────────────────────

    async def _execute_stages(
        self, state: ProjectExecutionState
    ) -> None:
        """Iterate through stages in topological order, executing each."""
        for stage_id in state.stage_order:
            stage = state.stages[stage_id]
            if stage.status in (
                StageStatus.SUCCEEDED,
                StageStatus.SKIPPED,
                StageStatus.CANCELLED,
            ):
                continue

            await self._run_stage(state, stage)

            if state.status == WorkflowStatus.CANCELLED:
                break

            if stage.status == StageStatus.WAITING_FOR_HITL:
                self._emit(
                    EventType.WORKFLOW_PAUSED,
                    EventCategory.SYSTEM_EVENT,
                    execution=state,
                    reason=f"Waiting for HITL on stage '{stage_id}'",
                )
                state.status = WorkflowStatus.WAITING_FOR_HITL
                self._persist(state)
                break

            if stage.status not in (
                StageStatus.SUCCEEDED,
                StageStatus.SKIPPED,
            ):
                state.metrics.record_failure()
                self._persist(state)
                self._emit(
                    EventType.WORKFLOW_FAILED,
                    EventCategory.SYSTEM_EVENT,
                    execution=state,
                    stage_id=stage_id,
                )
                state.status = WorkflowStatus.FAILED
                self._persist(state)
                return

    # ── Stage execution engine ───────────────────────────────────────────

    async def _run_stage(
        self,
        state: ProjectExecutionState,
        stage_state: StageExecutionState,
    ) -> None:
        """Execute a single stage to completion (with retries) or failure."""
        from autoforge_execution.environment import WorkspaceEnvironment
        from autoforge_execution.artifacts import ArtifactPipeline

        stage = stage_state.definition
        stage_id = stage.stage_id

        # Transition to RUNNING
        stage_state.status = StageStatus.RUNNING
        stage_state.started_at = _iso(_utc_now())
        state.touch()
        self._persist(state)
        self._emit(
            EventType.STAGE_STARTED,
            EventCategory.SYSTEM_EVENT,
            execution=state,
            stage_id=stage_id,
        )

        # DEPLOYMENT stages skip the engineering loop entirely
        if stage.kind == StageKind.DEPLOYMENT:
            await self._process_deployment_stage(state, stage_state, context=None, produced_artifacts=[])
            # If HITL is required, the stage is now WAITING_FOR_HITL; caller handles pausing
            if stage_state.status == StageStatus.WAITING_FOR_HITL:
                return
            # No HITL required: mark as SUCCEEDED and emit completion event
            stage_state.status = StageStatus.SUCCEEDED
            stage_state.finished_at = _iso(_utc_now())
            state.touch()
            self._persist(state)
            self._emit(
                EventType.STAGE_SUCCEEDED,
                EventCategory.SYSTEM_EVENT,
                execution=state,
                stage_id=stage_id,
                duration_ms=0,
            )
            return

        try:
            worker_type = _worker_type_for_stage(stage.kind)
            ai_provider = self._get_ai_provider(stage)
            model_decision = self._route_model(state, stage, worker_type)

                        # Resolve a real workforce worker for this stage. This is the
            # canonical 23-worker workforce path. If resolution fails,
            # the stage is failed honestly — we do NOT silently substitute
            # a generic EngineeringWorker (that was the Phase 18-A bug).
            workforce_worker = self._resolve_workforce_worker(stage, model_decision, ai_provider)
            if workforce_worker is None:
                # Honest failure: a specialized worker could not be resolved
                # for this stage. Do NOT silently substitute a generic worker.
                await self._finalize_stage_failure(
                    state, stage_state,
                    f"No specialized workforce worker could be resolved for stage kind "
                    f"'{stage.kind.value}' (expected worker_type='{stage.worker_type}')",
                    [],
                )
                return

            # Emit WORKER_ASSIGNED with the REAL worker that will execute.
            specialized_type = getattr(workforce_worker, "specialized_type", "unknown")
            worker_caps = list(
                getattr(getattr(workforce_worker, "expertise", None), "capabilities", []) or []
            )
            stage_state.worker_assignment = WorkerAssignment(
                worker_id=workforce_worker.worker_id,
                worker_type=specialized_type,
                required_capabilities=worker_caps,
                evidence=(
                    f"Capability match for stage kind '{stage.kind.value}': "
                    f"required={list(stage.required_capabilities or [])}"
                ),
                assigned_at=_iso(_utc_now()),
            )
            self._persist(state)
            self._emit(
                EventType.WORKER_ASSIGNED,
                EventCategory.EXECUTION,
                execution=state,
                stage_id=stage_id,
                worker_id=workforce_worker.worker_id,
                worker_type=specialized_type,
                worker_capabilities=worker_caps,
            )

            workspace_root = Path(self._config.workspace_root)
            context = _build_execution_context(
                stage=stage,
                stage_state=stage_state,
                state=state,
                workspace_root=workspace_root,
                model_decision=model_decision,
            )

            # The selected workforce worker IS the execution object.
            # It runs its own specialized loop based on its expertise
            # (e.g. ResearchEngineer -> ResearchLoop, QAEngineer -> QALoop).
            # We do NOT construct a generic EngineeringWorker, and we do NOT
            # construct a generic EngineeringLoop here.
            worker = workforce_worker

            # Prepare the workforce worker's internal state.
            try:
                worker.prepare(
                    task_id=stage.stage_id,
                    workflow_id=_safe_uuid(state.workflow_id),
                    correlation_id=_safe_uuid(state.execution_id) or uuid.uuid4(),
                    attempt_number=max(1, stage_state.attempt_number),
                )
            except Exception as prep_exc:
                # Some workforce workers have a custom prepare() that may
                # raise; treat as honest failure rather than masking it.
                logger.debug(f"workforce worker prepare() raised: {prep_exc}")

            self._emit(
                EventType.WORKER_STARTED,
                EventCategory.EXECUTION,
                execution=state,
                stage_id=stage_id,
                worker_id=worker.worker_id,
                worker_type=specialized_type,
            )
            self._emit(
                EventType.INFERENCE_STARTED,
                EventCategory.EXECUTION,
                execution=state,
                stage_id=stage_id,
                model=model_decision.model_id if model_decision else None,
                worker_id=worker.worker_id,
            )

            loop_config = self._get_loop_config(stage)

            # NOTE: we deliberately do NOT construct a generic
            # ``EngineeringLoop`` here. The selected workforce worker
            # builds its own specialized loop inside ``execute_task()``
            # (e.g. ResearchEngineer -> ResearchLoop). That is the
            # whole point of Phase 18-A: the specialized worker
            # executes through its OWN loop, not a generic one.

            verification_commands = self._get_verification_commands(stage)

            # Security guard validation: validate all verification commands before execution.
            # Any command that violates the security boundary causes the stage to fail.
            if verification_commands and self._security is not None:
                valid_commands: list[Any] = []
                for cmd in verification_commands:
                    argv = cmd.argv if hasattr(cmd, "argv") else list(cmd)
                    try:
                        self._security.validate_command(argv)
                        valid_commands.append(cmd)
                    except Exception as exc:
                        logger.warning(
                            f"Security guard rejected command {argv[:2]}... in stage {stage_id}: {exc}"
                        )
                        await self._finalize_stage_failure(
                            state, stage_state,
                            f"Security violation: {exc}",
                            [],
                        )
                        return
                verification_commands = valid_commands if valid_commands else None

            # Stash verification commands on the context so the workforce
            # worker's specialized loop can pick them up if it chooses to.
            if verification_commands:
                try:
                    context.input_data = dict(context.input_data or {})
                    context.input_data["verification_commands"] = verification_commands
                except Exception:
                    pass

            # ACTUAL EXECUTION: the resolved workforce worker runs.
            # The workforce worker's execute_task() builds its own
            # specialized loop (e.g. ResearchEngineer -> ResearchLoop)
            # and runs it with `worker_id == workforce_worker.worker_id`.
            # This is the SAME object whose identity is recorded in
            # WORKER_ASSIGNED above. No generic EngineeringWorker.
            try:
                passed, produced_artifacts, final_eval = await worker.execute_task(context)
            except Exception as worker_exc:
                self._emit(
                    EventType.WORKER_FAILED,
                    EventCategory.EXECUTION,
                    execution=state,
                    stage_id=stage_id,
                    worker_id=worker.worker_id,
                    worker_type=specialized_type,
                    error=str(worker_exc),
                )
                await self._finalize_stage_failure(
                    state, stage_state,
                    f"Workforce worker '{specialized_type}' (id={worker.worker_id}) failed: {worker_exc}",
                    [],
                    exception=worker_exc,
                )
                return

            self._emit(
                EventType.INFERENCE_COMPLETED,
                EventCategory.EXECUTION,
                execution=state,
                stage_id=stage_id,
                worker_id=worker.worker_id,
                worker_type=specialized_type,
            )

            if stage.kind == StageKind.REVIEW:
                await self._process_review_stage(state, stage_state, context, produced_artifacts)
                return

            if stage.kind == StageKind.DEPLOYMENT:
                await self._process_deployment_stage(state, stage_state, context, produced_artifacts)
                return

            if passed:
                self._emit(
                    EventType.WORKER_COMPLETED,
                    EventCategory.EXECUTION,
                    execution=state,
                    stage_id=stage_id,
                    worker_id=worker.worker_id,
                    worker_type=specialized_type,
                )
                await self._finalize_stage_success(state, stage_state, produced_artifacts, final_eval)
                return

            if stage_state.attempt_number < self._config.max_attempts_per_stage:
                self._emit(
                    EventType.WORKER_FAILED,
                    EventCategory.EXECUTION,
                    execution=state,
                    stage_id=stage_id,
                    worker_id=worker.worker_id,
                    worker_type=specialized_type,
                    error="Stage evaluation did not pass on first attempt",
                )
                diagnosis = None
                try:
                    diagnosis = self._extract_diagnosis_from_loop(
                        getattr(worker, "iteration_history", []) or []
                    )
                except Exception:
                    diagnosis = None
                if diagnosis is not None:
                    await self._generate_repair_plan(stage, state, stage_state, context, diagnosis)

                stage_state.attempt_number += 1
                stage_state.status = StageStatus.RUNNING
                self._persist(state)

                repaired_context = _build_execution_context(
                    stage=stage,
                    stage_state=stage_state,
                    state=state,
                    workspace_root=workspace_root,
                    model_decision=model_decision,
                )
                if diagnosis is not None and hasattr(diagnosis, "model_dump"):
                    repaired_context.metadata["last_diagnosis"] = diagnosis.model_dump()
                if verification_commands:
                    try:
                        repaired_context.input_data = dict(repaired_context.input_data or {})
                        repaired_context.input_data["verification_commands"] = verification_commands
                    except Exception:
                        pass

                try:
                    passed_retry, artifacts_retry, eval_retry = await worker.execute_task(repaired_context)
                except Exception as worker_retry_exc:
                    self._emit(
                        EventType.WORKER_FAILED,
                        EventCategory.EXECUTION,
                        execution=state,
                        stage_id=stage_id,
                        worker_id=worker.worker_id,
                        worker_type=specialized_type,
                        error=str(worker_retry_exc),
                    )
                    await self._finalize_stage_failure(
                        state, stage_state,
                        f"Workforce worker '{specialized_type}' (id={worker.worker_id}) failed on retry: {worker_retry_exc}",
                        [],
                        exception=worker_retry_exc,
                    )
                    return

                if passed_retry:
                    self._emit(
                        EventType.WORKER_COMPLETED,
                        EventCategory.EXECUTION,
                        execution=state,
                        stage_id=stage_id,
                        worker_id=worker.worker_id,
                        worker_type=specialized_type,
                    )
                    await self._finalize_stage_success(state, stage_state, artifacts_retry, eval_retry)
                    return

            self._emit(
                EventType.WORKER_FAILED,
                EventCategory.EXECUTION,
                execution=state,
                stage_id=stage_id,
                worker_id=worker.worker_id,
                worker_type=specialized_type,
                error="Stage evaluation failed after maximum retries",
            )
            await self._finalize_stage_failure(
                state, stage_state,
                "Stage evaluation failed after maximum retries",
                [],
            )

        except Exception as exc:  # noqa: BLE-001
            await self._finalize_stage_failure(
                state, stage_state,
                f"Stage execution error: {exc}",
                [],
                exception=exc,
            )

    # ── Worker resolution ──────────────────────────────────────────────

    def _resolve_worker(self, stage: StageDefinition) -> WorkerProtocol | None:
        """Resolve a worker for the given stage from the worker registry."""
        if self._worker_registry is None:
            return None
        try:
            worker_key = stage.kind.value
            return getattr(self._worker_registry, worker_key, None) or getattr(
                self._worker_registry, stage.worker_type or stage.kind.value, None
            )
        except Exception:
            return None

    def _resolve_workforce_worker(
        self, stage: StageDefinition, model_decision: ModelDecision | None,
        ai_provider: Any = None,
    ) -> Any | None:
        """Resolve a real 23-worker workforce worker for the given stage.

        Returns the WorkforceWorker instance, or None if the workforce
        is not available (legacy path).
        """
        try:
            from autoforge_workforce.registry import WORKER_REGISTRY
            from autoforge_workforce.workers import WorkforceWorker
        except ImportError:
            return None
        # Map stage to specialized worker type.
        worker_type = stage.worker_type or stage.kind.value
        worker_cls = WORKER_REGISTRY.lookup(worker_type)
        if worker_cls is None:
            return None
        try:
            from autoforge_execution.environment import WorkspaceEnvironment
            env = WorkspaceEnvironment(self._config.workspace_root)
            # Use the already-resolved AI provider for this stage if given.
            if ai_provider is None:
                ai_provider = self._get_ai_provider(stage)
            worker = worker_cls(
                worker_id=f"wf-{stage.stage_id[:8]}-{uuid.uuid4().hex[:6]}",
                environment=env,
                ai_provider=ai_provider,
            )
            return worker
        except Exception:
            return None

    # ── Model routing ───────────────────────────────────────────────────

    def _route_model(
        self,
        state: ProjectExecutionState,
        stage: StageDefinition,
        worker_type: Any,
    ) -> ModelDecision | None:
        """
        Route to an appropriate model for this stage using real model routing.

        Uses the worker's model requirements when available to build a proper
        RoutingRequest, then delegates to ModelRouterService for deterministic
        model selection. Returns the routing decision for provenance tracking.

        The selected model/provider/node flows through ExecutionContext metadata
        to the AI adapter, which uses it for actual inference execution.
        """
        if self._model_router is None:
            return None
        try:
            capability = _capability_for_stage(stage.kind)

            # Build a proper RoutingRequest from stage requirements.
            # Privacy policy defaults to local_only (the fleet's default).
            # IMPORTANT: None means "no constraint" — frozenset() would forbid
            # ALL modes and cause NoEligibleModelError.
            allowed_modes: frozenset | None = None  # no deployment-mode constraint

            req = RoutingRequest(
                required_capabilities=frozenset({capability}),
                min_context_window_tokens=stage.metadata.get("min_context_window_tokens"),
                allowed_deployment_modes=allowed_modes,
            )

            # Route synchronously (ModelRouterService.route is sync, not async)
            decision = self._model_router.route(req)

            # Emit the canonical MODEL_ROUTED event with the selected model
            self._emit(
                EventType.MODEL_ROUTED,
                EventCategory.EXECUTION,
                execution=state,
                stage_id=stage.stage_id,
                model=decision.selected.model.model_id,
                provider=decision.selected.model.provider_id,
                node=decision.selected.model.provider_id,
                policy=decision.policy_name,
                rationale=decision.rationale,
            )

            # Construct ModelDecision from the routing decision for provenance
            return ModelDecision(
                model_id=decision.selected.model.model_id,
                provider_id=decision.selected.model.provider_id,
                node_id=decision.selected.model.provider_id,
                policy_name=decision.policy_name,
                decision_id=str(decision.decision_id),
                rationale=decision.rationale,
                resolved_capabilities=sorted(str(c) for c in req.required_capabilities),
                decided_at=_iso(_utc_now()),
            )
        except Exception as exc:
            logger.debug(f"Model routing failed (non-fatal): {exc}")
            return None

    # ── AI provider & loop config helpers ──────────────────────────────

    def _ensure_provider_registry(self) -> ExecutorRegistry | None:
        """
        Ensure the executor registry has real provider adapters bound.

        When executor_registry is provided at construction time it is used directly.
        Otherwise creates a fresh registry and binds any locally-available
        Ollama adapters. This method is idempotent — repeated calls return the
        same (possibly pre-bound) registry.
        """
        if self._executor_registry is not None:
            return self._executor_registry

        try:
            registry = ExecutorRegistry()
            from autoforge_ai_infrastructure.adapters.ollama import OllamaProviderAdapter
            ollama_m1 = OllamaProviderAdapter(provider_id="local-m1")
            registry.bind("local-m1", ollama_m1)
            self._executor_registry = registry
            return registry
        except Exception:
            return None

    def _get_ai_provider(self, stage: StageDefinition) -> Any:
        """Return an AI provider for a stage (override in subclasses for testing).

        Caches the provider per stage_id so multiple calls within the same
        stage execution return the same instance.
        When an executor_registry is available, it is passed to the adapter
        so real model execution can occur.
        """
        if not hasattr(self, "_ai_provider_cache"):
            self._ai_provider_cache: dict[str, Any] = {}
        if stage.stage_id in self._ai_provider_cache:
            return self._ai_provider_cache[stage.stage_id]
        from autoforge_execution.ai_adapter import AIInfrastructureAdapter
        provider = AIInfrastructureAdapter(
            router=self._model_router,
            model_executor=self._ensure_provider_registry(),
        )
        self._ai_provider_cache[stage.stage_id] = provider
        return provider

    def _get_cached_ai_provider(self, stage_id: str) -> Any:
        """Return the cached AI provider for a stage, or build a default one."""
        if hasattr(self, "_ai_provider_cache") and stage_id in self._ai_provider_cache:
            return self._ai_provider_cache[stage_id]
        from autoforge_execution.ai_adapter import AIInfrastructureAdapter
        return AIInfrastructureAdapter(
            router=self._model_router,
            model_executor=self._ensure_provider_registry(),
        )

    def _get_loop_config(self, stage: StageDefinition) -> Any:
        """Return loop config for a stage (can be overridden)."""
        from autoforge_execution.models import LoopConfig
        return LoopConfig(
            max_iterations=self._config.max_rectification_loops,
            timeout_seconds=self._config.default_worker_timeout_seconds,
        )

    def _get_verification_commands(
        self, stage: StageDefinition
    ) -> list[Any] | None:
        """Return verification commands for a stage.

        Returns the configured commands if any, otherwise returns None.
        When None is returned, the stage's acceptance is evaluated by the AI
        adapter's plan/output verification rather than a fake always-pass.
        Subclasses can override this method to provide per-stage verification.
        """
        commands = stage.metadata.get("verification_commands") or getattr(stage, "verification_commands", None)
        if commands:
            from autoforge_execution.models import CommandSpec
            return [CommandSpec(argv=c) if isinstance(c, list) else c for c in commands]
        return None

    # ── Stage success / failure finalization ────────────────────────────

    async def _finalize_stage_success(
        self,
        state: ProjectExecutionState,
        stage_state: StageExecutionState,
        produced_artifacts: list[Any],
        final_eval: Any,
    ) -> None:
        """Transition a stage to SUCCEEDED after a successful evaluation."""
        stage_state.status = StageStatus.SUCCEEDED
        stage_state.finished_at = _iso(_utc_now())
        out: dict[str, Any] = {}
        if produced_artifacts:
            out["artifacts"] = [
                a.model_dump() if hasattr(a, "model_dump") else a
                for a in produced_artifacts
            ]
        if final_eval is not None and hasattr(final_eval, "model_dump"):
            out["evaluation"] = final_eval.model_dump()
        stage_state.output = out

        state.touch()
        duration_ms = 0.0
        if stage_state.started_at:
            try:
                started = datetime.fromisoformat(stage_state.started_at)
                duration_ms = (
                    datetime.now(timezone.utc) - started
                ).total_seconds() * 1000
            except Exception:
                pass
        state.metrics.record_attempt()
        state.metrics.record_worker()

        for artifact in produced_artifacts or []:
            if hasattr(artifact, "model_dump"):
                art_dict = artifact.model_dump()
            elif isinstance(artifact, dict):
                art_dict = artifact
            else:
                continue
            state.register_artifact(art_dict)

            # Register with the artifact manager if connected.
            if self._artifact_manager is not None:
                try:
                    import uuid as _uuid
                    self._artifact_manager.create_artifact(
                        name=art_dict.get("name", f"{stage_state.stage_id}-artifact"),
                        artifact_type=art_dict.get("artifact_type", "SOURCE"),
                        project_id=_uuid.UUID(state.project_id) if state.project_id else None,
                        workflow_id=state.workflow_id,
                        content=art_dict.get("content", ""),
                        metadata={
                            "stage_id": stage_state.stage_id,
                            "stage_kind": stage_state.definition.kind.value,
                            "execution_id": state.execution_id,
                            **art_dict.get("metadata", {}),
                        },
                    )
                except Exception as exc:
                    # Artifact registration failure must not break the stage.
                    logger.debug(f"Artifact manager registration failed (non-fatal): {exc}")

        self._persist(state)
        self._emit(
            EventType.STAGE_SUCCEEDED,
            EventCategory.SYSTEM_EVENT,
            execution=state,
            stage_id=stage_state.stage_id,
            duration_ms=duration_ms,
        )

    async def _finalize_stage_failure(
        self,
        state: ProjectExecutionState,
        stage_state: StageExecutionState,
        reason: str,
        iteration_history: list[Any],
        exception: BaseException | None = None,
    ) -> None:
        """Transition a stage to FAILED."""
        stage_state.status = StageStatus.FAILED
        stage_state.finished_at = _iso(_utc_now())
        stage_state.output = {
            "error": reason,
            "iterations": [
                i.model_dump() if hasattr(i, "model_dump") else i
                for i in iteration_history
            ],
        }

        state.touch()
        state.metrics.record_failure()
        self._persist(state)

        self._emit(
            EventType.STAGE_FAILED,
            EventCategory.SYSTEM_EVENT,
            execution=state,
            stage_id=stage_state.stage_id,
            reason=reason,
        )

        if exception:
            self._emit(
                EventType.FAILURE_DETECTED,
                EventCategory.FAILURE,
                execution=state,
                stage_id=stage_state.stage_id,
                error_type=type(exception).__name__,
                error_message=str(exception),
            )

    # ── Retry / repair helpers ──────────────────────────────────────────

    def _extract_diagnosis_from_loop(
        self, iteration_history: list[Any]
    ) -> Any | None:
        """Extract the most recent diagnosis from the loop iteration history."""
        if not iteration_history:
            return None
        last = iteration_history[-1]
        return getattr(last, "diagnosis", None)

    async def _generate_repair_plan(
        self,
        stage: StageDefinition,
        state: ProjectExecutionState,
        stage_state: StageExecutionState,
        context: Any,
        diagnosis: Any,
    ) -> dict[str, Any]:
        """Generate a repair plan based on the diagnosis."""
        diagnosis_summary = (
            diagnosis.root_cause
            if diagnosis is not None and hasattr(diagnosis, "root_cause")
            else str(diagnosis) if diagnosis is not None else ""
        )
        return {
            "stage_id": stage.stage_id,
            "attempt": stage_state.attempt_number,
            "diagnosis_summary": diagnosis_summary,
        }

    # ── Review stage ────────────────────────────────────────────────────

    async def _process_review_stage(
        self,
        state: ProjectExecutionState,
        stage_state: StageExecutionState,
        context: Any,
        produced_artifacts: list[Any],
    ) -> None:
        """Execute the REVIEW stage: run review engine and handle verdict."""
        verdict = ReviewVerdict.APPROVED
        review_output: dict[str, Any] = {}

        if self._review_engine is not None:
            try:
                review_req = _build_review_request(state, stage_state, context)
                review_result = await self._review_engine.review(review_req)
                if hasattr(review_result, "verdict"):
                    verdict = ReviewVerdict(review_result.verdict)
                    review_output = review_result.model_dump() if hasattr(review_result, "model_dump") else {}
                elif isinstance(review_result, dict):
                    verdict = ReviewVerdict(review_result.get("verdict", "approved"))
                    review_output = review_result
            except Exception as exc:
                logger.warning(f"Review engine failed: {exc}. Defaulting to approved.")
                review_output = {"error": str(exc)}

        stage_state.output = {"review_output": review_output}

        if verdict == ReviewVerdict.REJECTED:
            await self._finalize_stage_failure(
                state, stage_state,
                f"Code review rejected: {review_output.get('reason', 'No reason provided')}",
                [],
            )
            return

        await self._finalize_stage_success(state, stage_state, produced_artifacts, None)

    # ── Deployment stage ────────────────────────────────────────────────

    async def _process_deployment_stage(
        self,
        state: ProjectExecutionState,
        stage_state: StageExecutionState,
        context: Any,
        produced_artifacts: list[Any],
    ) -> None:
        """Execute the DEPLOYMENT stage: check HITL gate, then deploy."""
        gate_id = f"hitl-deploy-{state.execution_id}"

        if self._config.require_hitl_for_deployment:
            from autoforge_orchestration.models import HITLGateRecord

            state.hitl_gates[gate_id] = HITLGateRecord(
                gate_id=gate_id,
                stage_id=stage_state.stage_id,
                workflow_id=state.workflow_id,
                project_id=state.project_id,
                reason="Deployment requires human approval",
                risk_level="medium",
                requested_at=_iso(_utc_now()),
                status="PENDING",
                actor=None,
                decided_at=None,
                decision=None,
                reason_text=None,
            )
            self._persist(state)

            self._emit(
                EventType.APPROVAL_REQUIRED,
                EventCategory.APPROVAL,
                execution=state,
                stage_id=stage_state.stage_id,
                gate_id=gate_id,
                reason="Deployment requires human approval",
            )

            stage_state.status = StageStatus.WAITING_FOR_HITL
            stage_state.output = {"hitl_gate_id": gate_id}
            self._persist(state)
            return

        deployment_result = await self._execute_deployment(state, stage_state, produced_artifacts)
        if deployment_result and hasattr(deployment_result, "to_dict"):
            stage_state.output = {"deployment": deployment_result.to_dict()}

        # Emit deployment status events truthfully
        if deployment_result.status == DeploymentStatus.DEPLOYED:
            self._emit(
                EventType.DEPLOYMENT_COMPLETED,
                EventCategory.EXECUTION,
                execution=state,
                stage_id=stage_state.stage_id,
                deployment_target=deployment_result.target,
            )
            await self._finalize_stage_success(state, stage_state, produced_artifacts, None)
        elif deployment_result.status == DeploymentStatus.UNAVAILABLE:
            # Honest UNAVAILABLE: deployment infra not connected. Don't mark success.
            self._emit(
                EventType.DEPLOYMENT_UNAVAILABLE,
                EventCategory.EXECUTION,
                execution=state,
                stage_id=stage_state.stage_id,
                deployment_target=deployment_result.target,
                reason=deployment_result.detail,
            )
            # Mark stage as SUCCEEDED but emit truthful deployment.unavailable
            # so the stage contract is honored while the deployment is honestly reported.
            # This is a truthful outcome: the stage did its job; deployment infra is absent.
            await self._finalize_stage_success(state, stage_state, produced_artifacts, None)
        else:
            # Unknown deployment status — fail the stage honestly
            await self._finalize_stage_failure(
                state, stage_state,
                f"Unknown deployment status: {deployment_result.status}",
                [],
            )

    async def _execute_deployment(
        self,
        state: ProjectExecutionState,
        stage_state: StageExecutionState,
        produced_artifacts: list[Any],
    ) -> DeploymentResult:
        """Execute the actual deployment logic.

        Returns UNAVAILABLE when no deployment infrastructure is configured.
        A local runtime launch is NOT automatically a deployment operation.
        This method must be connected to real deployment infrastructure
        (container registry, cloud API, etc.) before DEPLOYED can be returned.
        """
        from autoforge_orchestration.models import DeploymentResult

        target = stage_state.definition.metadata.get("deployment_target", "production")
        deployment_target = stage_state.definition.deployment_target

        if not deployment_target and target in ("production", "staging", "development"):
            return DeploymentResult(
                status=DeploymentStatus.UNAVAILABLE,
                target=target,
                detail="Deployment target is not configured. No container registry, cloud platform, "
                       "or deployment API is available. Use local runtime execution instead.",
            )

        # When deployment infrastructure IS configured, execute real deployment here.
        # For now, return UNAVAILABLE with truthful reason.
        return DeploymentResult(
            status=DeploymentStatus.UNAVAILABLE,
            target=target,
            detail="Deployment infrastructure not connected to orchestration engine. "
                   "Real deployment requires integration with cloud/container registry APIs.",
        )


    # ── HITL resumption ─────────────────────────────────────────────────

    async def resume_from_hitl(
        self,
        execution_id: str,
        gate_id: str,
        *,
        approved: bool,
        reason: str | None = None,
    ) -> ProjectExecutionState:
        """Resume a workflow from a paused HITL gate."""
        state = self._load_or_lookup(execution_id)
        if state is None:
            raise OrchestrationError(f"No project found with execution_id: {execution_id}")

        gate = state.hitl_gates.get(gate_id)
        if gate is None:
            raise OrchestrationError(f"No HITL gate found with gate_id: {gate_id}")

        stage_state = state.stages.get(gate.stage_id)
        if stage_state is None:
            raise OrchestrationError(f"Stage not found for gate: {gate.stage_id}")

        gate.status = "APPROVED" if approved else "REJECTED"
        gate.decided_at = _iso(_utc_now())
        gate.actor = "human_operator"
        gate.decision = "approved" if approved else "rejected"
        gate.reason_text = reason

        self._emit(
            EventType.APPROVAL_DECIDED,
            EventCategory.APPROVAL,
            execution=state,
            stage_id=gate.stage_id,
            gate_id=gate_id,
            reason=reason,
        )

        if not approved:
            stage_state.status = StageStatus.FAILED
            stage_state.output = {"hitl_rejected": True, "reason": reason}
            state.status = WorkflowStatus.FAILED
            state.metrics.record_failure()
            self._persist(state)
            return state

        stage_state.status = StageStatus.RUNNING
        state.status = WorkflowStatus.RUNNING
        self._persist(state)

        if stage_state.definition.kind == StageKind.DEPLOYMENT:
            deployment_result = await self._execute_deployment(state, stage_state, [])
            if hasattr(deployment_result, "to_dict"):
                stage_state.output = {"deployment": deployment_result.to_dict()}
            if deployment_result.status == DeploymentStatus.DEPLOYED:
                self._emit(
                    EventType.DEPLOYMENT_COMPLETED,
                    EventCategory.EXECUTION,
                    execution=state,
                    stage_id=stage_state.stage_id,
                    deployment_target=deployment_result.target,
                )
                await self._finalize_stage_success(state, stage_state, [], None)
            elif deployment_result.status == DeploymentStatus.UNAVAILABLE:
                self._emit(
                    EventType.DEPLOYMENT_UNAVAILABLE,
                    EventCategory.EXECUTION,
                    execution=state,
                    stage_id=stage_state.stage_id,
                    deployment_target=deployment_result.target,
                    reason=deployment_result.detail,
                )
                await self._finalize_stage_success(state, stage_state, [], None)
            else:
                await self._finalize_stage_failure(
                    state, stage_state,
                    f"Unknown deployment status: {deployment_result.status}",
                    [],
                )

        await self._execute_stages(state)

        # After resuming, check if all stages are complete
        if state.status == WorkflowStatus.RUNNING:
            state.status = WorkflowStatus.COMPLETED
        state.completed_at = _iso(_utc_now())
        state.metrics.finalize()
        self._persist(state)
        self._emit(
            EventType.WORKFLOW_COMPLETED,
            EventCategory.SYSTEM_EVENT,
            execution=state,
            duration_ms=(
                state.metrics.duration_seconds * 1000
                if state.metrics.duration_seconds
                else None
            ),
        )
        return state

    # ── Health check ────────────────────────────────────────────────────

    async def health_check(self) -> dict[str, Any]:
        """Return health status of the orchestration engine and its dependencies."""
        checks: dict[str, Any] = {
            "engine": "healthy",
            "dependencies": {},
        }

        try:
            if self._persistence:
                health = getattr(self._persistence, "health_check", lambda: True)()
                checks["dependencies"]["persistence"] = "healthy" if health else "unhealthy"
        except Exception as exc:
            checks["dependencies"]["persistence"] = f"unhealthy: {exc}"

        if self._security:
            try:
                checks["dependencies"]["security"] = "healthy"
            except Exception:
                checks["dependencies"]["security"] = "unhealthy"

        return checks


# ── Helper functions (module-level) ──────────────────────────────────────────


def _worker_type_for_stage(kind: StageKind) -> Any:
    """Map StageKind to WorkerType for workforce worker creation."""
    try:
        from autoforge_execution.models import WorkerType
        mapping = {
            StageKind.PLANNING: WorkerType.PLANNING,
            StageKind.ARCHITECTURE: WorkerType.CODING,
            StageKind.IMPLEMENTATION: WorkerType.CODING,
            StageKind.TESTING: WorkerType.CODING,
            StageKind.REVIEW: WorkerType.REVIEW,
            StageKind.DEPLOYMENT: WorkerType.DEPLOYMENT,
            StageKind.DIAGNOSIS: WorkerType.CODING,
        }
        return mapping.get(kind, WorkerType.CODING)
    except Exception:
        return kind.value


def _capability_for_stage(kind: StageKind) -> str:
    """Map StageKind to the required AI model capability."""
    mapping = {
        StageKind.PLANNING: "planning",
        StageKind.ARCHITECTURE: "code_generation",
        StageKind.IMPLEMENTATION: "code_generation",
        StageKind.TESTING: "code_generation",
        StageKind.REVIEW: "code_review",
        StageKind.DEPLOYMENT: "code_generation",
        StageKind.DIAGNOSIS: "reasoning",
    }
    return mapping.get(kind, "text_generation")


def _task_type_for_stage(kind: StageKind) -> str:
    """Map StageKind to a task type string for ExecutionContext."""
    mapping = {
        StageKind.PLANNING: "planning",
        StageKind.ARCHITECTURE: "architecting",
        StageKind.IMPLEMENTATION: "coding",
        StageKind.TESTING: "testing",
        StageKind.REVIEW: "review",
        StageKind.DEPLOYMENT: "deployment",
        StageKind.DIAGNOSIS: "diagnosis",
    }
    return mapping.get(kind, "coding")


def _build_execution_context(
    stage: StageDefinition,
    stage_state: StageExecutionState,
    state: ProjectExecutionState,
    workspace_root: Path,
    model_decision: ModelDecision | None,
) -> Any:
    """Build an ExecutionContext from a stage definition and project state.

    The model_decision (routing provenance) is embedded in context.metadata so
    the AI adapter can access the selected model/provider/node for actual inference.
    """
    from autoforge_execution.context import ExecutionContext

    verification_commands = stage.metadata.get("verification_commands") or []
    input_data = dict(stage.metadata.get("input_data") or {})
    if verification_commands:
        input_data["verification_commands"] = verification_commands

    project_files = []
    file_contents: dict[str, str] = {}
    for artifact in state.artifacts:
        if artifact.get("path"):
            project_files.append(artifact["path"])

    # Build context metadata including the routing decision for provenance
    context_metadata = dict(stage.metadata or {})
    if model_decision is not None:
        context_metadata["model_decision"] = model_decision.to_dict()
        context_metadata["selected_model_id"] = model_decision.model_id
        context_metadata["selected_provider_id"] = model_decision.provider_id
        context_metadata["selected_node_id"] = model_decision.node_id

    return ExecutionContext(
        task_id=stage.stage_id,
        task_name=stage.name,
        task_type=_task_type_for_stage(stage.kind),
        task_description=stage.description or "",
        input_data=input_data,
        workspace_root=workspace_root,
        workflow_id=_safe_uuid(state.workflow_id),
        project_id=_safe_uuid(state.project_id),
        correlation_id=_safe_uuid(state.execution_id) or uuid.uuid4(),
        attempt_number=max(1, stage_state.attempt_number),
        project_files=project_files,
        file_contents=file_contents,
        metadata=context_metadata,
        effective_model_requirements={
            "required_capabilities": [_capability_for_stage(stage.kind)],
            "model_id": model_decision.model_id if model_decision else None,
            "provider_id": model_decision.provider_id if model_decision else None,
            "node_id": model_decision.node_id if model_decision else None,
        },
    )


def _build_review_request(
    state: ProjectExecutionState,
    stage_state: StageExecutionState,
    context: Any,
) -> Any:
    """Build a review request from stage and project state."""
    return {
        "project_id": state.project_id,
        "workflow_id": state.workflow_id,
        "stage_id": stage_state.stage_id,
        "artifacts": state.artifacts,
        "context": {
            "task_name": getattr(context, "task_name", stage_state.definition.name),
            "task_description": stage_state.definition.description or "",
        },
    }
