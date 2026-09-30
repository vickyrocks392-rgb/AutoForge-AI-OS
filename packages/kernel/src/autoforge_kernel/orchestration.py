"""
Engine Orchestration Module

Responsible for coordinating execution of the Executable Workflow through
the Execution Engine. This module implements the Engine Orchestration
component of the Kernel.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

logger = logging.getLogger(__name__)

from autoforge_events.event_types import EventCategory, EventType

from autoforge_kernel.interfaces import (
    OrchestrationEngine,
    LoopOrchestrator,
    WorkerDispatchCoordinator,
    Request,
    IntentAnalysisResult,
    StrategicPlan,
    ExecutableWorkflow,
    ExecutionEngine,
    ReviewEngine,
    EventBus,
    RuntimeStateManager,
    ExecutionContinuityManager,
    ModelRouter,
)
from autoforge_kernel.event_utils import publish_event, make_timestamp


class DefaultOrchestrationEngine(OrchestrationEngine):
    """
    Default implementation of the orchestration engine.

    Coordinates execution of the Executable Workflow through the Execution Engine.
    """

    def __init__(
        self,
        execution_engine: ExecutionEngine | None = None,
        review_engine: ReviewEngine | None = None,
        loop_orchestrator: LoopOrchestrator | None = None,
        worker_dispatch_coordinator: WorkerDispatchCoordinator | None = None,
        event_bus: EventBus | None = None,
        runtime_state_manager: RuntimeStateManager | None = None,
        execution_continuity_manager: ExecutionContinuityManager | None = None,
        model_router: ModelRouter | None = None,
    ):
        """
        Initialize the orchestration engine.

        Args:
            execution_engine: Execution Engine for executing loops.
            review_engine: Review Engine for reviewing artifacts.
            loop_orchestrator: Loop orchestrator.
            worker_dispatch_coordinator: Worker dispatch coordinator.
            event_bus: Event bus for publishing events.
            runtime_state_manager: Runtime state manager for state operations.
            execution_continuity_manager: Execution continuity manager for recovery.
            model_router: Model router for model selection.
        """
        self.execution_engine = execution_engine
        self.review_engine = review_engine
        self.loop_orchestrator = loop_orchestrator or DefaultLoopOrchestrator(
            execution_engine=execution_engine,
            review_engine=review_engine,
            event_bus=event_bus,
            runtime_state_manager=runtime_state_manager,
        )
        self.worker_dispatch_coordinator = worker_dispatch_coordinator or DefaultWorkerDispatchCoordinator(
            execution_engine=execution_engine,
            event_bus=event_bus,
            runtime_state_manager=runtime_state_manager,
            model_router=model_router,
        )
        self.event_bus = event_bus
        self.runtime_state_manager = runtime_state_manager
        self.execution_continuity_manager = execution_continuity_manager
        self.model_router = model_router

    async def orchestrate(
        self,
        project_id: uuid.UUID,
        executable_workflow: ExecutableWorkflow,
    ) -> None:
        """
        Orchestrate execution of an executable workflow.

        Args:
            project_id: The project to orchestrate.
            executable_workflow: The executable workflow to execute.
        """
        # Update project state to Running
        if self.runtime_state_manager:
            await self.runtime_state_manager.transition_state(
                project_id=project_id,
                new_status="Running",
                metadata={"workflow_id": str(executable_workflow.workflow_id)},
            )

        # Publish project.running event
        await publish_event(
            event_bus=self.event_bus,
            event_type=EventType.PROJECT_RUNNING,
            event_category=EventCategory.PROJECT,
            aggregate_id=project_id,
            aggregate_type="Project",
            metadata={"workflow_id": str(executable_workflow.workflow_id)},
        )

        # Execute each loop in the workflow
        #
        # DEF-18L-03: carry the ORIGINAL user request into every loop context.
        #
        # ``KernelExecutionEngineAdapter.execute_loop`` builds the task's
        # ``input_data`` from ``context["request_text"]`` when the loop supplies
        # none. O-2 never populated that key, so the engineering model was
        # handed a task NAME ("Core Implementation") instead of the actual
        # specification, and produced a generic single file that could not
        # satisfy the project.
        #
        # The request is read from the authoritative Runtime state -- the same
        # source the rest of the completion path uses -- so no new state is
        # invented and the correlation stays durable. A read failure is
        # non-fatal: it degrades to the previous behaviour rather than
        # blocking execution.
        request_text = ""
        if self.runtime_state_manager is not None:
            try:
                project_state = await self.runtime_state_manager.get_project_state(
                    project_id
                )
                if isinstance(project_state, dict):
                    # The authoritative Runtime state keeps the full, untruncated
                    # request under ``request["description"]`` (the shape the
                    # KernelRuntimeFacade projects). Callers that wrote
                    # ``description`` directly or ``metadata["original_request"]``
                    # are accepted as fallbacks rather than assumed.
                    req = project_state.get("request")
                    desc = ""
                    if isinstance(req, dict):
                        desc = str(req.get("description") or "")
                    request_text = desc or str(
                        project_state.get("description")
                        or (project_state.get("metadata") or {}).get(
                            "original_request", ""
                        )
                        or ""
                    )
            except Exception as exc:  # pragma: no cover - defensive only
                logger.warning(
                    "Could not read request text for project %s: %s", project_id, exc
                )

        for loop in executable_workflow.loops:
            loop_type = loop.get("type", "unknown")
            loop_context = {
                "project_id": str(project_id),
                "workflow_id": str(executable_workflow.workflow_id),
                "loop": loop,
                "request_text": request_text,
            }

            # Publish loop.started event
            await publish_event(
                event_bus=self.event_bus,
                event_type=EventType.LOOP_STARTED,
                event_category=EventCategory.LOOP,
                aggregate_id=project_id,
                aggregate_type="Project",
                metadata={"loop_type": loop_type},
            )

            # Publish loop.planning event
            await publish_event(
                event_bus=self.event_bus,
                event_type=EventType.LOOP_PLANNING,
                event_category=EventCategory.LOOP,
                aggregate_id=project_id,
                aggregate_type="Project",
                metadata={"loop_type": loop_type},
            )

            # Publish loop.executing event
            await publish_event(
                event_bus=self.event_bus,
                event_type=EventType.LOOP_EXECUTING,
                event_category=EventCategory.LOOP,
                aggregate_id=project_id,
                aggregate_type="Project",
                metadata={"loop_type": loop_type},
            )

            # Orchestrate the loop
            loop_result = await self.loop_orchestrator.orchestrate_loop(
                project_id=project_id,
                loop_type=loop_type,
                loop_context=loop_context,
            )

            # Handle loop completion
            await self.handle_loop_completion(project_id, loop_result)

    async def handle_loop_completion(
        self,
        project_id: uuid.UUID,
        loop_result: dict[str, Any],
    ) -> None:
        """
        Handle completion of an engineering loop.

        Args:
            project_id: The project.
            loop_result: The loop result.
        """
        status = loop_result.get("status", "unknown")
        loop_type = loop_result.get("loop_type", "unknown")

        if status == "complete":
            # Loop completed successfully
            await publish_event(
                event_bus=self.event_bus,
                event_type=EventType.LOOP_COMPLETED,
                event_category=EventCategory.LOOP,
                aggregate_id=project_id,
                aggregate_type="Project",
                metadata={"loop_type": loop_type},
            )

        elif status == "remediate":
            # Loop requires remediation
            await publish_event(
                event_bus=self.event_bus,
                event_type=EventType.LOOP_REMEDIATING,
                event_category=EventCategory.LOOP,
                aggregate_id=project_id,
                aggregate_type="Project",
                metadata={"loop_type": loop_type, "findings": loop_result.get("findings", {})},
            )
            await self._handle_remediation(project_id, loop_result)

        elif status == "escalate":
            # Loop requires human intervention
            await publish_event(
                event_bus=self.event_bus,
                event_type=EventType.LOOP_ESCALATED,
                event_category=EventCategory.LOOP,
                aggregate_id=project_id,
                aggregate_type="Project",
                metadata={"loop_type": loop_type, "reason": loop_result.get("reason", "Unknown")},
            )
            await self._handle_escalation(project_id, loop_result)

        elif status == "failed":
            # Loop failed
            await publish_event(
                event_bus=self.event_bus,
                event_type=EventType.LOOP_FAILED,
                event_category=EventCategory.LOOP,
                aggregate_id=project_id,
                aggregate_type="Project",
                metadata={"loop_type": loop_type, "error": loop_result.get("error", "Unknown error")},
            )
            await self.handle_failure(project_id, loop_result)

    async def handle_failure(
        self,
        project_id: uuid.UUID,
        failure: dict[str, Any],
    ) -> None:
        """
        Handle a failure during execution.

        Args:
            project_id: The project.
            failure: The failure details.
        """
        # Publish failure.detected event
        await publish_event(
            event_bus=self.event_bus,
            event_type=EventType.FAILURE_DETECTED,
            event_category=EventCategory.FAILURE,
            aggregate_id=project_id,
            aggregate_type="Project",
            metadata={"error": failure.get("error", "Unknown error"), "source": failure.get("loop_type", "unknown")},
        )

        # Attempt recovery if execution continuity manager is available
        if self.execution_continuity_manager:
            try:
                # Publish recovery.started event
                await publish_event(
                    event_bus=self.event_bus,
                    event_type=EventType.RECOVERY_STARTED,
                    event_category=EventCategory.FAILURE,
                    aggregate_id=project_id,
                    aggregate_type="Project",
                    metadata={"failure_id": str(failure.get("failure_id", uuid.uuid4()))},
                )

                recovery_result = await self.execution_continuity_manager.recover(
                    failure_context=failure
                )
                if recovery_result.get("success"):
                    # Publish recovery.completed event
                    await publish_event(
                        event_bus=self.event_bus,
                        event_type=EventType.RECOVERY_COMPLETED,
                        event_category=EventCategory.FAILURE,
                        aggregate_id=project_id,
                        aggregate_type="Project",
                        metadata={"recovery_strategy": recovery_result.get("strategy", "unknown")},
                    )
                else:
                    # Publish recovery.failed event
                    await publish_event(
                        event_bus=self.event_bus,
                        event_type=EventType.RECOVERY_FAILED,
                        event_category=EventCategory.FAILURE,
                        aggregate_id=project_id,
                        aggregate_type="Project",
                        metadata={"error": recovery_result.get("error", "Recovery failed")},
                    )
            except Exception:
                # Recovery failed, escalate to human
                await publish_event(
                    event_bus=self.event_bus,
                    event_type=EventType.RECOVERY_FAILED,
                    event_category=EventCategory.FAILURE,
                    aggregate_id=project_id,
                    aggregate_type="Project",
                    metadata={"error": "Recovery failed with exception"},
                )

    async def _handle_remediation(self, project_id: uuid.UUID, loop_result: dict[str, Any]) -> None:
        """
        Handle loop remediation.

        Args:
            project_id: The project.
            loop_result: The loop result.
        """
        # Get remediation tasks
        remediation_tasks = loop_result.get("remediation_tasks", [])

        # Dispatch workers for remediation tasks
        for task in remediation_tasks:
            await self.worker_dispatch_coordinator.dispatch_worker(
                project_id=project_id,
                task=task,
            )

    async def _handle_escalation(self, project_id: uuid.UUID, loop_result: dict[str, Any]) -> None:
        """
        Handle loop escalation to human.

        Args:
            project_id: The project.
            loop_result: The loop result.
        """
        # Update project state to Reviewing
        if self.runtime_state_manager:
            await self.runtime_state_manager.transition_state(
                project_id=project_id,
                new_status="reviewing",
            )

        # Publish project.reviewing event
        await publish_event(
            event_bus=self.event_bus,
            event_type=EventType.PROJECT_REVIEWING,
            event_category=EventCategory.PROJECT,
            aggregate_id=project_id,
            aggregate_type="Project",
            metadata={"reason": loop_result.get("reason", "Unknown")},
        )


class DefaultLoopOrchestrator(LoopOrchestrator):
    """
    Default implementation of loop orchestration.
    """

    def __init__(
        self,
        execution_engine: ExecutionEngine | None = None,
        review_engine: ReviewEngine | None = None,
        event_bus: EventBus | None = None,
        runtime_state_manager: RuntimeStateManager | None = None,
    ):
        """
        Initialize the loop orchestrator.

        Args:
            execution_engine: Execution Engine.
            review_engine: Review Engine.
            event_bus: Event bus.
            runtime_state_manager: Runtime state manager.
        """
        self.execution_engine = execution_engine
        self.review_engine = review_engine
        self.event_bus = event_bus
        self.runtime_state_manager = runtime_state_manager

    async def orchestrate_loop(
        self,
        project_id: uuid.UUID,
        loop_type: str,
        loop_context: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Orchestrate a single engineering loop.

        Args:
            project_id: The project.
            loop_type: The type of loop.
            loop_context: The loop context.

        Returns:
            Loop result.
        """
        if not self.execution_engine:
            raise RuntimeError("Execution Engine not configured")

        # Publish loop.planning event
        await publish_event(
            event_bus=self.event_bus,
            event_type=EventType.LOOP_PLANNING,
            event_category=EventCategory.LOOP,
            aggregate_id=project_id,
            aggregate_type="Project",
            metadata={"loop_type": loop_type},
        )

        # Publish loop.executing event
        await publish_event(
            event_bus=self.event_bus,
            event_type=EventType.LOOP_EXECUTING,
            event_category=EventCategory.LOOP,
            aggregate_id=project_id,
            aggregate_type="Project",
            metadata={"loop_type": loop_type},
        )

        # Execute the loop
        loop_result = await self.execution_engine.execute_loop(
            loop_type=loop_type,
            loop_input=loop_context,
            context=loop_context,
        )

        # Publish loop.reviewing event after execution
        await publish_event(
            event_bus=self.event_bus,
            event_type=EventType.LOOP_REVIEWING,
            event_category=EventCategory.LOOP,
            aggregate_id=project_id,
            aggregate_type="Project",
            metadata={"loop_type": loop_type},
        )

        # Add loop type to result
        loop_result["loop_type"] = loop_type

        return loop_result


