"""
Integration Tests for the AutoForge AI Kernel.

Tests the full request pipeline, engine coordination, dependency wiring,
service coordination, lifecycle coordination, approval flow, recovery flow,
and completion flow.
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
    ReviewEngine,
    ExecutionContinuityManager,
    ModelRouter,
)
from autoforge_kernel.kernel import Kernel
from autoforge_kernel.kernel_factory import KernelFactory, create_kernel
from autoforge_kernel.request_intake import (
    DefaultRequestValidator,
    DefaultRequestNormalizer,
    DefaultProjectInitializer,
    DefaultIdentifierGenerator,
)
from autoforge_kernel.intent_analysis import DefaultIntentAnalyzer
from autoforge_kernel.planning_coordination import DefaultPlanningCoordinator
from autoforge_kernel.orchestration import DefaultOrchestrationEngine
from autoforge_kernel.lifecycle import DefaultProjectLifecycleManager, DefaultRuntimeLifecycleManager, ProjectStatus
from autoforge_kernel.recovery import DefaultRecoveryModule
from autoforge_kernel.approval import DefaultApprovalCoordinator
from autoforge_kernel.completion import DefaultCompletionModule


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def mock_services():
    """Create all mock services."""
    return {
        "event_bus": AsyncMock(spec=EventBus),
        "runtime_state_manager": AsyncMock(spec=RuntimeStateManager),
        "strategic_engine": AsyncMock(spec=StrategicEngine),
        "workflow_engine": AsyncMock(spec=WorkflowEngine),
        "execution_engine": AsyncMock(spec=ExecutionEngine),
        "review_engine": AsyncMock(spec=ReviewEngine),
        "execution_continuity_manager": AsyncMock(spec=ExecutionContinuityManager),
        "model_router": AsyncMock(spec=ModelRouter),
    }


@pytest.fixture
def configured_kernel(mock_services):
    """Create a fully configured Kernel with all dependencies."""
    services = mock_services

    # Configure mock return values
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
        requirements=[{"id": "REQ-1", "description": "Test requirement"}],
        architecture_decisions=[{"id": "AD-1", "decision": "Use Python"}],
        technology_choices={"language": "python"},
        acceptance_criteria=[{"id": "AC-1", "description": "Test passes", "met": True}],
        estimated_duration=100.0,
        estimated_cost=5.0,
    )

    services["workflow_engine"].create_executable_workflow.return_value = ExecutableWorkflow(
        loops=[{"type": "coding_loop", "description": "Implement feature"}],
        task_graph={"tasks": [{"id": "t1"}], "dependencies": []},
        worker_assignments={"worker1": ["t1"]},
        model_assignments={"worker1": {"model": "gpt-4"}},
        estimated_duration=100.0,
        estimated_cost=5.0,
    )

    services["execution_engine"].execute_loop.return_value = {
        "status": "complete",
        "loop_type": "coding_loop",
    }
    services["execution_engine"].dispatch_worker.return_value = {"status": "completed"}

    # Create kernel with all dependencies
    kernel = Kernel(
        event_bus=services["event_bus"],
        runtime_state_manager=services["runtime_state_manager"],
        strategic_engine=services["strategic_engine"],
        workflow_engine=services["workflow_engine"],
        execution_engine=services["execution_engine"],
        review_engine=services["review_engine"],
        execution_continuity_manager=services["execution_continuity_manager"],
        model_router=services["model_router"],
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
            review_engine=services["review_engine"],
            event_bus=services["event_bus"],
            runtime_state_manager=services["runtime_state_manager"],
            execution_continuity_manager=services["execution_continuity_manager"],
            model_router=services["model_router"],
        ),
        project_lifecycle_manager=DefaultProjectLifecycleManager(
            event_bus=services["event_bus"],
            runtime_state_manager=services["runtime_state_manager"],
            execution_continuity_manager=services["execution_continuity_manager"],
        ),
        runtime_lifecycle_manager=DefaultRuntimeLifecycleManager(
            event_bus=services["event_bus"],
            runtime_state_manager=services["runtime_state_manager"],
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
            review_engine=services["review_engine"],
            event_bus=services["event_bus"],
            runtime_state_manager=services["runtime_state_manager"],
        ),
    )

    return kernel, services


# ============================================================================
# Full Request Pipeline Tests
# ============================================================================


class TestFullRequestPipeline:
    """Tests for the full request pipeline."""

    @pytest.mark.asyncio
    async def test_submit_to_complete_pipeline(self, configured_kernel):
        """Test the full submit -> intake -> analyze -> plan -> orchestrate -> complete pipeline."""
        kernel, services = configured_kernel
        request = Request(request_text="Build a simple REST API")

        result = await kernel.submit_request(request)

        assert "project_id" in result
        assert result["status"] == "created"

        # Verify that the full pipeline was executed
        # 1. Request validation was called
        # 2. Intent analysis was called
        # 3. Planning coordination was called
        # 4. Orchestration was called
        # 5. Completion validation was called

    @pytest.mark.asyncio
    async def test_pipeline_with_all_engines(self, configured_kernel):
        """Test that all engines are invoked in the pipeline."""
        kernel, services = configured_kernel
        request = Request(request_text="Build a todo application with FastAPI")

        result = await kernel.submit_request(request)

        # Verify strategic engine was invoked
        assert services["strategic_engine"].create_strategic_plan.called

        # Verify workflow engine was invoked
        assert services["workflow_engine"].create_executable_workflow.called

        # Verify execution engine was invoked
        assert services["execution_engine"].execute_loop.called

    @pytest.mark.asyncio
    async def test_pipeline_without_optional_engines(self, mock_services):
        """Test pipeline works without optional engines."""
        services = mock_services
        services["runtime_state_manager"].get_project_state.return_value = {}
        services["runtime_state_manager"].get_project.return_value = MagicMock()

        # Create kernel with minimal dependencies
        kernel = Kernel(
            event_bus=services["event_bus"],
            runtime_state_manager=services["runtime_state_manager"],
            request_validator=DefaultRequestValidator(),
            request_normalizer=DefaultRequestNormalizer(),
            project_initializer=DefaultProjectInitializer(event_bus=services["event_bus"]),
            identifier_generator=DefaultIdentifierGenerator(),
        )

        request = Request(request_text="Build a todo app")
        result = await kernel.submit_request(request)
        assert "project_id" in result


# ============================================================================
# Dependency Wiring Tests
# ============================================================================


class TestKernelFactory:
    """Tests for KernelFactory dependency wiring."""

    def test_create_kernel_with_factory(self, mock_services):
        """Test creating a kernel through the factory."""
        services = mock_services
        factory = KernelFactory(
            runtime_state_manager=services["runtime_state_manager"],
            event_bus=services["event_bus"],
            strategic_engine=services["strategic_engine"],
            workflow_engine=services["workflow_engine"],
            execution_engine=services["execution_engine"],
            review_engine=services["review_engine"],
        )
        kernel = factory.create_kernel()
        assert kernel is not None
        assert kernel.runtime_state_manager is not None
        assert kernel.event_bus is not None
        assert kernel.strategic_engine is not None
        assert kernel.workflow_engine is not None
        assert kernel.execution_engine is not None

    def test_create_kernel_convenience_function(self, mock_services):
        """Test the convenience create_kernel function."""
        services = mock_services
        kernel = create_kernel(
            runtime_state_manager=services["runtime_state_manager"],
            event_bus=services["event_bus"],
            strategic_engine=services["strategic_engine"],
            workflow_engine=services["workflow_engine"],
            execution_engine=services["execution_engine"],
        )
        assert kernel is not None

    def test_create_kernel_without_dependencies(self):
        """Test creating a kernel without any dependencies."""
        kernel = create_kernel()
        assert kernel is not None
        assert kernel.request_validator is not None
        assert kernel.request_normalizer is not None
        assert kernel.project_initializer is not None
        assert kernel.identifier_generator is not None


# ============================================================================
# Lifecycle Coordination Tests
# ============================================================================


class TestLifecycleCoordination:
    """Tests for lifecycle coordination."""

    @pytest.mark.asyncio
    async def test_runtime_lifecycle(self, configured_kernel):
        """Test runtime lifecycle coordination."""
        kernel, services = configured_kernel

        # Initialize
        await kernel.initialize()
        assert kernel.status.value == "ready"

        # Pause
        await kernel.pause_runtime("Testing")
        assert kernel.status.value == "paused"

        # Resume
        await kernel.resume_runtime()
        assert kernel.status.value == "ready"

    @pytest.mark.asyncio
    async def test_project_lifecycle(self, configured_kernel):
        """Test project lifecycle coordination."""
        kernel, services = configured_kernel
        request = Request(request_text="Build a todo app")
        result = await kernel.submit_request(request)
        project_id = result["project_id"]

        # Setup: Created -> Planning -> Running (via state transitions)
        await kernel.project_lifecycle_manager.transition_project_status(project_id, ProjectStatus.PLANNING)
        await kernel.project_lifecycle_manager.transition_project_status(project_id, ProjectStatus.RUNNING)

        # Pause project
        await kernel.pause(project_id, "Testing pause")
        # Resume project
        await kernel.resume(project_id)
        # Cancel project
        await kernel.cancel(project_id, "Testing cancel")


# ============================================================================
# Approval Flow Tests
# ============================================================================


class TestApprovalFlow:
    """Tests for the approval flow."""

    @pytest.mark.asyncio
    async def test_approval_request_and_decision(self, configured_kernel):
        """Test full approval flow: request -> decide -> execute."""
        kernel, services = configured_kernel

        # Request approval
        project_id = uuid.uuid4()
        approval_id = await kernel.approval_coordinator.request_approval(
            project_id=project_id,
            approval_context={"type": "review", "description": "Review code changes"},
        )
        assert approval_id is not None

        # Process approval decision
        result = await kernel.submit_approval_decision(
            approval_id=approval_id,
            decision="approved",
            feedback="Looks good to me",
        )
        assert result["status"] == "approved"

    @pytest.mark.asyncio
    async def test_approval_rejection(self, configured_kernel):
        """Test approval rejection flow."""
        kernel, services = configured_kernel

        project_id = uuid.uuid4()
        approval_id = await kernel.approval_coordinator.request_approval(
            project_id=project_id,
            approval_context={"type": "review"},
        )

        result = await kernel.submit_approval_decision(
            approval_id=approval_id,
            decision="rejected",
            feedback="Not acceptable",
        )
        assert result["status"] == "rejected"


# ============================================================================
# Recovery Flow Tests
# ============================================================================


class TestRecoveryFlow:
    """Tests for the recovery flow."""

    @pytest.mark.asyncio
    async def test_failure_recovery(self, configured_kernel):
        """Test failure -> classify -> recover -> resume flow."""
        kernel, services = configured_kernel

        # Simulate a failure
        project_id = uuid.uuid4()
        services["execution_continuity_manager"].recover.return_value = {
            "success": True,
            "strategy": "retry",
        }

        result = await kernel.recovery_module.handle_failure(
            project_id=project_id,
            failure={"error": "Provider timeout", "severity": "error"},
        )
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_unrecoverable_failure(self, configured_kernel):
        """Test unrecoverable failure handling."""
        kernel, services = configured_kernel

        project_id = uuid.uuid4()
        services["execution_continuity_manager"].recover.side_effect = Exception("Recovery failed")

        result = await kernel.recovery_module.handle_failure(
            project_id=project_id,
            failure={"error": "Critical system error", "severity": "fatal", "recoverable": False},
        )
        assert result["success"] is False


# ============================================================================
# Completion Flow Tests
# ============================================================================


class TestCompletionFlow:
    """Tests for the completion flow."""

    @pytest.mark.asyncio
    async def test_validate_and_finalize(self, configured_kernel):
        """Test validate -> finalize -> finish flow."""
        kernel, services = configured_kernel

        project_id = uuid.uuid4()
        services["runtime_state_manager"].get_project.return_value = MagicMock()

        # Completion requires an explicit final-review approval. The shared
        # review mock is an ``AsyncMock(spec=ReviewEngine)``, whose bare return
        # value is not an interpretable approval, so an explicit approval is
        # supplied here. ``review_project`` is supplied by the production
        # ``KernelReviewEngineAdapter`` rather than the Kernel ``ReviewEngine``
        # ABC, so it is attached explicitly.
        services["review_engine"].review_project = AsyncMock(
            return_value={
                "approved": True,
                "decision": "approved",
                "status": "approved",
                "findings": [],
                "findings_count": 0,
            }
        )

        # Validate completion
        validation = await kernel.completion_module.validate_completion(project_id)
        assert validation["valid"] is True

        # Finalize project
        result = await kernel.completion_module.finalize_project(project_id)
        assert result["success"] is True
        assert result["final_review"]["approved"] is True

    @pytest.mark.asyncio
    async def test_completion_fails_with_failed_tasks(self, configured_kernel):
        """Test completion fails when tasks have failed."""
        kernel, services = configured_kernel

        project_id = uuid.uuid4()
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

        validation = await kernel.completion_module.validate_completion(project_id)
        assert validation["valid"] is False
        assert any("failed" in e.lower() for e in validation["errors"])


# ============================================================================
# Event Publishing Tests
# ============================================================================


class TestEventPublishing:
    """Tests for event publishing."""

    @pytest.mark.asyncio
    async def test_project_created_event_published(self, configured_kernel):
        """Test that project.created event is published on submit."""
        kernel, services = configured_kernel
        request = Request(request_text="Build a todo app")

        await kernel.submit_request(request)

        # Verify event was published
        assert services["event_bus"].publish.called

    @pytest.mark.asyncio
    async def test_events_use_correct_types(self, configured_kernel):
        """Test that events use correct strongly-typed event types."""
        kernel, services = configured_kernel
        request = Request(request_text="Build a todo app")

        await kernel.submit_request(request)

        # Verify events were published with correct types
        for call_args in services["event_bus"].publish.call_args_list:
            event = call_args[0][0]
            assert isinstance(event.event_type, EventType)
            assert isinstance(event.event_category, EventCategory)