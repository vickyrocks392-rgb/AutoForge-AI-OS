"""
Kernel Interfaces and Contracts

This module defines all interfaces (abstract base classes) that the Kernel
depends on. These are contracts that external implementations must fulfill.

The Kernel depends on contracts, not implementations. This enables:
- Loose coupling
- Independent evolution
- Testability
- Clean abstractions
"""

from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Coroutine, Dict, List, Optional, Protocol, Union

from pydantic import Field

from autoforge_models.base import AutoForgeBaseModel
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


# ============================================================================
# Request and Intent Models
# ============================================================================


class Request(AutoForgeBaseModel):
    """Represents an incoming user request."""

    user_id: uuid.UUID | None = Field(
        default=None,
        description="ID of the user making the request.",
    )
    request_text: str = Field(
        ...,
        min_length=1,
        max_length=10000,
        description="The user's request in natural language.",
    )
    context: dict[str, Any] = Field(
        default_factory=dict,
        description="Optional context (existing codebase, references, constraints).",
    )
    configuration: dict[str, Any] = Field(
        default_factory=dict,
        description="Optional project configuration (language, framework, deployment target).",
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Extensible metadata for the request.",
    )


class IntentAnalysisResult(AutoForgeBaseModel):
    """Result of intent analysis."""

    request_type: str = Field(
        ...,
        description="Type of request (research, implementation, review, deployment, etc.).",
    )
    scope: str = Field(
        ...,
        description="Scope and complexity assessment.",
    )
    constraints: dict[str, Any] = Field(
        default_factory=dict,
        description="Extracted constraints (budget, timeline, quality, compliance).",
    )
    required_loops: list[str] = Field(
        default_factory=list,
        description="Engineering loops required for this request.",
    )
    approval_policy: dict[str, Any] = Field(
        default_factory=dict,
        description="Approval policy for this request.",
    )
    confidence: float = Field(
        default=1.0,
        ge=0.0,
        le=1.0,
        description="Confidence in the analysis (0.0-1.0).",
    )
    reasoning: str = Field(
        default="",
        max_length=4096,
        description="Reasoning behind the analysis.",
    )


class StrategicPlan(AutoForgeBaseModel):
    """Strategic plan produced by the Strategic Engine."""

    plan_id: uuid.UUID = Field(
        default_factory=uuid.uuid4,
        description="Unique identifier for this strategic plan.",
    )
    requirements: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Project requirements.",
    )
    architecture_decisions: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Architecture decisions made.",
    )
    technology_choices: dict[str, Any] = Field(
        default_factory=dict,
        description="Technology selections.",
    )
    acceptance_criteria: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Acceptance criteria for completion.",
    )
    estimated_duration: float = Field(
        default=0.0,
        description="Estimated duration in seconds.",
    )
    estimated_cost: float = Field(
        default=0.0,
        description="Estimated cost in USD.",
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Additional plan metadata.",
    )


class ExecutableWorkflow(AutoForgeBaseModel):
    """Executable workflow produced by the Workflow Engine."""

    workflow_id: uuid.UUID = Field(
        default_factory=uuid.uuid4,
        description="Unique identifier for this workflow.",
    )
    loops: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Engineering loops to execute.",
    )
    task_graph: dict[str, Any] = Field(
        default_factory=dict,
        description="Task dependency graph (DAG).",
    )
    worker_assignments: dict[str, Any] = Field(
        default_factory=dict,
        description="Worker assignments for tasks.",
    )
    model_assignments: dict[str, Any] = Field(
        default_factory=dict,
        description="Model assignments for tasks.",
    )
    approval_policies: dict[str, Any] = Field(
        default_factory=dict,
        description="Approval policies for tasks.",
    )
    retry_policies: dict[str, Any] = Field(
        default_factory=dict,
        description="Retry policies for tasks.",
    )
    estimated_duration: float = Field(
        default=0.0,
        description="Estimated duration in seconds.",
    )
    estimated_cost: float = Field(
        default=0.0,
        description="Estimated cost in USD.",
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Additional workflow metadata.",
    )


# ============================================================================
# Service Interfaces (Shared Platform Services)
# ============================================================================