class DefaultWorkerDispatchCoordinator(WorkerDispatchCoordinator):
    """
    Default implementation of worker dispatch coordination.

    Implements the Worker Dispatch Module per Kernel Specification v1.0 Section 7.5:
    - Assignment Validator: Validates worker assignments from Workflow Engine
    - Dispatch Executor: Executes worker dispatch operations
    - Dispatch Monitor: Monitors dispatch execution and status
    - Dispatch State Synchronizer: Synchronizes dispatch state with Runtime State Manager
    """

    def __init__(
        self,
        execution_engine: ExecutionEngine | None = None,
        event_bus: EventBus | None = None,
        runtime_state_manager: RuntimeStateManager | None = None,
        model_router: ModelRouter | None = None,
    ):
        """
        Initialize the worker dispatch coordinator.

        Args:
            execution_engine: Execution Engine.
            event_bus: Event bus.
            runtime_state_manager: Runtime state manager.
            model_router: Model router.
        """
        self.execution_engine = execution_engine
        self.event_bus = event_bus
        self.runtime_state_manager = runtime_state_manager
        self.model_router = model_router

    async def dispatch_worker(
        self,
        project_id: uuid.UUID,
        task: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Dispatch a worker for a task.

        Implements the full dispatch process:
        1. Assignment validation
        2. Dispatch execution
        3. Dispatch monitoring
        4. Dispatch state synchronization

        Args:
            project_id: The project.
            task: The task to dispatch.

        Returns:
            Task result.
        """
        if not self.execution_engine:
            raise RuntimeError("Execution Engine not configured")

        # Step 1: Assignment Validation
        # Validate worker assignment from Workflow Engine
        worker_type = task.get("worker_type", "default")
        task_id = task.get("task_id", str(uuid.uuid4()))
        self._validate_assignment(worker_type, task)

        # Step 2: Select model if model router is available
        if self.model_router:
            try:
                model = await self.model_router.select_model(task=task)
                task["model"] = model.to_dict()
            except Exception:
                # Model selection failed, continue without model
                pass

        # Step 3: Dispatch Execution
        # Publish worker.dispatched event per Kernel Specification v1.0 Section 14.2
        await publish_event(
            event_bus=self.event_bus,
            event_type=EventType.WORKER_DISPATCHED,
            event_category=EventCategory.TASK,
            aggregate_id=project_id,
            aggregate_type="Project",
            metadata={
                "task_id": task_id,
                "worker": worker_type,
                "model": task.get("model", {}).get("model_id", "unknown"),
            },
        )

        # Execute dispatch through Execution Engine
        result = await self.execution_engine.dispatch_worker(
            worker_type=worker_type,
            task=task,
            context={"project_id": str(project_id)},
        )

        # Step 4: Dispatch Monitoring & State Synchronization
        # Update task state in Runtime State Manager
        if self.runtime_state_manager:
            await self.runtime_state_manager.transition_state(
                project_id=project_id,
                new_status="running",
                metadata={
                    "task_id": task_id,
                    "worker_type": worker_type,
                    "dispatched_at": make_timestamp(),
                },
            )

        # Publish task.started event
        await publish_event(
            event_bus=self.event_bus,
            event_type=EventType.TASK_STARTED,
            event_category=EventCategory.TASK,
            aggregate_id=project_id,
            aggregate_type="Project",
            metadata={"task_id": task_id, "worker_type": worker_type},
        )

        return result

    def _validate_assignment(self, worker_type: str, task: dict[str, Any]) -> None:
        """
        Validate worker assignment from Workflow Engine.

        Args:
            worker_type: The type of worker.
            task: The task definition.

        Raises:
            ValueError: If the assignment is invalid.
        """
        if not worker_type:
            raise ValueError("Worker type must be specified")

        if not task.get("task_id") and not task.get("description"):
            raise ValueError("Task must have a task_id or description")

        # Validate that required fields are present
        required_fields = ["description"]
        for field in required_fields:
            if field not in task and field != "task_id":
                raise ValueError(f"Task missing required field: {field}")


class OrchestrationModule:
    """
    Orchestration Module.

    Coordinates execution of the Executable Workflow.
    """

    def __init__(
        self,
        orchestration_engine: OrchestrationEngine | None = None,
        execution_engine: ExecutionEngine | None = None,
        review_engine: ReviewEngine | None = None,
        event_bus: EventBus | None = None,
        runtime_state_manager: RuntimeStateManager | None = None,
        execution_continuity_manager: ExecutionContinuityManager | None = None,
        model_router: ModelRouter | None = None,
    ):
        """
        Initialize the orchestration module.

        Args:
            orchestration_engine: Orchestration engine.
            execution_engine: Execution Engine.
            review_engine: Review Engine.
            event_bus: Event bus.
            runtime_state_manager: Runtime state manager.
            execution_continuity_manager: Execution continuity manager.
            model_router: Model router.
        """
        self.orchestration_engine = orchestration_engine or DefaultOrchestrationEngine(
            execution_engine=execution_engine,
            review_engine=review_engine,
            event_bus=event_bus,
            runtime_state_manager=runtime_state_manager,
            execution_continuity_manager=execution_continuity_manager,
            model_router=model_router,
        )

    async def orchestrate(
        self,
        project_id: uuid.UUID,
        executable_workflow: ExecutableWorkflow,
    ) -> None:
        """
        Orchestrate execution of an executable workflow.

        Args:
            project_id: The project.
            executable_workflow: The executable workflow.
        """
        await self.orchestration_engine.orchestrate(project_id, executable_workflow)

    async def handle_loop_completion(
        self,
        project_id: uuid.UUID,
        loop_result: dict[str, Any],
    ) -> None:
        """
        Handle loop completion.

        Args:
            project_id: The project.
            loop_result: The loop result.
        """
        await self.orchestration_engine.handle_loop_completion(project_id, loop_result)

    async def handle_failure(
        self,
        project_id: uuid.UUID,
        failure: dict[str, Any],
    ) -> None:
        """
        Handle failure.

        Args:
            project_id: The project.
            failure: The failure details.
        """
        await self.orchestration_engine.handle_failure(project_id, failure)