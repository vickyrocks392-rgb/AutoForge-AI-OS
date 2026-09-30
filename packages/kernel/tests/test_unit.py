"""
Unit Tests for the AutoForge AI Kernel.

Covers all Kernel modules with comprehensive unit tests.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from autoforge_events.event_types import EventCategory, EventType
from autoforge_events.base import BaseEvent as DomainBaseEvent

from autoforge_kernel.interfaces import (
    Request,
    IntentAnalysisResult,
    StrategicPlan,
    ExecutableWorkflow,
    EventBus,
    RuntimeStateManager,
)
from autoforge_kernel.kernel import Kernel, KernelRuntimeStatus
from autoforge_kernel.request_intake import (
    DefaultRequestValidator,
    DefaultRequestNormalizer,
    DefaultProjectInitializer,
    DefaultIdentifierGenerator,
    RequestIntakeModule,
)
from autoforge_kernel.intent_analysis import DefaultIntentAnalyzer, IntentAnalysisModule
from autoforge_kernel.planning_coordination import DefaultPlanningCoordinator, PlanningCoordinationModule
from autoforge_kernel.orchestration import (
    DefaultOrchestrationEngine,
    DefaultLoopOrchestrator,
    DefaultWorkerDispatchCoordinator,
    OrchestrationModule,
)
from autoforge_kernel.lifecycle import (
    DefaultRuntimeLifecycleManager,
    DefaultProjectLifecycleManager,
    DefaultLifecycleCoordinator,
    ProjectStatus,
    LifecycleCoordinationModule,
)
from autoforge_kernel.recovery import DefaultFailureDetector, DefaultRecoveryCoordinator, DefaultRecoveryModule
from autoforge_kernel.approval import DefaultApprovalCoordinator, ApprovalCoordinatorModule
from autoforge_kernel.completion import DefaultCompletionModule, CompletionModuleWrapper
from autoforge_kernel.event_utils import publish_event, make_timestamp


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def mock_event_bus():
    """Create a mock event bus."""
    bus = AsyncMock(spec=EventBus)
    bus.publish = AsyncMock()
    bus.subscribe = AsyncMock(return_value=uuid.uuid4())
    bus.unsubscribe = AsyncMock()
    return bus


@pytest.fixture
def mock_runtime_state_manager():
    """Create a mock runtime state manager."""
    mgr = AsyncMock(spec=RuntimeStateManager)
    mgr.create_project = AsyncMock(return_value=uuid.uuid4())
    mgr.get_project = AsyncMock()
    mgr.update_project = AsyncMock()
    mgr.transition_state = AsyncMock()
    mgr.get_project_state = AsyncMock(return_value={
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
    })
    mgr.create_task = AsyncMock(return_value=uuid.uuid4())
    mgr.get_task = AsyncMock()
    mgr.update_task = AsyncMock()
    mgr.create_checkpoint = AsyncMock(return_value=uuid.uuid4())
    mgr.get_checkpoint = AsyncMock()
    mgr.get_latest_checkpoint = AsyncMock()
    return mgr


@pytest.fixture
def sample_request():
    """Create a sample request."""
    return Request(
        request_text="Build a simple REST API for a todo application",
        context={"language": "python", "framework": "fastapi"},
        configuration={"deployment_target": "docker"},
    )


@pytest.fixture
def sample_intent_result():
    """Create a sample intent analysis result."""
    return IntentAnalysisResult(
        request_type="implementation",
        scope="medium",
        constraints={"language": "python", "framework": "fastapi"},
        required_loops=["research_loop", "architecture_loop", "coding_loop", "review_loop", "testing_loop"],
        approval_policy={"require_approval": False, "approval_gates": []},
        confidence=0.85,
        reasoning="Request classified as 'implementation' with 'medium' scope.",
    )


@pytest.fixture
def sample_strategic_plan():
    """Create a sample strategic plan."""
    return StrategicPlan(
        requirements=[{"id": "REQ-1", "description": "REST API for todos"}],
        architecture_decisions=[{"id": "AD-1", "decision": "Use FastAPI framework"}],
        technology_choices={"language": "python", "framework": "fastapi"},
        acceptance_criteria=[{"id": "AC-1", "description": "API returns todo items", "met": True}],
        estimated_duration=3600.0,
        estimated_cost=10.0,
    )


@pytest.fixture
def sample_executable_workflow():
    """Create a sample executable workflow."""
    return ExecutableWorkflow(
        loops=[{"type": "coding_loop", "description": "Implement REST API"}],
        task_graph={
            "tasks": [{"id": "task-1", "description": "Implement API endpoint"}],
            "dependencies": [],
        },
        worker_assignments={"coding_worker": ["task-1"]},
        model_assignments={"coding_worker": {"model_id": "gpt-4"}},
        estimated_duration=3600.0,
        estimated_cost=10.0,
    )


# ============================================================================
# Event Utils Tests
# ============================================================================


class TestEventUtils:
    """Tests for event utility functions."""

    @pytest.mark.asyncio
    async def test_publish_event_with_bus(self, mock_event_bus):
        """Test publishing an event with a valid event bus."""
        await publish_event(
            event_bus=mock_event_bus,
            event_type=EventType.PROJECT_CREATED,
            event_category=EventCategory.PROJECT,
            aggregate_id=uuid.uuid4(),
            aggregate_type="Project",
            metadata={"key": "value"},
        )
        mock_event_bus.publish.assert_called_once()

    @pytest.mark.asyncio
    async def test_publish_event_without_bus(self):
        """Test publishing an event without an event bus."""
        # Should not raise
        await publish_event(
            event_bus=None,
            event_type=EventType.PROJECT_CREATED,
            event_category=EventCategory.PROJECT,
            aggregate_id=uuid.uuid4(),
            aggregate_type="Project",
        )

    def test_make_timestamp(self):
        """Test timestamp generation."""
        ts = make_timestamp()
        assert isinstance(ts, str)
        assert "T" in ts  # ISO-8601 format


# ============================================================================
# Request Intake Tests
# ============================================================================


class TestDefaultRequestValidator:
    """Tests for DefaultRequestValidator."""

    @pytest.mark.asyncio
    async def test_valid_request(self):
        """Test validation of a valid request."""
        validator = DefaultRequestValidator()
        request = Request(request_text="Build a todo app")
        is_valid, errors = await validator.validate(request)
        assert is_valid
        assert len(errors) == 0

    @pytest.mark.asyncio
    async def test_empty_request_text(self):
        """Test validation of empty request text."""
        validator = DefaultRequestValidator()
        # Use model_construct to bypass Pydantic validation
        request = Request.model_construct(request_text="")
        is_valid, errors = await validator.validate(request)
        assert not is_valid
        assert any("empty" in e.lower() for e in errors)

    @pytest.mark.asyncio
    async def test_request_too_long(self):
        """Test validation of overly long request text."""
        validator = DefaultRequestValidator()
        # Use model_construct to bypass Pydantic validation
        request = Request.model_construct(request_text="x" * 10001)
        is_valid, errors = await validator.validate(request)
        assert not is_valid
        assert any("10000" in e for e in errors)


class TestDefaultRequestNormalizer:
    """Tests for DefaultRequestNormalizer."""

    @pytest.mark.asyncio
    async def test_normalize_request(self):
        """Test request normalization."""
        normalizer = DefaultRequestNormalizer()
        request = Request(
            request_text="  Build a todo app  ",
            context={"Language": "Python"},
            configuration={"Framework": "FastAPI"},
        )
        normalized = await normalizer.normalize(request)
        assert normalized.request_text == "Build a todo app"
        assert "language" in normalized.context
        assert "framework" in normalized.configuration


class TestDefaultProjectInitializer:
    """Tests for DefaultProjectInitializer."""

    @pytest.mark.asyncio
    async def test_initialize_project(self, mock_event_bus):
        """Test project initialization."""
        initializer = DefaultProjectInitializer(event_bus=mock_event_bus)
        request = Request(request_text="Build a todo app")
        project = await initializer.initialize(request)
        assert project.id is not None
        assert project.name is not None
        mock_event_bus.publish.assert_called_once()


class TestDefaultIdentifierGenerator:
    """Tests for DefaultIdentifierGenerator."""

    def test_generate_ids(self):
        """Test identifier generation."""
        gen = DefaultIdentifierGenerator()
        assert isinstance(gen.generate_project_id(), uuid.UUID)
        assert isinstance(gen.generate_workflow_id(), uuid.UUID)
        assert isinstance(gen.generate_correlation_id(), uuid.UUID)


class TestRequestIntakeModule:
    """Tests for RequestIntakeModule."""

    @pytest.mark.asyncio
    async def test_process_request(self, mock_event_bus):
        """Test full request processing."""
        module = RequestIntakeModule(event_bus=mock_event_bus)
        request = Request(request_text="Build a todo app")
        result = await module.process_request(request)
        assert "project_id" in result
        assert "correlation_id" in result
        assert "workflow_id" in result
        assert "project" in result

    @pytest.mark.asyncio
    async def test_process_invalid_request(self, mock_event_bus):
        """Test processing an invalid request."""
        module = RequestIntakeModule(event_bus=mock_event_bus)
        # Use model_construct to bypass Pydantic validation
        request = Request.model_construct(request_text="")
        with pytest.raises(ValueError, match="Invalid request"):
            await module.process_request(request)


# ============================================================================
# Intent Analysis Tests
# ============================================================================


class TestDefaultIntentAnalyzer:
    """Tests for DefaultIntentAnalyzer."""

    @pytest.mark.asyncio
    async def test_analyze_implementation_request(self):
        """Test analyzing an implementation request."""
        analyzer = DefaultIntentAnalyzer()
        request = Request(request_text="Build a REST API for a todo application")
        result = await analyzer.analyze(request)
        assert result.request_type == "implementation"
        assert result.scope in ["small", "medium", "large"]  # Scope depends on length
        assert len(result.required_loops) > 0

    @pytest.mark.asyncio
    async def test_analyze_research_request(self):
        """Test analyzing a research request."""
        analyzer = DefaultIntentAnalyzer()
        request = Request(request_text="Research the best practices for microservices")
        result = await analyzer.analyze(request)
        assert result.request_type == "research"

    @pytest.mark.asyncio
    async def test_analyze_with_constraints(self):
        """Test analyzing a request with constraints."""
        analyzer = DefaultIntentAnalyzer()
        request = Request(
            request_text="Build a todo app",
            context={"budget": 100, "timeline": "2 weeks"},
        )
        result = await analyzer.analyze(request)
        assert "budget" in result.constraints
        assert "timeline" in result.constraints


class TestIntentAnalysisModule:
    """Tests for IntentAnalysisModule."""

    @pytest.mark.asyncio
    async def test_analyze_intent(self):
        """Test intent analysis module."""
        module = IntentAnalysisModule()
        request = Request(request_text="Build a todo app")
        result = await module.analyze_intent(request)
        assert result.request_type is not None


# ============================================================================
# Planning Coordination Tests
# ============================================================================


class TestDefaultPlanningCoordinator:
    """Tests for DefaultPlanningCoordinator."""

    @pytest.mark.asyncio
    async def test_coordinate_planning(self, mock_event_bus, sample_request, sample_intent_result):
        """Test planning coordination with mock engines."""
        mock_strategic = AsyncMock()
        mock_strategic.create_strategic_plan = AsyncMock(return_value=StrategicPlan(
            requirements=[{"id": "REQ-1"}],
            architecture_decisions=[{"id": "AD-1"}],
            technology_choices={"lang": "python"},
            acceptance_criteria=[{"id": "AC-1"}],
        ))
        mock_workflow = AsyncMock()
        mock_workflow.create_executable_workflow = AsyncMock(return_value=ExecutableWorkflow(
            loops=[{"type": "coding_loop"}],
            task_graph={"tasks": [{"id": "t1"}], "dependencies": []},
            worker_assignments={"coding_loop": ["t1"]},
            model_assignments={"coding_loop": {"model": "gpt-4"}},
        ))

        coordinator = DefaultPlanningCoordinator(
            strategic_engine=mock_strategic,
            workflow_engine=mock_workflow,
            event_bus=mock_event_bus,
        )
        plan, workflow = await coordinator.coordinate_planning(sample_request, sample_intent_result)
        assert plan is not None
        assert workflow is not None

    @pytest.mark.asyncio
    async def test_validate_planning_outputs_fails(self, mock_event_bus, sample_request, sample_intent_result):
        """Test that planning validation rejects invalid outputs."""
        mock_strategic = AsyncMock()
        mock_strategic.create_strategic_plan = AsyncMock(return_value=StrategicPlan(
            requirements=[],
            architecture_decisions=[],
            technology_choices={},
            acceptance_criteria=[],
        ))
        mock_workflow = AsyncMock()
        mock_workflow.create_executable_workflow = AsyncMock(return_value=ExecutableWorkflow(
            loops=[],
            task_graph={},
            worker_assignments={},
            model_assignments={},
        ))

        coordinator = DefaultPlanningCoordinator(
            strategic_engine=mock_strategic,
            workflow_engine=mock_workflow,
            event_bus=mock_event_bus,
        )
        with pytest.raises(ValueError, match="Planning validation failed"):
            await coordinator.coordinate_planning(sample_request, sample_intent_result)


# ============================================================================
# Lifecycle Tests
# ============================================================================


class TestProjectStatusTransitions:
    """Tests for project status state machine."""

    def setup_method(self):
        self.manager = DefaultProjectLifecycleManager()

    def test_valid_transition_created_to_planning(self):
        """Test Created -> Planning is valid."""
        assert self.manager._is_valid_transition(ProjectStatus.CREATED, ProjectStatus.PLANNING)

    def test_valid_transition_planning_to_running(self):
        """Test Planning -> Running is valid."""
        assert self.manager._is_valid_transition(ProjectStatus.PLANNING, ProjectStatus.RUNNING)

    def test_valid_transition_running_to_reviewing(self):
        """Test Running -> Reviewing is valid."""
        assert self.manager._is_valid_transition(ProjectStatus.RUNNING, ProjectStatus.REVIEWING)

    def test_valid_transition_running_to_completing(self):
        """Test Running -> Completing is valid."""
        assert self.manager._is_valid_transition(ProjectStatus.RUNNING, ProjectStatus.COMPLETING)

    def test_valid_transition_completing_to_finished(self):
        """Test Completing -> Finished is valid."""
        assert self.manager._is_valid_transition(ProjectStatus.COMPLETING, ProjectStatus.FINISHED)

    def test_valid_transition_paused_to_running(self):
        """Test Paused -> Running is valid."""
        assert self.manager._is_valid_transition(ProjectStatus.PAUSED, ProjectStatus.RUNNING)

    def test_invalid_transition_created_to_finished(self):
        """Test Created -> Finished is invalid."""
        assert not self.manager._is_valid_transition(ProjectStatus.CREATED, ProjectStatus.FINISHED)

    def test_invalid_transition_planning_to_completing(self):
        """Test Planning -> Completing is invalid."""
        assert not self.manager._is_valid_transition(ProjectStatus.PLANNING, ProjectStatus.COMPLETING)

    def test_invalid_transition_finished_to_any(self):
        """Test Finished -> any is invalid (terminal state)."""
        assert not self.manager._is_valid_transition(ProjectStatus.FINISHED, ProjectStatus.RUNNING)
        assert not self.manager._is_valid_transition(ProjectStatus.FINISHED, ProjectStatus.PLANNING)

    def test_invalid_transition_failed_to_any(self):
        """Test Failed -> any is invalid (terminal state)."""
        assert not self.manager._is_valid_transition(ProjectStatus.FAILED, ProjectStatus.RUNNING)

    def test_invalid_transition_cancelled_to_any(self):
        """Test Cancelled -> any is invalid (terminal state)."""
        assert not self.manager._is_valid_transition(ProjectStatus.CANCELLED, ProjectStatus.RUNNING)

    def test_none_to_planning(self):
        """Test None -> Planning is valid (initial transition)."""
        assert self.manager._is_valid_transition(None, ProjectStatus.PLANNING)

    def test_none_to_cancelled(self):
        """Test None -> Cancelled is valid."""
        assert self.manager._is_valid_transition(None, ProjectStatus.CANCELLED)

    def test_none_to_running_invalid(self):
        """Test None -> Running is invalid (must go through Planning)."""
        assert not self.manager._is_valid_transition(None, ProjectStatus.RUNNING)

    def test_created_to_running_invalid(self):
        """Test Created -> Running is invalid (must go through Planning)."""
        assert not self.manager._is_valid_transition(ProjectStatus.CREATED, ProjectStatus.RUNNING)


class TestDefaultRuntimeLifecycleManager:
    """Tests for DefaultRuntimeLifecycleManager."""

    @pytest.mark.asyncio
    async def test_initialize(self, mock_event_bus):
        """Test runtime initialization."""
        manager = DefaultRuntimeLifecycleManager(event_bus=mock_event_bus)
        await manager.initialize()
        assert manager.status.value == "starting"
        mock_event_bus.publish.assert_called_once()

    @pytest.mark.asyncio
    async def test_start(self, mock_event_bus):
        """Test runtime start."""
        manager = DefaultRuntimeLifecycleManager(event_bus=mock_event_bus)
        await manager.start()
        assert manager.status.value == "ready"

    def test_get_status(self):
        """Test get_status."""
        manager = DefaultRuntimeLifecycleManager()
        assert manager.get_status() == "created"


# ============================================================================
# Orchestration Tests
# ============================================================================


class TestDefaultOrchestrationEngine:
    """Tests for DefaultOrchestrationEngine."""

    @pytest.mark.asyncio
    async def test_orchestrate(self, mock_event_bus, mock_runtime_state_manager, sample_executable_workflow):
        """Test orchestration execution."""
        mock_execution = AsyncMock()
        mock_execution.execute_loop = AsyncMock(return_value={"status": "complete", "loop_type": "coding_loop"})

        engine = DefaultOrchestrationEngine(
            execution_engine=mock_execution,
            event_bus=mock_event_bus,
            runtime_state_manager=mock_runtime_state_manager,
        )
        project_id = uuid.uuid4()
        await engine.orchestrate(project_id, sample_executable_workflow)
        mock_execution.execute_loop.assert_called_once()


class TestDefaultWorkerDispatchCoordinator:
    """Tests for DefaultWorkerDispatchCoordinator."""

    @pytest.mark.asyncio
    async def test_dispatch_worker(self, mock_event_bus, mock_runtime_state_manager):
        """Test worker dispatch."""
        mock_execution = AsyncMock()
        mock_execution.dispatch_worker = AsyncMock(return_value={"status": "completed"})

        coordinator = DefaultWorkerDispatchCoordinator(
            execution_engine=mock_execution,
            event_bus=mock_event_bus,
            runtime_state_manager=mock_runtime_state_manager,
        )
        project_id = uuid.uuid4()
        result = await coordinator.dispatch_worker(
            project_id=project_id,
            task={"task_id": "task-1", "description": "Implement API", "worker_type": "coding_worker"},
        )
        assert result is not None
        mock_execution.dispatch_worker.assert_called_once()

    @pytest.mark.asyncio
    async def test_dispatch_worker_validates_assignment(self, mock_event_bus):
        """Test that worker dispatch validates assignments."""
        mock_execution = AsyncMock()
        coordinator = DefaultWorkerDispatchCoordinator(
            execution_engine=mock_execution,
            event_bus=mock_event_bus,
        )
        project_id = uuid.uuid4()
        with pytest.raises(ValueError, match="Task missing required field"):
            await coordinator.dispatch_worker(
                project_id=project_id,
                task={"task_id": "task-1"},
            )


# ============================================================================
# Recovery Tests
# ============================================================================


class TestDefaultFailureDetector:
    """Tests for DefaultFailureDetector."""

    @pytest.mark.asyncio
    async def test_detect_failure(self):
        """Test failure detection."""
        detector = DefaultFailureDetector()
        event = DomainBaseEvent(
            event_type=EventType.LOOP_FAILED,
            event_category=EventCategory.LOOP,
            aggregate_id=uuid.uuid4(),
            aggregate_type="Project",
            metadata={"error": "Test error"},
        )
        failure = await detector.detect_failure(event)
        assert failure is not None
        assert failure["error"] == "Test error"

    @pytest.mark.asyncio
    async def test_detect_no_failure(self):
        """Test that non-failure events return None."""
        detector = DefaultFailureDetector()
        event = DomainBaseEvent(
            event_type=EventType.PROJECT_CREATED,
            event_category=EventCategory.PROJECT,
            aggregate_id=uuid.uuid4(),
            aggregate_type="Project",
        )
        failure = await detector.detect_failure(event)
        assert failure is None

    @pytest.mark.asyncio
    async def test_classify_failure(self):
        """Test failure classification."""
        detector = DefaultFailureDetector()
        failure = {"error": "Provider timeout", "severity": "error"}
        classified = await detector.classify_failure(failure)
        assert classified["source"] == "llm_failure"
        assert classified["recoverable"] is True


# ============================================================================
# Approval Tests
# ============================================================================


class TestDefaultApprovalCoordinator:
    """Tests for DefaultApprovalCoordinator."""

    @pytest.mark.asyncio
    async def test_request_approval(self, mock_event_bus, mock_runtime_state_manager):
        """Test requesting approval."""
        coordinator = DefaultApprovalCoordinator(
            event_bus=mock_event_bus,
            runtime_state_manager=mock_runtime_state_manager,
        )
        project_id = uuid.uuid4()
        approval_id = await coordinator.request_approval(
            project_id=project_id,
            approval_context={"type": "review", "description": "Review API design"},
        )
        assert approval_id is not None
        assert approval_id in coordinator.pending_approvals
        mock_event_bus.publish.assert_called_once()

    @pytest.mark.asyncio
    async def test_process_approval_decision(self, mock_event_bus, mock_runtime_state_manager):
        """Test processing an approval decision."""
        coordinator = DefaultApprovalCoordinator(
            event_bus=mock_event_bus,
            runtime_state_manager=mock_runtime_state_manager,
        )
        project_id = uuid.uuid4()
        approval_id = await coordinator.request_approval(
            project_id=project_id,
            approval_context={"type": "review"},
        )
        result = await coordinator.process_decision(
            approval_id=approval_id,
            decision="approved",
            feedback="Looks good",
        )
        assert result["status"] == "approved"
        assert "resume_execution" in result["next_actions"]

    @pytest.mark.asyncio
    async def test_process_rejected_decision(self, mock_event_bus, mock_runtime_state_manager):
        """Test processing a rejected decision."""
        coordinator = DefaultApprovalCoordinator(
            event_bus=mock_event_bus,
            runtime_state_manager=mock_runtime_state_manager,
        )
        project_id = uuid.uuid4()
        approval_id = await coordinator.request_approval(
            project_id=project_id,
            approval_context={"type": "review"},
        )
        result = await coordinator.process_decision(
            approval_id=approval_id,
            decision="rejected",
            feedback="Not acceptable",
        )
        assert result["status"] == "rejected"

    @pytest.mark.asyncio
    async def test_invalid_approval_id(self):
        """Test processing with invalid approval ID."""
        coordinator = DefaultApprovalCoordinator()
        with pytest.raises(ValueError, match="not found"):
            await coordinator.process_decision(
                approval_id=uuid.uuid4(),
                decision="approved",
            )

    @pytest.mark.asyncio
    async def test_check_timeouts(self, mock_event_bus):
        """Test timeout checking."""
        coordinator = DefaultApprovalCoordinator(event_bus=mock_event_bus)
        coordinator.approval_timeout_seconds = 0  # Immediate timeout
        project_id = uuid.uuid4()
        approval_id = await coordinator.request_approval(
            project_id=project_id,
            approval_context={"type": "review", "risk_assessment": "low"},
        )
        results = await coordinator.check_timeouts()
        assert len(results) > 0


# ============================================================================
# Completion Tests
# ============================================================================


class TestDefaultCompletionModule:
    """Tests for DefaultCompletionModule."""

    @pytest.mark.asyncio
    async def test_validate_completion_no_state_manager(self):
        """Test validation without state manager."""
        module = DefaultCompletionModule()
        result = await module.validate_completion(uuid.uuid4())
        assert not result["valid"]
        assert any("not configured" in e for e in result["errors"])

    @pytest.mark.asyncio
    async def test_validate_completion_with_state(self, mock_runtime_state_manager):
        """Test validation with state manager."""
        module = DefaultCompletionModule(runtime_state_manager=mock_runtime_state_manager)
        mock_runtime_state_manager.get_project.return_value = MagicMock()
        result = await module.validate_completion(uuid.uuid4())
        # Should pass with default empty state
        assert result["valid"]

    @pytest.mark.asyncio
    async def test_validate_completion_fails_with_failed_tasks(self, mock_runtime_state_manager):
        """Test validation fails with failed tasks."""
        mock_runtime_state_manager.get_project_state.return_value = {
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
        mock_runtime_state_manager.get_project.return_value = MagicMock()
        module = DefaultCompletionModule(runtime_state_manager=mock_runtime_state_manager)
        result = await module.validate_completion(uuid.uuid4())
        assert not result["valid"]
        assert any("failed" in e.lower() for e in result["errors"])

    @pytest.mark.asyncio
    async def test_finalize_project(self, mock_event_bus, mock_runtime_state_manager):
        """Test project finalization.

        Completion requires an explicit final-review approval, so this test
        supplies an approving review engine. The production composition root
        always wires one (composition_root.py).
        """
        mock_runtime_state_manager.get_project.return_value = MagicMock()
        review_engine = AsyncMock()
        review_engine.review_project.return_value = {
            "approved": True,
            "decision": "approved",
            "status": "approved",
            "findings": [],
            "findings_count": 0,
        }
        module = DefaultCompletionModule(
            review_engine=review_engine,
            event_bus=mock_event_bus,
            runtime_state_manager=mock_runtime_state_manager,
        )
        result = await module.finalize_project(uuid.uuid4())
        assert result["success"]
        assert result["final_review"]["approved"] is True


# ============================================================================
# Kernel Core Tests
# ============================================================================


class TestKernel:
    """Tests for the Kernel class."""

    @pytest.mark.asyncio
    async def test_submit_request(self, mock_event_bus, mock_runtime_state_manager):
        """Test submitting a request to the Kernel."""
        kernel = Kernel(
            event_bus=mock_event_bus,
            runtime_state_manager=mock_runtime_state_manager,
            request_validator=DefaultRequestValidator(),
            request_normalizer=DefaultRequestNormalizer(),
            project_initializer=DefaultProjectInitializer(event_bus=mock_event_bus),
            identifier_generator=DefaultIdentifierGenerator(),
        )
        request = Request(request_text="Build a todo app")
        result = await kernel.submit_request(request)
        assert "project_id" in result
        assert result["status"] == "created"

    @pytest.mark.asyncio
    async def test_submit_request_invalid(self, mock_event_bus):
        """Test submitting an invalid request."""
        kernel = Kernel(
            event_bus=mock_event_bus,
            request_validator=DefaultRequestValidator(),
        )
        # Use model_construct to bypass Pydantic validation
        request = Request.model_construct(request_text="")
        with pytest.raises(ValueError, match="Invalid request"):
            await kernel.submit_request(request)

    @pytest.mark.asyncio
    async def test_get_status(self, mock_runtime_state_manager):
        """Test getting project status."""
        kernel = Kernel(runtime_state_manager=mock_runtime_state_manager)
        mock_runtime_state_manager.get_project.return_value = MagicMock()
        project_id = uuid.uuid4()
        status = await kernel.get_status(project_id)
        assert "status" in status
        assert "progress" in status

    @pytest.mark.asyncio
    async def test_pause_resume_cancel(self, mock_event_bus, mock_runtime_state_manager):
        """Test pause, resume, and cancel operations."""
        manager = DefaultProjectLifecycleManager(
            event_bus=mock_event_bus,
            runtime_state_manager=mock_runtime_state_manager,
        )
        project_id = uuid.uuid4()

        # Setup: Created -> Planning -> Running
        await manager.transition_project_status(project_id, ProjectStatus.PLANNING)
        await manager.transition_project_status(project_id, ProjectStatus.RUNNING)

        # Test pause
        await manager.pause_project(project_id, "Testing pause")
        assert manager.get_project_status(project_id) == "paused"
        # Test resume
        await manager.resume_project(project_id)
        assert manager.get_project_status(project_id) == "running"
        # Test cancel
        await manager.cancel_project(project_id, "Testing cancel")
        assert manager.get_project_status(project_id) == "cancelled"

    @pytest.mark.asyncio
    async def test_initialize_and_start(self, mock_event_bus):
        """Test kernel initialization and start."""
        kernel = Kernel(event_bus=mock_event_bus)
        await kernel.initialize()
        assert kernel.status == KernelRuntimeStatus.READY

    @pytest.mark.asyncio
    async def test_runtime_lifecycle(self, mock_event_bus):
        """Test full runtime lifecycle."""
        kernel = Kernel(event_bus=mock_event_bus)
        await kernel.initialize()
        assert kernel.status == KernelRuntimeStatus.READY

        await kernel.pause_runtime("Testing")
        assert kernel.status == KernelRuntimeStatus.PAUSED

        await kernel.resume_runtime()
        assert kernel.status == KernelRuntimeStatus.READY

    def test_repr(self):
        """Test string representation."""
        kernel = Kernel()
        rep = repr(kernel)
        assert "Kernel(" in rep
        assert "kernel_id=" in rep


# ============================================================================
# State Transition Tests
# ============================================================================


class TestStateTransitions:
    """Comprehensive state transition tests."""

    @pytest.mark.asyncio
    async def test_full_project_lifecycle(self, mock_event_bus, mock_runtime_state_manager):
        """Test the full project lifecycle state transitions."""
        manager = DefaultProjectLifecycleManager(
            event_bus=mock_event_bus,
            runtime_state_manager=mock_runtime_state_manager,
        )
        project_id = uuid.uuid4()

        # Created -> Planning
        await manager.transition_project_status(project_id, ProjectStatus.PLANNING)
        assert manager.get_project_status(project_id) == "planning"

        # Planning -> Running
        await manager.transition_project_status(project_id, ProjectStatus.RUNNING)
        assert manager.get_project_status(project_id) == "running"

        # Running -> Reviewing
        await manager.transition_project_status(project_id, ProjectStatus.REVIEWING)
        assert manager.get_project_status(project_id) == "reviewing"

        # Reviewing -> Running
        await manager.transition_project_status(project_id, ProjectStatus.RUNNING)
        assert manager.get_project_status(project_id) == "running"

        # Running -> Completing
        await manager.transition_project_status(project_id, ProjectStatus.COMPLETING)
        assert manager.get_project_status(project_id) == "completing"

        # Completing -> Finished
        await manager.transition_project_status(project_id, ProjectStatus.FINISHED)
        assert manager.get_project_status(project_id) == "finished"

    @pytest.mark.asyncio
    async def test_invalid_transition_raises(self, mock_event_bus):
        """Test that invalid transitions raise ValueError."""
        manager = DefaultProjectLifecycleManager(event_bus=mock_event_bus)
        project_id = uuid.uuid4()

        # Try invalid transition: Created -> Finished
        with pytest.raises(ValueError, match="Invalid transition"):
            await manager.transition_project_status(project_id, ProjectStatus.FINISHED)

    @pytest.mark.asyncio
    async def test_pause_resume_cycle(self, mock_event_bus, mock_runtime_state_manager):
        """Test pause/resume cycle."""
        manager = DefaultProjectLifecycleManager(
            event_bus=mock_event_bus,
            runtime_state_manager=mock_runtime_state_manager,
        )
        project_id = uuid.uuid4()

        # Created -> Planning -> Running -> Paused -> Running -> Completing -> Finished
        await manager.transition_project_status(project_id, ProjectStatus.PLANNING)
        await manager.transition_project_status(project_id, ProjectStatus.RUNNING)
        await manager.transition_project_status(project_id, ProjectStatus.PAUSED)
        assert manager.get_project_status(project_id) == "paused"
        await manager.transition_project_status(project_id, ProjectStatus.RUNNING)
        assert manager.get_project_status(project_id) == "running"

    @pytest.mark.asyncio
    async def test_failure_paths(self, mock_event_bus, mock_runtime_state_manager):
        """Test failure state transitions."""
        manager = DefaultProjectLifecycleManager(
            event_bus=mock_event_bus,
            runtime_state_manager=mock_runtime_state_manager,
        )
        project_id = uuid.uuid4()

        # Planning -> Failed
        await manager.transition_project_status(project_id, ProjectStatus.PLANNING)
        await manager.transition_project_status(project_id, ProjectStatus.FAILED)
        assert manager.get_project_status(project_id) == "failed"

    @pytest.mark.asyncio
    async def test_cancellation_paths(self, mock_event_bus, mock_runtime_state_manager):
        """Test cancellation state transitions."""
        manager = DefaultProjectLifecycleManager(
            event_bus=mock_event_bus,
            runtime_state_manager=mock_runtime_state_manager,
        )
        project_id = uuid.uuid4()

        # Created -> Cancelled
        await manager.transition_project_status(project_id, ProjectStatus.CANCELLED)
        assert manager.get_project_status(project_id) == "cancelled"