class RuntimeStateManager(ABC):
    """Interface for the Runtime State Manager service."""

    @abstractmethod
    async def create_project(self, project: Project) -> uuid.UUID:
        """Create a new project record."""
        pass

    @abstractmethod
    async def get_project(self, project_id: uuid.UUID) -> Project | None:
        """Get a project by ID."""
        pass

    @abstractmethod
    async def update_project(self, project: Project) -> None:
        """Update a project record."""
        pass

    @abstractmethod
    async def transition_state(
        self,
        project_id: uuid.UUID,
        new_status: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Transition a project to a new state."""
        pass

    @abstractmethod
    async def get_project_state(self, project_id: uuid.UUID) -> dict[str, Any]:
        """Get the current state of a project."""
        pass

    @abstractmethod
    async def create_task(self, task: Task) -> uuid.UUID:
        """Create a new task."""
        pass

    @abstractmethod
    async def get_task(self, task_id: uuid.UUID) -> Task | None:
        """Get a task by ID."""
        pass

    @abstractmethod
    async def update_task(self, task: Task) -> None:
        """Update a task."""
        pass

    @abstractmethod
    async def create_checkpoint(self, checkpoint: Checkpoint) -> uuid.UUID:
        """Create a checkpoint."""
        pass

    @abstractmethod
    async def get_checkpoint(self, checkpoint_id: uuid.UUID) -> Checkpoint | None:
        """Get a checkpoint by ID."""
        pass

    @abstractmethod
    async def get_latest_checkpoint(self, project_id: uuid.UUID) -> Checkpoint | None:
        """Get the latest checkpoint for a project."""
        pass

    @abstractmethod
    async def health_check(self) -> dict[str, Any]:
        """Verify that the runtime state manager is reachable and healthy.

        Called by the Kernel during initialization to validate its dependency
        on the Runtime State Manager before accepting requests.

        Returns:
            Dictionary with at least a boolean ``healthy`` flag plus
            implementation-specific health details.
        """
        raise NotImplementedError


class EventBus(ABC):
    """Interface for the Event Bus service."""

    @abstractmethod
    async def publish(self, event: DomainBaseEvent) -> None:
        """Publish an event."""
        pass

    @abstractmethod
    async def subscribe(
        self,
        event_types: list[EventType],
        handler: Callable[[DomainBaseEvent], Coroutine[Any, Any, None]],
    ) -> uuid.UUID:
        """Subscribe to events."""
        pass

    @abstractmethod
    async def unsubscribe(self, subscription_id: uuid.UUID) -> None:
        """Unsubscribe from events."""
        pass


class MemoryEngine(ABC):
    """Interface for the Memory Engine service."""

    @abstractmethod
    async def load_context(self, project_id: uuid.UUID) -> dict[str, Any]:
        """Load project context."""
        pass

    @abstractmethod
    async def persist_state(self, project_id: uuid.UUID, state: dict[str, Any]) -> None:
        """Persist execution state."""
        pass

    @abstractmethod
    async def store_memory(self, project_id: uuid.UUID, memory: dict[str, Any]) -> None:
        """Store project memory."""
        pass

    @abstractmethod
    async def retrieve_memory(self, query: str, limit: int = 10) -> list[dict[str, Any]]:
        """Retrieve memories matching a query."""
        pass


class KnowledgeEngine(ABC):
    """Interface for the Knowledge Engine service."""

    @abstractmethod
    async def research(self, topic: str, context: dict[str, Any]) -> dict[str, Any]:
        """Perform research on a topic."""
        pass

    @abstractmethod
    async def query(self, query: str, filters: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        """Query the knowledge base."""
        pass

    @abstractmethod
    async def promote(self, learning: dict[str, Any]) -> None:
        """Promote validated learning to knowledge base."""
        pass


class ModelRouter(ABC):
    """Interface for the Model Router service."""

    @abstractmethod
    async def select_model(
        self,
        task: dict[str, Any],
        exclude_provider: str | None = None,
    ) -> ModelProfile:
        """Select the optimal model for a task."""
        pass

    @abstractmethod
    async def get_model_capabilities(self, model_id: str) -> dict[str, Any]:
        """Get capabilities of a model."""
        pass

    @abstractmethod
    async def get_provider_health(self) -> dict[str, Any]:
        """Get health status of providers."""
        pass


class ExecutionContinuityManager(ABC):
    """Interface for the Execution Continuity Manager service."""

    @abstractmethod
    async def retry(self, task_id: uuid.UUID, context: dict[str, Any]) -> dict[str, Any]:
        """Retry a failed task."""
        pass

    @abstractmethod
    async def failover(self, task_id: uuid.UUID, failed_provider: str) -> dict[str, Any]:
        """Failover to an alternative provider."""
        pass

    @abstractmethod
    async def restore_checkpoint(self, checkpoint_id: uuid.UUID) -> dict[str, Any]:
        """Restore from a checkpoint."""
        pass

    @abstractmethod
    async def recover(self, failure_context: dict[str, Any]) -> dict[str, Any]:
        """Execute recovery procedure."""
        pass


class ConnectorLayer(ABC):
    """Interface for the Connector Layer service."""

    @abstractmethod
    async def connect(self, connector_type: str, config: dict[str, Any]) -> uuid.UUID:
        """Establish a connection."""
        pass

    @abstractmethod
    async def execute(
        self,
        connection_id: uuid.UUID,
        operation: str,
        params: dict[str, Any],
    ) -> dict[str, Any]:
        """Execute an operation on a connection."""
        pass

    @abstractmethod
    async def disconnect(self, connection_id: uuid.UUID) -> None:
        """Close a connection."""
        pass


class ObservabilityService(ABC):
    """Interface for the Observability service."""

    @abstractmethod
    async def emit_metric(self, metric_name: str, value: float, tags: dict[str, str]) -> None:
        """Emit a metric."""
        pass

    @abstractmethod
    async def log_event(self, event: str, context: dict[str, Any]) -> None:
        """Log an event."""
        pass

    @abstractmethod
    async def create_trace(self, trace_name: str, context: dict[str, Any]) -> uuid.UUID:
        """Create a trace."""
        pass

    @abstractmethod
    async def record_span(
        self,
        trace_id: uuid.UUID,
        span_name: str,
        duration_ms: float,
        metadata: dict[str, Any],
    ) -> None:
        """Record a span within a trace."""
        pass


class SecurityService(ABC):
    """Interface for the Security service."""

    @abstractmethod
    async def authenticate(self, credentials: dict[str, Any]) -> uuid.UUID:
        """Authenticate a user or service."""
        pass

    @abstractmethod
    async def authorize(self, subject_id: uuid.UUID, action: str, resource: str) -> bool:
        """Authorize an action on a resource."""
        pass

    @abstractmethod
    async def enforce_policy(self, policy_name: str, context: dict[str, Any]) -> bool:
        """Enforce a security policy."""
        pass

    @abstractmethod
    async def audit(self, event: str, context: dict[str, Any]) -> None:
        """Record an audit event."""
        pass


# ============================================================================
# Platform Engine Interfaces
# ============================================================================


class StrategicEngine(ABC):
    """Interface for the Strategic Engine."""

    @abstractmethod
    async def create_strategic_plan(
        self,
        request: Request,
        intent_analysis: IntentAnalysisResult,
        context: dict[str, Any],
    ) -> StrategicPlan:
        """Create a strategic plan."""
        pass


class WorkflowEngine(ABC):
    """Interface for the Workflow Engine."""

    @abstractmethod
    async def create_executable_workflow(
        self,
        strategic_plan: StrategicPlan,
        context: dict[str, Any],
    ) -> ExecutableWorkflow:
        """Create an executable workflow from a strategic plan."""
        pass

    @abstractmethod
    async def replan(
        self,
        workflow_id: uuid.UUID,
        execution_context: dict[str, Any],
    ) -> ExecutableWorkflow:
        """Replan an existing workflow based on changed conditions."""
        pass


class ExecutionEngine(ABC):
    """Interface for the Execution Engine."""

    @abstractmethod
    async def execute_loop(
        self,
        loop_type: str,
        loop_input: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        """Execute an engineering loop."""
        pass

    @abstractmethod
    async def dispatch_worker(
        self,
        worker_type: str,
        task: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        """Dispatch a worker to execute a task."""
        pass


class ReviewEngine(ABC):
    """Interface for the Review Engine."""

    @abstractmethod
    async def review(
        self,
        artifact: Artifact,
        criteria: dict[str, Any],
    ) -> Review:
        """Review an artifact."""
        pass


# ============================================================================
# Kernel Internal Interfaces
# ============================================================================


class RequestValidator(ABC):
    """Interface for request validation."""

    @abstractmethod
    async def validate(self, request: Request) -> tuple[bool, list[str]]:
        """
        Validate a request.

        Returns:
            Tuple of (is_valid, list_of_errors)
        """
        pass


class RequestNormalizer(ABC):
    """Interface for request normalization."""

    @abstractmethod
    async def normalize(self, request: Request) -> Request:
        """Normalize a request to canonical format."""
        pass


class ProjectInitializer(ABC):
    """Interface for project initialization."""

    @abstractmethod
    async def initialize(self, request: Request) -> Project:
        """Initialize a new project from a request."""
        pass


class IdentifierGenerator(ABC):
    """Interface for identifier generation."""

    @abstractmethod
    def generate_project_id(self) -> uuid.UUID:
        """Generate a new project ID."""
        pass

    @abstractmethod
    def generate_workflow_id(self) -> uuid.UUID:
        """Generate a new workflow ID."""
        pass

    @abstractmethod
    def generate_correlation_id(self) -> uuid.UUID:
        """Generate a new correlation ID."""
        pass


class IntentAnalyzer(ABC):
    """Interface for intent analysis."""

    @abstractmethod
    async def analyze(self, request: Request) -> IntentAnalysisResult:
        """Analyze user intent."""
        pass


class PlanningCoordinator(ABC):
    """Interface for planning coordination."""

    @abstractmethod
    async def coordinate_planning(
        self,
        request: Request,
        intent_analysis: IntentAnalysisResult,
    ) -> tuple[StrategicPlan, ExecutableWorkflow]:
        """Coordinate planning to produce strategic plan and executable workflow."""
        pass


class OrchestrationEngine(ABC):
    """Interface for the orchestration engine."""

    @abstractmethod
    async def orchestrate(
        self,
        project_id: uuid.UUID,
        executable_workflow: ExecutableWorkflow,
    ) -> None:
        """Orchestrate execution of an executable workflow."""
        pass

    @abstractmethod
    async def handle_loop_completion(
        self,
        project_id: uuid.UUID,
        loop_result: dict[str, Any],
    ) -> None:
        """Handle completion of an engineering loop."""
        pass

    @abstractmethod
    async def handle_failure(
        self,
        project_id: uuid.UUID,
        failure: dict[str, Any],
    ) -> None:
        """Handle a failure during execution."""
        pass


class LoopOrchestrator(ABC):
    """Interface for loop orchestration."""

    @abstractmethod
    async def orchestrate_loop(
        self,
        project_id: uuid.UUID,
        loop_type: str,
        loop_context: dict[str, Any],
    ) -> dict[str, Any]:
        """Orchestrate a single engineering loop."""
        pass


class WorkerDispatchCoordinator(ABC):
    """Interface for worker dispatch coordination."""

    @abstractmethod
    async def dispatch_worker(
        self,
        project_id: uuid.UUID,
        task: dict[str, Any],
    ) -> dict[str, Any]:
        """Dispatch a worker for a task."""
        pass


class InfrastructureCoordinator(ABC):
    """Interface for infrastructure coordination."""

    @abstractmethod
    async def coordinate_services(self, lifecycle_point: str, context: dict[str, Any]) -> None:
        """Coordinate infrastructure services at a lifecycle point."""
        pass


class FailureDetector(ABC):
    """Interface for failure detection."""

    @abstractmethod
    async def detect_failure(self, event: DomainBaseEvent) -> dict[str, Any] | None:
        """Detect if an event represents a failure."""
        pass

    @abstractmethod
    async def classify_failure(self, failure: dict[str, Any]) -> dict[str, Any]:
        """Classify a failure by source, severity, and recoverability."""
        pass


class RecoveryCoordinator(ABC):
    """Interface for recovery coordination."""

    @abstractmethod
    async def coordinate_recovery(
        self,
        project_id: uuid.UUID,
        failure: dict[str, Any],
    ) -> dict[str, Any]:
        """Coordinate recovery from a failure."""
        pass


class ApprovalCoordinator(ABC):
    """Interface for approval coordination."""

    @abstractmethod
    async def request_approval(
        self,
        project_id: uuid.UUID,
        approval_context: dict[str, Any],
    ) -> uuid.UUID:
        """Request human approval."""
        pass

    @abstractmethod
    async def process_decision(
        self,
        approval_id: uuid.UUID,
        decision: str,
        feedback: str | None = None,
        modifications: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Process an approval decision."""
        pass


class CompletionModule(ABC):
    """Interface for completion validation and finalization."""

    @abstractmethod
    async def validate_completion(self, project_id: uuid.UUID) -> dict[str, Any]:
        """Validate that a project is complete."""
        pass

    @abstractmethod
    async def finalize_project(self, project_id: uuid.UUID) -> dict[str, Any]:
        """Finalize a completed project."""
        pass


class LifecycleCoordinator(ABC):
    """Interface for lifecycle coordination."""

    @abstractmethod
    async def coordinate_runtime_lifecycle(self, action: str, **kwargs: Any) -> None:
        """Coordinate runtime lifecycle actions."""
        pass

    @abstractmethod
    async def coordinate_project_lifecycle(
        self,
        project_id: uuid.UUID,
        action: str,
        **kwargs: Any,
    ) -> None:
        """Coordinate project lifecycle actions."""
        pass


class RuntimeLifecycleManager(ABC):
    """Interface for runtime lifecycle management."""

    @abstractmethod
    async def initialize(self) -> None:
        """Initialize the runtime."""
        pass

    @abstractmethod
    async def start(self) -> None:
        """Start the runtime."""
        pass

    @abstractmethod
    async def pause(self, reason: str) -> None:
        """Pause the runtime."""
        pass

    @abstractmethod
    async def resume(self) -> None:
        """Resume the runtime."""
        pass

    @abstractmethod
    async def shutdown(self, reason: str) -> None:
        """Shutdown the runtime."""
        pass

    @abstractmethod
    def get_status(self) -> str:
        """Get the current runtime status."""
        pass


class ProjectLifecycleManager(ABC):
    """Interface for project lifecycle management."""

    @abstractmethod
    async def start_project(self, project_id: uuid.UUID) -> None:
        """Start a project."""
        pass

    @abstractmethod
    async def pause_project(self, project_id: uuid.UUID, reason: str) -> None:
        """Pause a project."""
        pass

    @abstractmethod
    async def resume_project(self, project_id: uuid.UUID) -> None:
        """Resume a project."""
        pass

    @abstractmethod
    async def cancel_project(self, project_id: uuid.UUID, reason: str) -> None:
        """Cancel a project."""
        pass

    @abstractmethod
    async def complete_project(self, project_id: uuid.UUID) -> None:
        """Complete a project."""
        pass

    @abstractmethod
    async def fail_project(self, project_id: uuid.UUID, error: str) -> None:
        """Fail a project."""
        pass

    @abstractmethod
    def get_project_status(self, project_id: uuid.UUID) -> str:
        """Get the current project status."""
        pass


# ============================================================================
# Recovery Module Interface
# ============================================================================


class RecoveryModule(ABC):
    """Interface for the recovery module."""

    @abstractmethod
    async def handle_failure(
        self,
        project_id: uuid.UUID,
        failure: dict[str, Any],
    ) -> dict[str, Any]:
        """Handle a failure and coordinate recovery."""
        pass

    @abstractmethod
    async def restore_from_checkpoint(
        self,
        project_id: uuid.UUID,
        checkpoint_id: uuid.UUID,
    ) -> dict[str, Any]:
        """Restore a project from a checkpoint."""
        pass