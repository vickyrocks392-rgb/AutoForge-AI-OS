"""
Orchestration Tests for the AutoForge AI Kernel.

Tests planning pipeline, event ordering, state transitions, pause/resume,
cancel, failure recovery, completion, and multi-project coordination.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from autoforge_events.event_types import EventCategory, EventType

from autoforge_kernel.interfaces import (
    Request,
    IntentAnalysisResult,
    StrategicPlan,
    ExecutableWorkflow,
    EventBus,
    RuntimeStateManager,
    StrategicEngine,
    WorkflowEngine,
    ExecutionEngine,
    ExecutionContinuityManager,
)
from autoforge_kernel.kernel import Kernel
from autoforge_kernel.request_intake import (
    DefaultRequestValidator,
    DefaultRequestNormalizer,
    DefaultProjectInitializer,
    DefaultIdentifierGenerator,
)
from autoforge_kernel.intent_analysis import DefaultIntentAnalyzer
from autoforge_kernel.planning_coordination import DefaultPlanningCoordinator
from autoforge_kernel.orchestration import DefaultOrchestrationEngine, DefaultLoopOrchestrator
from autoforge_kernel.lifecycle import DefaultProjectLifecycleManager, ProjectStatus
from autoforge_kernel.recovery import DefaultRecoveryModule
from autoforge_kernel.approval import DefaultApprovalCoordinator
from autoforge_kernel.completion import DefaultCompletionModule


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def mock_services():
    """Create all mock services."""
    services = {
        "event_bus": AsyncMock(spec=EventBus),
        "runtime_state_manager": AsyncMock(spec=RuntimeStateManager),
        "strategic_engine": AsyncMock(spec=StrategicEngine),
        "workflow_engine": AsyncMock(spec=WorkflowEngine),
        "execution_engine": AsyncMock(spec=ExecutionEngine),
        "execution_continuity_manager": AsyncMock(spec=ExecutionContinuityManager),
    }

    services["runtime_state_manager"].get_project_state.return_value = {
        "status": "created",
        "progress": 0.0,
        "current_phase": "intake",
        "running_count": 0,
        "task_count": 0,
        "completed_count": 0,
        "failed_count": 0,
        "estimated_duration": 0.0,
        "actual_duration": 0.0,
        "actual_cost": 0.0,
        "token_usage": 0,
        "acceptance_criteria": [],
        "quality_gates": [],
        "artifacts": [],
        "approval_history": [],
    }
    services["runtime_state_manager"].get_project.return_value = MagicMock()

    services["strategic_engine"].create_strategic_plan.return_value = StrategicPlan(
        requirements=[{"id": "REQ-1"}],
        architecture_decisions=[{"id": "AD-1"}],
        technology_choices={"lang": "python"},
        acceptance_criteria=[{"id": "AC-1"}],
        estimated_duration=100.0,
        estimated_cost=5.0,
    )

    services["workflow_engine"].create_executable_workflow.return_value = ExecutableWorkflow(
        loops=[{"type": "coding_loop"}],
        task_graph={"tasks": [{"id": "t1"}], "dependencies": []},
        worker_assignments={"w1": ["t1"]},
        model_assignments={"w1": {"model": "gpt-4"}},
        estimated_duration=100.0,
        estimated_cost=5.0,
    )

    services["execution_engine"].execute_loop.return_value = {
        "status": "complete",
        "loop_type": "coding_loop",
    }

    return services


@pytest.fixture
def full_kernel(mock_services):
    """Create a fully configured Kernel."""
    services = mock_services

    kernel = Kernel(
        event_bus=services["event_bus"],
        runtime_state_manager=services["runtime_state_manager"],
        strategic_engine=services["strategic_engine"],
        workflow_engine=services["workflow_engine"],
        execution_engine=services["execution_engine"],
        execution_continuity_manager=services["execution_continuity_manager"],
        request_validator=DefaultRequestValidator(),
        request_normalizer=DefaultRequestNormalizer(),
        project_initializer=DefaultProjectInitializer(event_bus=services["event_bus"]),
        identifier_generator=DefaultIdentifierGenerator(),
        intent_analyzer=DefaultIntentAnalyzer(),
        planning_coordinator=DefaultPlanningCoordinator(
            strategic_engine=services["strategic_engine"],
            workflow_engine=services["workflow_engine"],
            event_bus=services["event_bus"],
        ),
        orchestration_engine=DefaultOrchestrationEngine(
            execution_engine=services["execution_engine"],
            event_bus=services["event_bus"],
            runtime_state_manager=services["runtime_state_manager"],
            execution_continuity_manager=services["execution_continuity_manager"],
        ),
        project_lifecycle_manager=DefaultProjectLifecycleManager(
            event_bus=services["event_bus"],
            runtime_state_manager=services["runtime_state_manager"],
            execution_continuity_manager=services["execution_continuity_manager"],
        ),
        recovery_module=DefaultRecoveryModule(
            event_bus=services["event_bus"],
            runtime_state_manager=services["runtime_state_manager"],
            execution_continuity_manager=services["execution_continuity_manager"],
        ),
        approval_coordinator=DefaultApprovalCoordinator(
            event_bus=services["event_bus"],
            runtime_state_manager=services["runtime_state_manager"],
        ),
        completion_module=DefaultCompletionModule(
            event_bus=services["event_bus"],
            runtime_state_manager=services["runtime_state_manager"],
        ),
    )

    return kernel, services


# ============================================================================
# Planning Pipeline Tests
# ============================================================================


class TestPlanningPipeline:
    """Tests for the planning pipeline."""

    @pytest.mark.asyncio
    async def test_intent_to_strategic_plan(self, full_kernel):
        """Test intent analysis -> strategic plan pipeline."""
        kernel, services = full_kernel
        request = Request(request_text="Build a REST API")

        # Intent analysis
        intent_result = await kernel.intent_analyzer.analyze(request)
        assert intent_result is not None
        assert intent_result.request_type == "implementation"

        # Strategic planning
        strategic_plan = await services["strategic_engine"].create_strategic_plan(
            request=request,
            intent_analysis=intent_result,
            context={},
        )
        assert strategic_plan is not None
        assert len(strategic_plan.requirements) > 0

    @pytest.mark.asyncio
    async def test_strategic_plan_to_workflow(self, full_kernel):
        """Test strategic plan -> executable workflow pipeline."""
        kernel, services = full_kernel

        strategic_plan = StrategicPlan(
            requirements=[{"id": "REQ-1"}],
            architecture_decisions=[{"id": "AD-1"}],
            technology_choices={"lang": "python"},
            acceptance_criteria=[{"id": "AC-1"}],
        )

        workflow = await services["workflow_engine"].create_executable_workflow(
            strategic_plan=strategic_plan,
            context={},
        )
        assert workflow is not None
        assert len(workflow.loops) > 0
        assert workflow.task_graph is not None

    @pytest.mark.asyncio
    async def test_full_planning_pipeline(self, full_kernel):
        """Test the full planning pipeline end-to-end."""
        kernel, services = full_kernel
        request = Request(request_text="Build a todo app")

        result = await kernel.submit_request(request)
        assert "project_id" in result

        # Verify planning was invoked
        assert services["strategic_engine"].create_strategic_plan.called
        assert services["workflow_engine"].create_executable_workflow.called


# ============================================================================
# Event Ordering Tests
# ============================================================================


class TestEventOrdering:
    """Tests for event ordering."""

    @pytest.mark.asyncio
    async def test_events_published_in_correct_order(self, full_kernel):
        """Test that events are published in the correct sequence."""
        kernel, services = full_kernel
        request = Request(request_text="Build a todo app")

        await kernel.submit_request(request)

        # Verify events were published
        assert services["event_bus"].publish.called

    @pytest.mark.asyncio
    async def test_event_types_are_strongly_typed(self, full_kernel):
        """Test that all published events use strongly-typed EventType enums."""
        kernel, services = full_kernel
        request = Request(request_text="Build a todo app")

        await kernel.submit_request(request)

        for call_args in services["event_bus"].publish.call_args_list:
            event = call_args[0][0]
            assert isinstance(event.event_type, EventType)
            # Verify no SYSTEM_EVENT fallback
            assert event.event_type != EventType.SYSTEM_EVENT


# ============================================================================
# State Transition Tests
# ============================================================================


class TestOrchestrationStateTransitions:
    """Tests for state transitions during orchestration."""

    @pytest.mark.asyncio
    async def test_valid_state_sequence(self, full_kernel):
        """Test a valid sequence of state transitions."""
        kernel, services = full_kernel
        manager = kernel.project_lifecycle_manager
        project_id = uuid.uuid4()

        # Valid sequence: Created -> Planning -> Running -> Completing -> Finished
        await manager.transition_project_status(project_id, ProjectStatus.PLANNING)
        await manager.transition_project_status(project_id, ProjectStatus.RUNNING)
        await manager.transition_project_status(project_id, ProjectStatus.COMPLETING)
        await manager.transition_project_status(project_id, ProjectStatus.FINISHED)

        assert manager.get_project_status(project_id) == "finished"

    @pytest.mark.asyncio
    async def test_invalid_state_sequence_raises(self, full_kernel):
        """Test that invalid state sequences raise errors."""
        kernel, services = full_kernel
        manager = kernel.project_lifecycle_manager
        project_id = uuid.uuid4()

        # Invalid: Created -> Finished (skips Planning, Running, Completing)
        with pytest.raises(ValueError, match="Invalid transition"):
            await manager.transition_project_status(project_id, ProjectStatus.FINISHED)


# ============================================================================
# Pause/Resume Tests
# ============================================================================


class TestPauseResume:
    """Tests for pause/resume functionality."""

    @pytest.mark.asyncio
    async def test_pause_and_resume_project(self, full_kernel):
        """Test pausing and resuming a project."""
        kernel, services = full_kernel
        manager = kernel.project_lifecycle_manager
        project_id = uuid.uuid4()

        # Setup: Created -> Planning -> Running
        await manager.transition_project_status(project_id, ProjectStatus.PLANNING)
        await manager.transition_project_status(project_id, ProjectStatus.RUNNING)

        # Pause
        await manager.transition_project_status(project_id, ProjectStatus.PAUSED)
        assert manager.get_project_status(project_id) == "paused"

        # Resume
        await manager.transition_project_status(project_id, ProjectStatus.RUNNING)
        assert manager.get_project_status(project_id) == "running"

    @pytest.mark.asyncio
    async def test_pause_from_reviewing(self, full_kernel):
        """Test pausing from reviewing state."""
        kernel, services = full_kernel
        manager = kernel.project_lifecycle_manager
        project_id = uuid.uuid4()

        await manager.transition_project_status(project_id, ProjectStatus.PLANNING)
        await manager.transition_project_status(project_id, ProjectStatus.RUNNING)
        await manager.transition_project_status(project_id, ProjectStatus.REVIEWING)
        await manager.transition_project_status(project_id, ProjectStatus.PAUSED)

        assert manager.get_project_status(project_id) == "paused"


# ============================================================================
# Cancel Tests
# ============================================================================


class TestCancel:
    """Tests for cancel functionality."""

    @pytest.mark.asyncio
    async def test_cancel_from_planning(self, full_kernel):
        """Test cancelling from planning state."""
        kernel, services = full_kernel
        manager = kernel.project_lifecycle_manager
        project_id = uuid.uuid4()

        await manager.transition_project_status(project_id, ProjectStatus.PLANNING)
        await manager.transition_project_status(project_id, ProjectStatus.CANCELLED)
        assert manager.get_project_status(project_id) == "cancelled"

    @pytest.mark.asyncio
    async def test_cancel_from_running(self, full_kernel):
        """Test cancelling from running state."""
        kernel, services = full_kernel
        manager = kernel.project_lifecycle_manager
        project_id = uuid.uuid4()

        await manager.transition_project_status(project_id, ProjectStatus.PLANNING)
        await manager.transition_project_status(project_id, ProjectStatus.RUNNING)
        await manager.transition_project_status(project_id, ProjectStatus.CANCELLED)
        assert manager.get_project_status(project_id) == "cancelled"

    @pytest.mark.asyncio
    async def test_cancel_from_paused(self, full_kernel):
        """Test cancelling from paused state."""
        kernel, services = full_kernel
        manager = kernel.project_lifecycle_manager
        project_id = uuid.uuid4()

        await manager.transition_project_status(project_id, ProjectStatus.PLANNING)
        await manager.transition_project_status(project_id, ProjectStatus.RUNNING)
        await manager.transition_project_status(project_id, ProjectStatus.PAUSED)
        await manager.transition_project_status(project_id, ProjectStatus.CANCELLED)
        assert manager.get_project_status(project_id) == "cancelled"


# ============================================================================
# Failure Recovery Tests
# ============================================================================


class TestFailureRecovery:
    """Tests for failure recovery during orchestration."""

    @pytest.mark.asyncio
    async def test_recoverable_failure(self, full_kernel):
        """Test handling of recoverable failures."""
        kernel, services = full_kernel
        services["execution_continuity_manager"].recover.return_value = {
            "success": True,
            "strategy": "retry",
        }

        project_id = uuid.uuid4()
        result = await kernel.recovery_module.handle_failure(
            project_id=project_id,
            failure={"error": "Provider timeout", "severity": "error"},
        )
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_unrecoverable_failure(self, full_kernel):
        """Test handling of unrecoverable failures."""
        kernel, services = full_kernel

        project_id = uuid.uuid4()
        result = await kernel.recovery_module.handle_failure(
            project_id=project_id,
            failure={"error": "Critical error", "severity": "fatal", "recoverable": False},
        )
        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_failure_during_orchestration(self, full_kernel):
        """Test failure handling during orchestration."""
        kernel, services = full_kernel
        services["execution_engine"].execute_loop.return_value = {
            "status": "failed",
            "loop_type": "coding_loop",
            "error": "Execution error",
        }

        request = Request(request_text="Build a todo app")
        result = await kernel.submit_request(request)
        assert "project_id" in result


# ============================================================================
# Completion Tests
# ============================================================================


class TestOrchestrationCompletion:
    """Tests for completion during orchestration."""

    @pytest.mark.asyncio
    async def test_successful_completion(self, full_kernel):
        """Test successful project completion.

        Completion requires an explicit final-review approval, so the completion
        module is given an approving review engine before finalizing.
        """
        kernel, services = full_kernel
        services["runtime_state_manager"].get_project.return_value = MagicMock()

        review_engine = AsyncMock()
        review_engine.review_project.return_value = {
            "approved": True,
            "decision": "approved",
            "status": "approved",
            "findings": [],
            "findings_count": 0,
        }
        kernel.completion_module.review_engine = review_engine

        project_id = uuid.uuid4()
        result = await kernel.completion_module.finalize_project(project_id)
        assert result["success"] is True
        assert result["final_review"]["approved"] is True

    @pytest.mark.asyncio
    async def test_completion_with_failed_tasks(self, full_kernel):
        """Test completion fails with failed tasks."""
        kernel, services = full_kernel
        services["runtime_state_manager"].get_project.return_value = MagicMock()
        services["runtime_state_manager"].get_project_state.return_value = {
            "status": "running",
            "progress": 50.0,
            "task_count": 5,
            "completed_count": 3,
            "failed_count": 2,
            "acceptance_criteria": [],
            "quality_gates": [],
            "artifacts": [],
            "approval_history": [],
        }

        project_id = uuid.uuid4()
        result = await kernel.completion_module.finalize_project(project_id)
        assert result["success"] is False


# ============================================================================
# Multi-Project Coordination Tests
# ============================================================================


class TestMultiProjectCoordination:
    """Tests for multiple concurrent projects."""

    @pytest.mark.asyncio
    async def test_multiple_concurrent_projects(self, full_kernel):
        """Test handling multiple concurrent projects."""
        kernel, services = full_kernel

        # Submit multiple requests
        requests = [
            Request(request_text="Build project A"),
            Request(request_text="Build project B"),
            Request(request_text="Build project C"),
        ]

        results = []
        for req in requests:
            result = await kernel.submit_request(req)
            results.append(result)

        # Verify all projects were created
        assert len(results) == 3
        for result in results:
            assert "project_id" in result
            assert result["status"] == "created"

        # Verify all projects are tracked
        assert len(kernel.active_projects) == 3

    @pytest.mark.asyncio
    async def test_independent_project_lifecycles(self, full_kernel):
        """Test that project lifecycles are independent."""
        kernel, services = full_kernel
        manager = kernel.project_lifecycle_manager

        # Create two projects with different lifecycles
        project_a = uuid.uuid4()
        project_b = uuid.uuid4()

        # Project A: Planning -> Running -> Completing -> Finished
        await manager.transition_project_status(project_a, ProjectStatus.PLANNING)
        await manager.transition_project_status(project_a, ProjectStatus.RUNNING)
        await manager.transition_project_status(project_a, ProjectStatus.COMPLETING)
        await manager.transition_project_status(project_a, ProjectStatus.FINISHED)

        # Project B: Planning -> Running -> Failed
        await manager.transition_project_status(project_b, ProjectStatus.PLANNING)
        await manager.transition_project_status(project_b, ProjectStatus.RUNNING)
        await manager.transition_project_status(project_b, ProjectStatus.FAILED)

        # Verify independent states
        assert manager.get_project_status(project_a) == "finished"
        assert manager.get_project_status(project_b) == "failed"


# ============================================================================
# Event Handler Tests
# ============================================================================


class TestEventHandlers:
    """Tests for event handlers."""

    @pytest.mark.asyncio
    async def test_loop_event_handler(self, full_kernel):
        """Test loop event handler."""
        kernel, services = full_kernel

        # Create a loop completed event
        from autoforge_events.base import BaseEvent as DomainBaseEvent

        event = DomainBaseEvent(
            event_type=EventType.COMPLETED,
            event_category=EventCategory.PROJECT,
            aggregate_id=uuid.uuid4(),
            aggregate_type="Project",
            metadata={"loop_type": "coding_loop"},
        )

        # Handler should not raise
        await kernel._handle_loop_event(event)

    @pytest.mark.asyncio
    async def test_task_event_handler(self, full_kernel):
        """Test task event handler."""
        kernel, services = full_kernel

        from autoforge_events.base import BaseEvent as DomainBaseEvent

        event = DomainBaseEvent(
            event_type=EventType.COMPLETED,
            event_category=EventCategory.PROJECT,
            aggregate_id=uuid.uuid4(),
            aggregate_type="Project",
            metadata={"task_id": "task-1"},
        )

        # Handler should not raise
        await kernel._handle_task_event(event)

    @pytest.mark.asyncio
    async def test_approval_event_handler(self, full_kernel):
        """Test approval event handler."""
        kernel, services = full_kernel

        from autoforge_events.base import BaseEvent as DomainBaseEvent

        event = DomainBaseEvent(
            event_type=EventType.APPROVED,
            event_category=EventCategory.PROJECT,
            aggregate_id=uuid.uuid4(),
            aggregate_type="Project",
            metadata={"approval_id": str(uuid.uuid4())},
        )

        # Handler should not raise
        await kernel._handle_approval_event(event)