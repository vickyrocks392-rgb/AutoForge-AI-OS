"""
Kernel Core - Executive Orchestrator

The Kernel is the single entry point for all platform requests and the central
coordination layer that transforms user intent into completed software engineering
projects.

This module implements the main Kernel class that coordinates all internal modules
and external Platform Engines.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Coroutine
from enum import Enum

#: Module logger. ``logger`` was previously referenced on the learning-stage
#: exception paths without ever being defined, which raised ``NameError`` and
#: masked the original failure whenever the learning engine raised.
logger = logging.getLogger(__name__)

from autoforge_models.project import Project
from autoforge_models.task import Task
from autoforge_models.artifact import Artifact
from autoforge_models.checkpoint import Checkpoint
from autoforge_models.review import Review
from autoforge_models.employee import Employee
from autoforge_models.model_profile import ModelProfile
from autoforge_models.execution_session import ExecutionSession
from autoforge_models.memory_entry import MemoryEntry
from autoforge_models.knowledge import KnowledgeNode
from autoforge_models.quality_gate import QualityGate
from autoforge_models.event import Event as ModelEvent

from autoforge_events.base import BaseEvent as DomainBaseEvent
from autoforge_events.event_types import EventCategory, EventType

from autoforge_kernel.interfaces import (
    # Request and Intent Models
    Request,
    IntentAnalysisResult,
    StrategicPlan,
    ExecutableWorkflow,
    # Service Interfaces
    RuntimeStateManager,
    EventBus,
    MemoryEngine,
    KnowledgeEngine,
    ModelRouter,
    ExecutionContinuityManager,
    ConnectorLayer,
    ObservabilityService,
    SecurityService,
    # Platform Engine Interfaces
    StrategicEngine,
    WorkflowEngine,
    ExecutionEngine,
    ReviewEngine,
    # Kernel Internal Interfaces
    RequestValidator,
    RequestNormalizer,
    ProjectInitializer,
    IdentifierGenerator,
    IntentAnalyzer,
    PlanningCoordinator,
    OrchestrationEngine,
    LoopOrchestrator,
    WorkerDispatchCoordinator,
    InfrastructureCoordinator,
    FailureDetector,
    RecoveryCoordinator,
    ApprovalCoordinator,
    CompletionModule,
    LifecycleCoordinator,
    RuntimeLifecycleManager,
    ProjectLifecycleManager,
    RecoveryModule,
)
from autoforge_kernel.event_utils import publish_event, make_timestamp


class KernelRuntimeStatus(str, Enum):
    """Runtime status for the Kernel."""

    CREATED = "created"
    STARTING = "starting"
    READY = "ready"
    PROCESSING = "processing"
    PAUSING = "pausing"
    PAUSED = "paused"
    RESUMING = "resuming"
    STOPPING = "stopping"
    STOPPED = "stopped"


def _authoritative_review_findings(finalize_result: Any) -> list[dict[str, Any]]:
    """Extract the REAL review/validation evidence from a completion result.

    Phase 19B-1 Gate 4. The Kernel's learning stage previously called
    ``validation_result.get("findings", [])``, but ``validate_completion``
    never populates a ``"findings"`` key, so the learning engine's
    defect-prevention branch was permanently dead (Gate 19A GAP-03).

    Rather than inventing a parallel ``"findings"`` field, this reads the
    authoritative structures ``CompletionModule.finalize_project`` actually
    produces:

    * ``final_review["validation"]`` -- the genuine deterministic validation
      truth (mapping with ``required``/``passed``), and
    * ``final_review["approved"]`` -- the genuine final review verdict.

    The returned list is *evidence*, not invented findings: each entry is a
    verbatim projection of a field the completion module already computed. No
    severity, message, or quality claim is synthesised, and completion and
    validation semantics are untouched.
    """
    if not isinstance(finalize_result, dict):
        return []

    evidence: list[dict[str, Any]] = []

    final_review = finalize_result.get("final_review")
    if isinstance(final_review, dict):
        validation = final_review.get("validation")
        if isinstance(validation, dict):
            evidence.append(
                {
                    "kind": "deterministic_validation",
                    "required": validation.get("required"),
                    "passed": validation.get("passed"),
                    "reason": validation.get("reason", ""),
                    "test_results": validation.get("test_results"),
                    "authoritative": True,
                }
            )
        if isinstance(final_review.get("approved"), bool):
            evidence.append(
                {
                    "kind": "final_review",
                    "approved": final_review.get("approved"),
                    "reason": final_review.get("reason", ""),
                    "evidence_files": final_review.get("evidence_files", 0),
                    "authoritative": True,
                }
            )
        return evidence

    # Failure path: finalize_project reports validation at the top level.
    validation = finalize_result.get("validation")
    if isinstance(validation, dict):
        evidence.append(
            {
                "kind": "deterministic_validation",
                "required": validation.get("required"),
                "passed": validation.get("passed"),
                "reason": validation.get("reason", ""),
                "test_results": validation.get("test_results"),
                "authoritative": True,
            }
        )

    review_gate = finalize_result.get("review_gate")
    if isinstance(review_gate, dict):
        evidence.append(
            {
                "kind": "final_review",
                "approved": review_gate.get("approved"),
                "reason": review_gate.get("reason", ""),
                "evidence_files": review_gate.get("evidence_files", 0),
                "authoritative": True,
            }
        )

    return evidence


class Kernel:
    """
    The AutoForge AI Kernel - Executive Orchestrator.

    The Kernel is the single entry point for all platform requests and the central
    coordination layer that transforms user intent into completed software engineering
    projects.

    The Kernel owns execution orchestration. Everything else provides capabilities.
    The Kernel never directly performs engineering work. Instead, it coordinates
    infrastructure, engineering workflows, and specialist workers.

    Attributes:
        kernel_id: Unique identifier for this Kernel instance.
        version: Kernel version.
        status: Current runtime status.
        config: Kernel configuration.
    """

    def __init__(
        self,
        kernel_id: uuid.UUID | None = None,
        version: str = "1.0.0",
        config: dict[str, Any] | None = None,
        # Service dependencies (injected)
        runtime_state_manager: RuntimeStateManager | None = None,
        event_bus: EventBus | None = None,
        memory_engine: MemoryEngine | None = None,
        knowledge_engine: KnowledgeEngine | None = None,
        model_router: ModelRouter | None = None,
        execution_continuity_manager: ExecutionContinuityManager | None = None,
        connector_layer: ConnectorLayer | None = None,
        observability_service: ObservabilityService | None = None,
        security_service: SecurityService | None = None,
        # Platform Engine dependencies (injected)
        strategic_engine: StrategicEngine | None = None,
        workflow_engine: WorkflowEngine | None = None,
        execution_engine: ExecutionEngine | None = None,
        review_engine: ReviewEngine | None = None,
        # Internal module dependencies (injected)
        request_validator: RequestValidator | None = None,
        request_normalizer: RequestNormalizer | None = None,
        project_initializer: ProjectInitializer | None = None,
        identifier_generator: IdentifierGenerator | None = None,
        intent_analyzer: IntentAnalyzer | None = None,
        planning_coordinator: PlanningCoordinator | None = None,
        orchestration_engine: OrchestrationEngine | None = None,
        loop_orchestrator: LoopOrchestrator | None = None,
        worker_dispatch_coordinator: WorkerDispatchCoordinator | None = None,
        infrastructure_coordinator: InfrastructureCoordinator | None = None,
        failure_detector: FailureDetector | None = None,
        recovery_coordinator: RecoveryCoordinator | None = None,
        approval_coordinator: ApprovalCoordinator | None = None,
        completion_module: CompletionModule | None = None,
        lifecycle_coordinator: LifecycleCoordinator | None = None,
        runtime_lifecycle_manager: RuntimeLifecycleManager | None = None,
        project_lifecycle_manager: ProjectLifecycleManager | None = None,
        recovery_module: RecoveryModule | None = None,
        learning_engine: Any | None = None,
    ):
        """
        Initialize the Kernel.

        All dependencies are injected to enable loose coupling and testability.
        """
        # Kernel identity
        self.kernel_id = kernel_id or uuid.uuid4()
        self.version = version
        self.config = config or {}
        self.status = KernelRuntimeStatus.CREATED
        self.created_at = datetime.now(timezone.utc)

        # Service dependencies
        self.runtime_state_manager = runtime_state_manager
        self.event_bus = event_bus
        self.memory_engine = memory_engine
        self.knowledge_engine = knowledge_engine
        self.model_router = model_router
        self.execution_continuity_manager = execution_continuity_manager
        self.connector_layer = connector_layer
        self.observability_service = observability_service
        self.security_service = security_service

        # Platform Engine dependencies
        self.strategic_engine = strategic_engine
        self.workflow_engine = workflow_engine
        self.execution_engine = execution_engine
        self.review_engine = review_engine

        # Internal module dependencies
        self.request_validator = request_validator
        self.request_normalizer = request_normalizer
        self.project_initializer = project_initializer
        self.identifier_generator = identifier_generator
        self.intent_analyzer = intent_analyzer
        self.planning_coordinator = planning_coordinator
        self.orchestration_engine = orchestration_engine
        self.loop_orchestrator = loop_orchestrator
        self.worker_dispatch_coordinator = worker_dispatch_coordinator
        self.infrastructure_coordinator = infrastructure_coordinator
        self.failure_detector = failure_detector
        self.recovery_coordinator = recovery_coordinator
        self.approval_coordinator = approval_coordinator
        self.completion_module = completion_module
        self.lifecycle_coordinator = lifecycle_coordinator
        self.runtime_lifecycle_manager = runtime_lifecycle_manager
        self.project_lifecycle_manager = project_lifecycle_manager
        self.recovery_module = recovery_module
        self.learning_engine = learning_engine

        # Active projects tracking
        self.active_projects: dict[uuid.UUID, dict[str, Any]] = {}

        # Event handlers registry
        self._event_handlers: dict[EventType, list[Coroutine]] = {}

    # ========================================================================
    # Public Kernel Interface (Section 6 of Specification)
    # ========================================================================

    async def submit_request(
        self,
        request: Request,
    ) -> dict[str, Any]:
        """
        Submit a request to the Kernel.

        This is the main entry point for all platform requests.
        Implements the full orchestration pipeline:
        Request -> Intake -> Intent Analysis -> Planning Coordination ->
        Strategic Engine -> Workflow Engine -> Execution Engine -> Engineering Loops -> Completion

        Args:
            request: The user's request.

        Returns:
            Dictionary containing project_id, status, estimated_duration, estimated_cost.
        """
        # Validate request
        if self.request_validator:
            is_valid, errors = await self.request_validator.validate(request)
            if not is_valid:
                raise ValueError(f"Invalid request: {', '.join(errors)}")

        # Normalize request
        if self.request_normalizer:
            request = await self.request_normalizer.normalize(request)

        # Initialize project
        if self.project_initializer:
            project = await self.project_initializer.initialize(request)
        else:
            raise RuntimeError("Project initializer not configured")

        project_id = project.id

        # Generate identifiers
        correlation_id = None
        workflow_id = None
        if self.identifier_generator:
            correlation_id = self.identifier_generator.generate_correlation_id()
            workflow_id = self.identifier_generator.generate_workflow_id()

        # Create project in state manager
        if self.runtime_state_manager:
            await self.runtime_state_manager.create_project(project)

        # Track active project
        self.active_projects[project_id] = {
            "project": project,
            "correlation_id": correlation_id,
            "workflow_id": workflow_id,
            "status": "created",
            "created_at": datetime.now(timezone.utc),
        }

        # Publish project.created event
        await publish_event(
            event_bus=self.event_bus,
            event_type=EventType.PROJECT_CREATED,
            event_category=EventCategory.PROJECT,
            aggregate_id=project_id,
            aggregate_type="Project",
            correlation_id=correlation_id,
            metadata={
                "project_name": project.name,
                "request_text": request.request_text[:100],
            },
        )

        # Coordinate infrastructure at project start per Kernel Specification v1.0 Section 15
        if self.infrastructure_coordinator:
            await self.infrastructure_coordinator.coordinate_services(
                lifecycle_point="project_start",
                context={
                    "project_id": str(project_id),
                    "request_text": request.request_text,
                },
            )

        # ====================================================================
        # Full Orchestration Pipeline
        # ====================================================================

        # Transition to Planning state
        if self.runtime_state_manager:
            await self.runtime_state_manager.transition_state(
                project_id=project_id,
                new_status="planning",
                metadata={"correlation_id": str(correlation_id)},
            )

        # Publish project.planning event
        await publish_event(
            event_bus=self.event_bus,
            event_type=EventType.PROJECT_PLANNING,
            event_category=EventCategory.PROJECT,
            aggregate_id=project_id,
            aggregate_type="Project",
            correlation_id=correlation_id,
            metadata={"workflow_id": str(workflow_id)},
        )

        # ====================================================================
        # Execute Orchestration Pipeline
        # ====================================================================

        # Step 2: Intent Analysis
        intent_result: IntentAnalysisResult | None = None
        if self.intent_analyzer:
            intent_result = await self.intent_analyzer.analyze(request)
            
            # Publish intent.analyzed event per Kernel Specification v1.0 Section 8.2
            await publish_event(
                event_bus=self.event_bus,
                event_type=EventType.INTENT_ANALYZED,
                event_category=EventCategory.PROJECT,
                aggregate_id=project_id,
                aggregate_type="Project",
                correlation_id=correlation_id,
                metadata={
                    "request_type": intent_result.request_type,
                    "scope": intent_result.scope,
                    "confidence": intent_result.confidence,
                },
            )

        # Step 3: Planning Coordination -> Strategic Engine -> Workflow Engine
        strategic_plan: StrategicPlan | None = None
        executable_workflow: ExecutableWorkflow | None = None
        if self.planning_coordinator and intent_result:
            strategic_plan, executable_workflow = await self.planning_coordinator.coordinate_planning(
                request, intent_result
            )
            
            # Publish plan.created event per Kernel Specification v1.0 Section 8.2
            await publish_event(
                event_bus=self.event_bus,
                event_type=EventType.PLAN_CREATED,
                event_category=EventCategory.PROJECT,
                aggregate_id=project_id,
                aggregate_type="Project",
                correlation_id=correlation_id,
                metadata={
                    "plan_id": str(strategic_plan.plan_id),
                    "workflow_id": str(executable_workflow.workflow_id),
                    "loop_count": len(executable_workflow.loops),
                },
            )

        # Store planning artifacts in active_projects
        if project_id in self.active_projects:
            self.active_projects[project_id]["strategic_plan"] = strategic_plan
            self.active_projects[project_id]["executable_workflow"] = executable_workflow

        # DEF-P1-EVIDENCE: persist the project's workflow identity in the
        # authoritative Runtime state.
        #
        # Execution artifacts are correlated to a project by ``workflow_id``
        # (``ArtifactProvenance.workflow_id`` / ``DurableArtifactState``), but
        # the Kernel kept the planned workflow only in its in-memory
        # ``active_projects`` map, so the correlation was not durable and was
        # lost on restart. Without it the Completion Module cannot determine
        # which durable artifacts belong to a project, and the final review has
        # no authoritative evidence source.
        #
        # ``update_project`` is an existing declared API of this Kernel's
        # ``RuntimeStateManager`` interface (interfaces.py:211) that projects
        # ``project.metadata`` into ``ProjectState.configuration``. This adds no
        # new persistence model, no new state field, and changes no Runtime
        # behaviour: it records an identity the platform already generates and
        # already publishes on planning events.
        if self.runtime_state_manager is not None:
            try:
                correlated_project = project.model_copy(
                    update={
                        "metadata": {
                            **dict(project.metadata or {}),
                            "workflow_id": str(executable_workflow.workflow_id),
                        }
                    }
                )
                await self.runtime_state_manager.update_project(correlated_project)
                self.active_projects[project_id]["project"] = correlated_project
            except Exception as exc:  # pragma: no cover - defensive only
                # Failing to persist the correlation must not abort the request.
                # The final review gate still fails closed if evidence cannot be
                # resolved, so a silent gap here cannot produce a false approval.
                logger.warning(
                    "Could not persist workflow correlation for project %s: %s",
                    project_id,
                    exc,
                )

        # Step 4 & 5: Orchestration -> Execution Engine -> Engineering Loops
        should_execute = True
        if self.config and "auto_execute" in self.config:
            should_execute = bool(self.config["auto_execute"])
        if request.configuration and "execute" in request.configuration:
            should_execute = bool(request.configuration["execute"])
        elif request.configuration and "auto_execute" in request.configuration:
            should_execute = bool(request.configuration["auto_execute"])

        if should_execute and self.orchestration_engine and executable_workflow:
            await self.execute_project(project_id)

        # Return project info
        estimated_duration = 0.0
        estimated_cost = 0.0
        if strategic_plan:
            estimated_duration = strategic_plan.estimated_duration
            estimated_cost = strategic_plan.estimated_cost
        if executable_workflow:
            estimated_duration = executable_workflow.estimated_duration
            estimated_cost = executable_workflow.estimated_cost

        return {
            "project_id": project_id,
            "status": "created",
            "estimated_duration": estimated_duration,
            "estimated_cost": estimated_cost,
        }

    async def execute_project(
        self,
        project_id: uuid.UUID,
    ) -> dict[str, Any]:
        """
        Execute a planned project through the Orchestration Engine,
        specialist workforce engineering loops, and completion validation.
        """
        project_info = self.active_projects.get(project_id)
        if not project_info:
            raise ValueError(f"Project {project_id} not found in active projects")

        executable_workflow = project_info.get("executable_workflow")
        if not executable_workflow:
            raise RuntimeError(f"No executable workflow found for project {project_id}")

        correlation_id = project_info.get("correlation_id")
        workflow_id = project_info.get("workflow_id") or executable_workflow.workflow_id

        # Step 4: Orchestration -> Execution Engine -> Engineering Loops
        if self.orchestration_engine and executable_workflow:
            # Transition to Running state
            if self.runtime_state_manager:
                await self.runtime_state_manager.transition_state(
                    project_id=project_id,
                    new_status="running",
                    metadata={
                        "workflow_id": str(workflow_id),
                        "strategic_plan": True,
                        "executable_workflow": True,
                    },
                )

            # Publish project.running event
            await publish_event(
                event_bus=self.event_bus,
                event_type=EventType.PROJECT_RUNNING,
                event_category=EventCategory.PROJECT,
                aggregate_id=project_id,
                aggregate_type="Project",
                correlation_id=correlation_id,
                metadata={"workflow_id": str(workflow_id)},
            )

            await self.orchestration_engine.orchestrate(project_id, executable_workflow)

        # Step 5: Completion Validation
        if self.completion_module:
            validation_result = await self.completion_module.validate_completion(project_id)
            if validation_result.get("valid"):
                # Transition to Completing state
                if self.runtime_state_manager:
                    await self.runtime_state_manager.transition_state(
                        project_id=project_id,
                        new_status="completing",
                    )

                # Publish project.completing event
                await publish_event(
                    event_bus=self.event_bus,
                    event_type=EventType.PROJECT_COMPLETING,
                    event_category=EventCategory.PROJECT,
                    aggregate_id=project_id,
                    aggregate_type="Project",
                    correlation_id=correlation_id,
                )

                finalize_result = await self.completion_module.finalize_project(project_id)
                if finalize_result.get("success"):
                    # Publish project.finished event
                    await publish_event(
                        event_bus=self.event_bus,
                        event_type=EventType.PROJECT_FINISHED,
                        event_category=EventCategory.PROJECT,
                        aggregate_id=project_id,
                        aggregate_type="Project",
                        correlation_id=correlation_id,
                        metadata=finalize_result,
                    )

                    # Coordinate infrastructure at project end per Kernel Specification v1.0 Section 15
                    if self.infrastructure_coordinator:
                        await self.infrastructure_coordinator.coordinate_services(
                            lifecycle_point="project_end",
                            context={
                                "project_id": str(project_id),
                                "project_memory": finalize_result,
                            },
                        )

                    # Step 6: Learning & Reflection (Phase 18-K ADR-005; Phase 19B-1 evidence)
                    #
                    # PHASE 19B-1 GATE 4: ``review_findings`` previously read
                    # ``validation_result.get("findings", [])``. ``validate_completion``
                    # never populates a "findings" key, so that branch of the
                    # learning engine was permanently dead.
                    #
                    # The correct repair is NOT to invent a "findings" field.
                    # The real, authoritative evidence already exists in
                    # ``finalize_result``:
                    #   * ``final_review["validation"]`` -- the genuine
                    #     deterministic validation truth, and
                    #   * ``final_review["approved"]``  -- the genuine final
                    #     review verdict.
                    # We pass those through instead. No parallel validation data
                    # is created, completion semantics are untouched, and
                    # validation authority is unchanged.
                    if self.learning_engine and hasattr(self.learning_engine, "reflect_and_learn"):
                        try:
                            await self.learning_engine.reflect_and_learn(
                                project_id=project_id,
                                execution_summary=finalize_result,
                                review_findings=_authoritative_review_findings(finalize_result),
                            )
                        except Exception as ex:
                            logger.warning(f"Kernel learning stage failed: {ex}")
        elif self.learning_engine and hasattr(self.learning_engine, "reflect_and_learn"):
            try:
                await self.learning_engine.reflect_and_learn(
                    project_id=project_id,
                    execution_summary={"status": "finished", "project_id": str(project_id)},
                )
            except Exception as ex:
                logger.warning(f"Kernel learning stage failed: {ex}")

        return {"project_id": project_id, "status": "finished"}

    async def get_status(self, project_id: uuid.UUID) -> dict[str, Any]:
        """
        Get the current status of a project.

        Args:
            project_id: The project to query.

        Returns:
            Dictionary containing status, progress, current_phase, etc.
        """
        if self.runtime_state_manager:
            project = await self.runtime_state_manager.get_project(project_id)
            if not project:
                raise ValueError(f"Project {project_id} not found")

            state = await self.runtime_state_manager.get_project_state(project_id)
            return {
                "project_id": project_id,
                "status": state.get("status", "unknown"),
                "progress": state.get("progress", 0.0),
                "current_phase": state.get("current_phase", "unknown"),
                "active_tasks": state.get("running_count", 0),
                "estimated_completion": state.get("estimated_duration"),
                "metrics": {
                    "duration": state.get("actual_duration", 0.0),
                    "cost": state.get("actual_cost", 0.0),
                    "token_usage": state.get("token_usage", 0),
                },
            }
        else:
            raise RuntimeError("Runtime state manager not configured")

    async def pause(self, project_id: uuid.UUID, reason: str) -> None:
        """
        Pause a running project.

        Args:
            project_id: The project to pause.
            reason: Reason for pausing.
        """
        if self.project_lifecycle_manager:
            await self.project_lifecycle_manager.pause_project(project_id, reason)
        else:
            raise RuntimeError("Project lifecycle manager not configured")

    async def resume(self, project_id: uuid.UUID) -> None:
        """
        Resume a paused project.

        Args:
            project_id: The project to resume.
        """
        if self.project_lifecycle_manager:
            await self.project_lifecycle_manager.resume_project(project_id)
        else:
            raise RuntimeError("Project lifecycle manager not configured")

    async def cancel(self, project_id: uuid.UUID, reason: str) -> None:
        """
        Cancel a project.

        Args:
            project_id: The project to cancel.
            reason: Reason for cancellation.
        """
        if self.project_lifecycle_manager:
            await self.project_lifecycle_manager.cancel_project(project_id, reason)
        else:
            raise RuntimeError("Project lifecycle manager not configured")

    async def restart(self, project_id: uuid.UUID, from_checkpoint_id: uuid.UUID | None = None) -> None:
        """
        Restart a project from a checkpoint or from the beginning.

        Implements the restart operation per Kernel Specification v1.0 Section 6.3.

        Args:
            project_id: The project to restart.
            from_checkpoint_id: Optional checkpoint to restart from. If not provided, restarts from beginning.
        """
        if not self.project_lifecycle_manager:
            raise RuntimeError("Project lifecycle manager not configured")

        # Restore from checkpoint or beginning
        if from_checkpoint_id and self.execution_continuity_manager:
            # Restore from specified checkpoint
            await self.execution_continuity_manager.restore_checkpoint(
                project_id=project_id,
                checkpoint_id=from_checkpoint_id,
            )
        else:
            # Reset project state to Planning
            if self.runtime_state_manager:
                await self.runtime_state_manager.transition_state(
                    project_id=project_id,
                    new_status="planning",
                    metadata={"restarted": True, "restarted_at": make_timestamp()},
                )

        # Resume execution
        await self.project_lifecycle_manager.resume_project(project_id)

    async def subscribe_to_events(
        self,
        event_types: list[EventType],
        callback: Coroutine,
    ) -> str:
        """
        Subscribe to Kernel events.

        Implements the event subscription interface per Kernel Specification v1.0 Section 6.5.

        Args:
            event_types: List of event types to subscribe to.
            callback: Callback handler for events.

        Returns:
            Subscription ID.
        """
        if not self.event_bus:
            raise RuntimeError("Event bus not configured")

        # Generate subscription ID
        subscription_id = str(uuid.uuid4())

        # Register subscription with event bus
        await self.event_bus.subscribe(
            event_types=event_types,
            handler=callback,
        )

        return subscription_id

    async def unsubscribe_from_events(self, subscription_id: str) -> None:
        """
        Unsubscribe from Kernel events.

        Args:
            subscription_id: The subscription ID to unsubscribe.
        """
        # Note: Event bus interface would need to support unsubscribe
        # For now, this is a placeholder that maintains the interface
        pass

    async def submit_approval_decision(
        self,
        approval_id: uuid.UUID,
        decision: str,
        feedback: str | None = None,
        modifications: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        Submit a human approval decision.

        Args:
            approval_id: The approval request identifier.
            decision: The decision (approved, rejected, modified).
            feedback: Optional human feedback.
            modifications: Optional modifications to the plan.

        Returns:
            Dictionary containing status and next_actions.
        """
        if self.approval_coordinator:
            result = await self.approval_coordinator.process_decision(
                approval_id, decision, feedback, modifications
            )
            return result
        else:
            raise RuntimeError("Approval coordinator not configured")

    # ========================================================================
    # Runtime Lifecycle (Section 9 of Specification)
    # ========================================================================

    async def initialize(self) -> None:
        """
        Initialize the Kernel runtime.

        This method initializes all components and prepares the Kernel to accept requests.
        """
        self.status = KernelRuntimeStatus.STARTING

        # Initialize lifecycle coordinator
        if self.lifecycle_coordinator:
            await self.lifecycle_coordinator.coordinate_runtime_lifecycle("initialize")

        # Initialize runtime lifecycle manager
        if self.runtime_lifecycle_manager:
            await self.runtime_lifecycle_manager.initialize()

        # Connect to infrastructure services
        if self.runtime_state_manager:
            # Verify connection to Runtime State Manager via the standard
            # health check contract defined on the Kernel's service ABC.
            await self.runtime_state_manager.health_check()

        if self.event_bus:
            # Subscribe to events
            await self._subscribe_to_events()

        # Publish kernel.starting event
        await publish_event(
            event_bus=self.event_bus,
            event_type=EventType.KERNEL_STARTING,
            event_category=EventCategory.SYSTEM_EVENT,
            aggregate_id=self.kernel_id,
            aggregate_type="Kernel",
            metadata={"version": self.version},
        )

        self.status = KernelRuntimeStatus.READY

        # Publish kernel.ready event
        await publish_event(
            event_bus=self.event_bus,
            event_type=EventType.KERNEL_READY,
            event_category=EventCategory.SYSTEM_EVENT,
            aggregate_id=self.kernel_id,
            aggregate_type="Kernel",
            metadata={"version": self.version},
        )

    async def start(self) -> None:
        """Start the Kernel runtime."""
        if self.runtime_lifecycle_manager:
            await self.runtime_lifecycle_manager.start()
        else:
            self.status = KernelRuntimeStatus.READY

    async def pause_runtime(self, reason: str) -> None:
        """
        Pause the Kernel runtime.

        Args:
            reason: Reason for pausing.
        """
        self.status = KernelRuntimeStatus.PAUSING

        if self.runtime_lifecycle_manager:
            await self.runtime_lifecycle_manager.pause(reason)

        # Publish kernel.paused event
        await publish_event(
            event_bus=self.event_bus,
            event_type=EventType.KERNEL_PAUSED,
            event_category=EventCategory.SYSTEM_EVENT,
            aggregate_id=self.kernel_id,
            aggregate_type="Kernel",
            metadata={"reason": reason},
        )

        self.status = KernelRuntimeStatus.PAUSED

    async def resume_runtime(self) -> None:
        """Resume the Kernel runtime."""
        self.status = KernelRuntimeStatus.RESUMING

        if self.runtime_lifecycle_manager:
            await self.runtime_lifecycle_manager.resume()

        # Publish kernel.resumed event
        await publish_event(
            event_bus=self.event_bus,
            event_type=EventType.KERNEL_RESUMING,
            event_category=EventCategory.SYSTEM_EVENT,
            aggregate_id=self.kernel_id,
            aggregate_type="Kernel",
        )

        self.status = KernelRuntimeStatus.READY

        # Publish kernel.ready event
        await publish_event(
            event_bus=self.event_bus,
            event_type=EventType.KERNEL_READY,
            event_category=EventCategory.SYSTEM_EVENT,
            aggregate_id=self.kernel_id,
            aggregate_type="Kernel",
        )

    async def shutdown(self, reason: str) -> None:
        """
        Shutdown the Kernel runtime.

        Args:
            reason: Reason for shutdown.
        """
        self.status = KernelRuntimeStatus.STOPPING

        # Save checkpoints for all active projects
        for project_id in self.active_projects:
            if self.execution_continuity_manager:
                # Save checkpoint
                await self.execution_continuity_manager.create_checkpoint(project_id)

        # Publish kernel.stopping event
        await publish_event(
            event_bus=self.event_bus,
            event_type=EventType.KERNEL_STOPPING,
            event_category=EventCategory.SYSTEM_EVENT,
            aggregate_id=self.kernel_id,
            aggregate_type="Kernel",
            metadata={"reason": reason},
        )

        # Shutdown runtime lifecycle manager
        if self.runtime_lifecycle_manager:
            await self.runtime_lifecycle_manager.shutdown(reason)

        self.status = KernelRuntimeStatus.STOPPED

        # Publish kernel.stopped event
        await publish_event(
            event_bus=self.event_bus,
            event_type=EventType.KERNEL_STOPPED,
            event_category=EventCategory.SYSTEM_EVENT,
            aggregate_id=self.kernel_id,
            aggregate_type="Kernel",
            metadata={"reason": reason},
        )

    def get_runtime_status(self) -> str:
        """Get the current runtime status."""
        return self.status.value

    # ========================================================================
    # Internal Methods
    # ========================================================================

    async def _publish_event(
        self,
        event_type: EventType,
        event_category: EventCategory,
        aggregate_id: uuid.UUID,
        aggregate_type: str,
        correlation_id: uuid.UUID | None = None,
        causation_id: uuid.UUID | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """
        Publish an event to the Event Bus.

        Args:
            event_type: The type of event.
            event_category: The category of event.
            aggregate_id: The ID of the aggregate this event relates to.
            aggregate_type: The type of the aggregate.
            correlation_id: Optional correlation ID.
            causation_id: Optional causation ID.
            metadata: Optional metadata.
        """
        await publish_event(
            event_bus=self.event_bus,
            event_type=event_type,
            event_category=event_category,
            aggregate_id=aggregate_id,
            aggregate_type=aggregate_type,
            correlation_id=correlation_id,
            causation_id=causation_id,
            metadata=metadata,
        )

    async def _subscribe_to_events(self) -> None:
        """Subscribe to events from the Event Bus."""
        if not self.event_bus:
            return

        # Subscribe to loop events
        await self.event_bus.subscribe(
            event_types=[
                EventType.LOOP_COMPLETED,
                EventType.LOOP_REMEDIATING,
                EventType.LOOP_ESCALATED,
                EventType.LOOP_FAILED,
            ],
            handler=self._handle_loop_event,
        )

        # Subscribe to task events
        await self.event_bus.subscribe(
            event_types=[
                EventType.TASK_COMPLETED,
                EventType.TASK_FAILED,
                EventType.TASK_PAUSED,
                EventType.TASK_BLOCKED,
            ],
            handler=self._handle_task_event,
        )

        # Subscribe to approval events
        await self.event_bus.subscribe(
            event_types=[
                EventType.APPROVAL_DECIDED,
                EventType.APPROVAL_TIMEOUT,
                EventType.APPROVAL_ESCALATED,
            ],
            handler=self._handle_approval_event,
        )

        # Subscribe to review events
        await self.event_bus.subscribe(
            event_types=[
                EventType.REVIEW_COMPLETED,
                EventType.REVIEW_APPROVED,
                EventType.REVIEW_REJECTED,
                EventType.REVIEW_CHANGES_REQUESTED,
            ],
            handler=self._handle_review_event,
        )

        # Subscribe to recovery events
        await self.event_bus.subscribe(
            event_types=[
                EventType.RECOVERY_COMPLETED,
                EventType.RECOVERY_FAILED,
                EventType.CHECKPOINT_RESTORED,
            ],
            handler=self._handle_recovery_event,
        )

        # Subscribe to infrastructure service events
        await self.event_bus.subscribe(
            event_types=[
                EventType.SERVICE_DEGRADED,
                EventType.SERVICE_RECOVERED,
                EventType.SERVICE_FAILED,
            ],
            handler=self._handle_service_event,
        )

    async def _handle_loop_event(self, event: DomainBaseEvent) -> None:
        """Handle loop lifecycle events."""
        if event.metadata.get("handled"):
            # Event was already handled and published by orchestration_engine; do not create a re-entrant loop.
            return

        project_id = event.aggregate_id
        loop_type = event.metadata.get("loop_type", "unknown")
        event_type = event.event_type

        if event_type == EventType.LOOP_COMPLETED:
            # Loop completed successfully - proceed to next loop
            if self.orchestration_engine:
                await self.orchestration_engine.handle_loop_completion(
                    project_id, {"status": "complete", "loop_type": loop_type}
                )
        elif event_type == EventType.LOOP_FAILED:
            # Loop failed - handle failure
            if self.orchestration_engine:
                await self.orchestration_engine.handle_failure(
                    project_id, {"error": event.metadata.get("error", "Unknown error")}
                )
        elif event_type == EventType.LOOP_REMEDIATING:
            # Loop requires remediation
            if self.orchestration_engine:
                await self.orchestration_engine.handle_loop_completion(
                    project_id, {"status": "remediate", "loop_type": loop_type}
                )
        elif event_type == EventType.LOOP_ESCALATED:
            # Loop rejected - escalate
            if self.orchestration_engine:
                await self.orchestration_engine.handle_loop_completion(
                    project_id, {"status": "escalate", "loop_type": loop_type, "reason": event.metadata.get("reason", "Rejected")}
                )

    async def _handle_task_event(self, event: DomainBaseEvent) -> None:
        """Handle task lifecycle events."""
        project_id = event.aggregate_id
        task_id = event.metadata.get("task_id")
        event_type = event.event_type

        if event_type == EventType.TASK_COMPLETED:
            # Task completed - update state
            if self.runtime_state_manager:
                try:
                    state = await self.runtime_state_manager.get_project_state(project_id)
                except Exception:
                    state = None
                if state:
                    completed = state.get("completed_count", 0) + 1
                    total = state.get("task_count", 1)
                    progress = (completed / total) * 100.0 if total > 0 else 0.0
                    await self.runtime_state_manager.transition_state(
                        project_id, state.get("status", "running"),
                        metadata={"completed_count": completed, "progress": progress}
                    )
        elif event_type == EventType.TASK_FAILED:
            # Task failed - apply retry policy
            if self.recovery_module:
                await self.recovery_module.handle_failure(
                    project_id, {"error": event.metadata.get("error", "Unknown error"), "task_id": task_id}
                )
        elif event_type == EventType.TASK_PAUSED:
            # Task paused - update state
            if self.runtime_state_manager:
                try:
                    state = await self.runtime_state_manager.get_project_state(project_id)
                except Exception:
                    state = None
                if state:
                    await self.runtime_state_manager.transition_state(
                        project_id, "paused",
                        metadata={"paused_task_id": task_id}
                    )
        elif event_type == EventType.TASK_BLOCKED:
            # Task blocked - update state
            if self.runtime_state_manager:
                try:
                    state = await self.runtime_state_manager.get_project_state(project_id)
                except Exception:
                    state = None
                if state:
                    await self.runtime_state_manager.transition_state(
                        project_id, "running",
                        metadata={"blocked_task_id": task_id, "blocked_by": event.metadata.get("blocked_by")}
                    )

    async def _handle_approval_event(self, event: DomainBaseEvent) -> None:
        """Handle approval events."""
        project_id = event.aggregate_id
        approval_id = event.metadata.get("approval_id")
        event_type = event.event_type

        if not self.approval_coordinator or not approval_id:
            return

        try:
            approval_uuid = uuid.UUID(approval_id) if isinstance(approval_id, str) else approval_id
        except (ValueError, TypeError):
            return

        # Only handle APPROVAL_DECIDED events - the decision is in metadata
        if event_type != EventType.APPROVAL_DECIDED:
            return

        decision = event.metadata.get("decision", "").lower()

        try:
            if decision == "approved":
                # Approval granted - resume execution
                await self.approval_coordinator.process_decision(
                    approval_uuid,
                    "approved",
                    feedback=event.metadata.get("feedback"),
                )
            elif decision == "rejected":
                # Approval rejected - fail or modify
                await self.approval_coordinator.process_decision(
                    approval_uuid,
                    "rejected",
                    feedback=event.metadata.get("feedback"),
                )
            elif decision in ["modified", "changes_requested"]:
                # Changes requested - create remediation
                await self.approval_coordinator.process_decision(
                    approval_uuid,
                    "modified",
                    feedback=event.metadata.get("feedback"),
                    modifications=event.metadata.get("modifications"),
                )
        except ValueError:
            # Approval not found - this is expected for test events
            pass

    async def _handle_review_event(self, event: DomainBaseEvent) -> None:
        """Handle review engine events."""
        project_id = event.aggregate_id
        event_type = event.event_type

        if event_type == EventType.REVIEW_COMPLETED:
            # Review completed - process decision
            if self.orchestration_engine:
                await self.orchestration_engine.handle_loop_completion(
                    project_id, {"status": "complete", "loop_type": "review"}
                )
        elif event_type == EventType.REVIEW_APPROVED:
            # Artifact approved - release to downstream
            if self.runtime_state_manager:
                await self.runtime_state_manager.transition_state(
                    project_id, "running",
                    metadata={"review_approved": True}
                )
        elif event_type == EventType.REVIEW_REJECTED:
            # Artifact rejected - create remediation task
            if self.orchestration_engine:
                await self.orchestration_engine.handle_loop_completion(
                    project_id, {"status": "remediate", "loop_type": "review"}
                )
        elif event_type == EventType.REVIEW_CHANGES_REQUESTED:
            # Changes requested - create remediation task
            if self.orchestration_engine:
                await self.orchestration_engine.handle_loop_completion(
                    project_id, {"status": "remediate", "loop_type": "review"}
                )

    async def _handle_recovery_event(self, event: DomainBaseEvent) -> None:
        """Handle execution continuity manager events."""
        project_id = event.aggregate_id
        event_type = event.event_type

        if event_type == EventType.RECOVERY_COMPLETED:
            # Recovery completed - resume execution
            if self.runtime_state_manager:
                await self.runtime_state_manager.transition_state(
                    project_id, "running",
                    metadata={"recovery_completed": True}
                )
        elif event_type == EventType.RECOVERY_FAILED:
            # Recovery failed - escalate to human
            if self.approval_coordinator:
                await self.approval_coordinator.request_approval(
                    project_id,
                    {"type": "recovery_failure", "error": event.metadata.get("error", "Recovery failed")}
                )
        elif event_type == EventType.CHECKPOINT_RESTORED:
            # Checkpoint restored - resume from checkpoint
            if self.runtime_state_manager:
                await self.runtime_state_manager.transition_state(
                    project_id, "running",
                    metadata={"checkpoint_restored": True}
                )

    async def _handle_service_event(self, event: DomainBaseEvent) -> None:
        """Handle infrastructure service events."""
        project_id = event.aggregate_id
        event_type = event.event_type

        if event_type == EventType.SERVICE_DEGRADED:
            # Service degraded - adjust execution
            if self.runtime_state_manager:
                await self.runtime_state_manager.transition_state(
                    project_id, "running",
                    metadata={"service_degraded": True, "service": event.metadata.get("service")}
                )
        elif event_type == EventType.SERVICE_RECOVERED:
            # Service recovered - resume normal operation
            if self.runtime_state_manager:
                await self.runtime_state_manager.transition_state(
                    project_id, "running",
                    metadata={"service_recovered": True, "service": event.metadata.get("service")}
                )
        elif event_type == EventType.SERVICE_FAILED:
            # Service failed - invoke failover
            if self.execution_continuity_manager:
                await self.execution_continuity_manager.failover(
                    project_id, event.metadata.get("service", "unknown")
                )

    # ========================================================================
    # String Representation
    # ========================================================================

    def __repr__(self) -> str:
        """String representation of the Kernel."""
        return (
            f"Kernel("
            f"kernel_id={self.kernel_id}, "
            f"version={self.version}, "
            f"status={self.status.value}, "
            f"active_projects={len(self.active_projects)}"
            f")"
        )