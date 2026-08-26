"""Runtime State Manager — the authoritative state management subsystem.

Implements the Runtime State Manager from Runtime State Manager Specification v1.0.
"""

from __future__ import annotations

import uuid
from typing import Any, Callable

from autoforge_runtime.checkpoint_manager import CheckpointManager
from autoforge_runtime.concurrency import ConcurrencyController
from autoforge_runtime.event_publisher import EventPublisher
from autoforge_runtime.exceptions import (
    DuplicateEntityError,
    EntityNotFoundError,
    InvalidEntityTypeError,
    InvalidTransitionError,
    PersistenceError,
    SnapshotError,
    ValidationError,
    VersionConflictError,
)
from autoforge_runtime.interfaces import (
    EventSubscriptionInterface,
    QueryInterface,
    StateReadInterface,
    StateWriteInterface,
)
from autoforge_runtime.lifecycle import RuntimeLifecycle
from autoforge_runtime.models import (
    CheckpointState,
    CheckpointType,
    EngineeringLoopState,
    EntityType,
    FailureRecord,
    ProgressMetrics,
    ProjectState,
    ProjectStatus,
    RecoveryState,
    RestoreType,
    StateModel,
    StateTransition,
    TaskState,
    TimeRange,
    TransitionResult,
    WorkerState,
    WorkflowState,
)
from autoforge_runtime.persistence import PersistenceLayer
from autoforge_runtime.query_engine import QueryEngine
from autoforge_runtime.recovery_manager import RecoveryManager
from autoforge_runtime.snapshots import (
    SNAPSHOT_STORES,
    RuntimeSnapshot,
    create_snapshot as build_snapshot,
    restore_snapshot as expand_snapshot,
)
from autoforge_runtime.transition_engine import StateTransitionEngine
from autoforge_runtime.validation import (
    ValidationErrorCode,
    validate_project_transition,
    validate_task_transition,
)


class RuntimeStateManager:
    """Authoritative runtime state manager for AutoForge AI.

    Implements the Runtime State Manager from Specification v1.0.
    Owns all runtime state, state transitions, checkpoints, and state history.
    """

    def __init__(
        self,
        *,
        event_callback: Callable[[str, dict[str, Any]], None] | None = None,
    ) -> None:
        """Initialize the runtime state manager.

        Args:
            event_callback: Callback to publish events to the Event Bus.
        """
        self._persistence = PersistenceLayer()
        self._concurrency = ConcurrencyController()
        self._event_publisher = EventPublisher(publish_callback=event_callback)
        self._transition_engine = StateTransitionEngine(
            self._concurrency,
            history_callback=self._persistence.write_history,
            event_callback=self._publish_event,
        )
        self._checkpoint_manager = CheckpointManager(self._persistence)
        self._query_engine = QueryEngine(self._persistence)
        self._recovery_manager = RecoveryManager(self._persistence)
        self._lifecycle = RuntimeLifecycle(event_callback=self._publish_event)

    # ── Lifecycle Operations ─────────────────────────────────────────────

    def initialize(self) -> None:
        """Initialize the runtime state manager."""
        self._lifecycle.initialize()

    def start(self) -> None:
        """Start the runtime state manager."""
        self._lifecycle.start()

    def stop(self, reason: str = "shutdown") -> None:
        """Stop the runtime state manager."""
        self._lifecycle.stop(reason)

    def pause(self, reason: str = "user_requested") -> None:
        """Pause the runtime state manager."""
        self._lifecycle.pause(reason)

    def resume(self) -> None:
        """Resume the runtime state manager."""
        self._lifecycle.resume()

    @property
    def runtime_id(self) -> uuid.UUID:
        """Get the runtime ID."""
        return self._lifecycle.runtime_id

    # ── State Write API (Section 6.1) ────────────────────────────────────

    def create_project(self, project_data: dict[str, Any]) -> uuid.UUID:
        """Create a new project.

        Args:
            project_data: Project initialization data.

        Returns:
            UUID: Unique project identifier.

        Raises:
            ValidationError: If project data is invalid.
            PersistenceError: If state cannot be persisted.
        """
        project = ProjectState(
            request=project_data.get("request", {}),
            configuration=project_data.get("configuration", {}),
            status=ProjectStatus.CREATED,
        )
        self._persistence.write_state(EntityType.PROJECT, project.project_id, project)
        self._publish_event("project.created", {"project_id": str(project.project_id)})
        return project.project_id

    def transition_project_state(
        self,
        project_id: uuid.UUID,
        new_status: str,
        metadata: dict[str, Any] | None = None,
    ) -> TransitionResult:
        """Transition project to new status.

        Args:
            project_id: Project identifier.
            new_status: New project status.
            metadata: Optional metadata.

        Returns:
            TransitionResult: Transition result.

        Raises:
            InvalidTransitionError: If transition is not allowed.
            EntityNotFoundError: If project does not exist.
            VersionConflictError: If state version conflict.
        """
        project = self._get_project(project_id)
        result = self._transition_engine.execute_transition(
            EntityType.PROJECT,
            project_id,
            project.status.value,
            new_status,
            metadata=metadata,
            expected_version=project.version,
        )
        updated = project.model_copy(
            update={
                "status": ProjectStatus(new_status),
                "version": project.version + 1,
            }
        )
        self._persistence.write_state(EntityType.PROJECT, project_id, updated)
        return result

    def update_task_state(
        self,
        task_id: uuid.UUID,
        new_status: str,
        metadata: dict[str, Any] | None = None,
    ) -> TransitionResult:
        """Update task state.

        Args:
            task_id: Task identifier.
            new_status: New task status.
            metadata: Optional metadata.

        Returns:
            TransitionResult: Transition result.

        Raises:
            InvalidTransitionError: If transition is not allowed.
            EntityNotFoundError: If task does not exist.
            VersionConflictError: If state version conflict.
        """
        task = self._get_task(task_id)
        result = self._transition_engine.execute_transition(
            EntityType.TASK,
            task_id,
            task.status,
            new_status,
            metadata=metadata,
            expected_version=task.version,
        )
        updated = task.model_copy(
            update={
                "status": new_status,
                "version": task.version + 1,
            }
        )
        self._persistence.write_state(EntityType.TASK, task_id, updated)
        return result

    def create_checkpoint(
        self,
        project_id: uuid.UUID,
        checkpoint_type: CheckpointType,
        label: str | None = None,
        description: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> uuid.UUID:
        """Create a checkpoint.

        Args:
            project_id: Project identifier.
            checkpoint_type: Checkpoint type.
            label: Optional human-readable label.
            description: Optional description.
            metadata: Optional metadata.

        Returns:
            UUID: Unique checkpoint identifier.

        Raises:
            EntityNotFoundError: If project does not exist.
            PersistenceError: If checkpoint cannot be created.
        """
        checkpoint = self._checkpoint_manager.create_checkpoint(
            project_id,
            checkpoint_type,
            label=label,
            description=description,
            metadata=metadata,
        )
        self._publish_event(
            "checkpoint.created",
            {
                "checkpoint_id": str(checkpoint.checkpoint_id),
                "project_id": str(project_id),
                "checkpoint_type": checkpoint_type.value,
            },
        )
        return checkpoint.checkpoint_id

    def restore_checkpoint(
        self,
        checkpoint_id: uuid.UUID,
        restore_type: RestoreType = RestoreType.FULL,
    ) -> TransitionResult:
        """Restore state from checkpoint.

        Args:
            checkpoint_id: Checkpoint identifier.
            restore_type: Type of restoration (full/partial).

        Returns:
            TransitionResult: Restoration result.

        Raises:
            EntityNotFoundError: If checkpoint does not exist.
            InvalidStateError: If checkpoint cannot be restored.
            PersistenceError: If state cannot be restored.
        """
        result = self._checkpoint_manager.restore_checkpoint(checkpoint_id, restore_type)
        self._publish_event(
            "checkpoint.restored",
            {
                "checkpoint_id": str(checkpoint_id),
                "restored_by": "system",
            },
        )
        return result

    # ── Snapshot Operations ──────────────────────────────────────────────

    def create_snapshot(self) -> RuntimeSnapshot:
        """Capture an immutable snapshot of the entire runtime state.

        Returns:
            RuntimeSnapshot: Immutable point-in-time capture of all
            registered state entities.

        Raises:
            SnapshotError: If the snapshot cannot be created.
        """
        try:
            stores = {
                field: self._persistence.snapshot_store(entity_type)
                for field, entity_type, _ in SNAPSHOT_STORES
            }
            snapshot = build_snapshot(stores)
        except Exception as exc:
            raise SnapshotError(
                f"Failed to create runtime snapshot: {exc}",
                details={"error": str(exc)},
            ) from exc
        self._publish_event(
            "snapshot.created",
            {
                "snapshot_id": str(snapshot.snapshot_id),
                "entity_count": len(snapshot),
            },
        )
        return snapshot

    def restore_snapshot(self, snapshot: RuntimeSnapshot) -> int:
        """Restore runtime state from an immutable snapshot.

        Writes every entity contained in the snapshot back into the
        persistence layer, replacing existing state for those IDs.

        Args:
            snapshot: The snapshot to restore from.

        Returns:
            int: Number of entities restored.
        """
        restored = expand_snapshot(snapshot)
        count = 0
        for field, entity_type, _ in SNAPSHOT_STORES:
            for entity_id, entity in restored[field].items():
                self._persistence.write_state(entity_type, entity_id, entity)
                count += 1
        self._publish_event(
            "snapshot.restored",
            {
                "snapshot_id": str(snapshot.snapshot_id),
                "entity_count": count,
            },
        )
        return count

    def health_check(self) -> dict[str, Any]:
        """Report runtime health for dependency verification.

        Used by dependents (e.g. the Kernel during initialization) to verify
        that this runtime state manager instance is alive and operational.

        Returns:
            dict[str, Any]: Health information including runtime ID, lifecycle
            status and persistence availability.
        """
        persistence_ok = True
        try:
            self._persistence.read_all(EntityType.PROJECT)
        except Exception:
            persistence_ok = False
        return {
            "healthy": persistence_ok,
            "runtime_id": str(self._lifecycle.runtime_id),
            "status": self._lifecycle.status.value,
            "persistence_available": persistence_ok,
        }

    # ── State Read API (Section 6.2) ─────────────────────────────────────

    def get_project_state(self, project_id: uuid.UUID) -> ProjectState:
        """Get project state.

        Args:
            project_id: Project identifier.

        Returns:
            ProjectState: Current project state.

        Raises:
            EntityNotFoundError: If project does not exist.
        """
        return self._query_engine.get_project_state(project_id)

    def get_task_state(self, task_id: uuid.UUID) -> TaskState:
        """Get task state.

        Args:
            task_id: Task identifier.

        Returns:
            TaskState: Current task state.

        Raises:
            EntityNotFoundError: If task does not exist.
        """
        return self._query_engine.get_task_state(task_id)

    def get_worker_state(self, worker_id: uuid.UUID) -> WorkerState:
        """Get worker state.

        Args:
            worker_id: Worker identifier.

        Returns:
            WorkerState: Current worker state.

        Raises:
            EntityNotFoundError: If worker does not exist.
        """
        return self._query_engine.get_worker_state(worker_id)

    def get_checkpoint(self, checkpoint_id: uuid.UUID) -> CheckpointState:
        """Get checkpoint state.

        Args:
            checkpoint_id: Checkpoint identifier.

        Returns:
            CheckpointState: Checkpoint state.

        Raises:
            EntityNotFoundError: If checkpoint does not exist.
        """
        return self._query_engine.get_checkpoint(checkpoint_id)

    # ── Query API (Section 6.3) ──────────────────────────────────────────

    def get_projects_by_status(self, status: str) -> list[ProjectState]:
        """Get projects by status."""
        return self._query_engine.get_projects_by_status(status)

    def get_tasks_by_project(self, project_id: uuid.UUID) -> list[TaskState]:
        """Get tasks by project."""
        return self._query_engine.get_tasks_by_project(project_id)

    def get_tasks_by_status(self, status: str) -> list[TaskState]:
        """Get tasks by status."""
        return self._query_engine.get_tasks_by_status(status)

    def get_running_workflows(self) -> list[WorkflowState]:
        """Get all running workflows."""
        return self._query_engine.get_running_workflows()

    def get_worker_status(self) -> list[WorkerState]:
        """Get all worker states."""
        return self._query_engine.get_worker_status()

    def get_execution_progress(self, project_id: uuid.UUID) -> ProgressMetrics:
        """Get execution progress."""
        return self._query_engine.get_execution_progress(project_id)

    def get_runtime_history(
        self,
        entity_type: EntityType,
        entity_id: uuid.UUID,
        time_range: TimeRange | None = None,
    ) -> list[StateTransition]:
        """Get runtime history."""
        return self._query_engine.get_runtime_history(entity_type, entity_id, time_range)

    def get_checkpoint_history(self, project_id: uuid.UUID) -> list[CheckpointState]:
        """Get checkpoint history."""
        return self._query_engine.get_checkpoint_history(project_id)

    def get_failure_history(self, project_id: uuid.UUID | None = None) -> list[FailureRecord]:
        """Get failure history."""
        return self._query_engine.get_failure_history(project_id)

    def get_loop_history(self, project_id: uuid.UUID) -> list[EngineeringLoopState]:
        """Get engineering loop history."""
        return self._query_engine.get_loop_history(project_id)

    # ── Event Subscription API (Section 6.4) ─────────────────────────────

    def subscribe_to_state_changes(
        self,
        entity_type: EntityType,
        callback: Callable[[dict[str, Any]], None],
    ) -> uuid.UUID:
        """Subscribe to state changes.

        Args:
            entity_type: Entity type to subscribe to.
            callback: Callback function.

        Returns:
            UUID: Subscription identifier.

        Raises:
            InvalidEntityTypeError: If entity type is invalid.
        """
        if entity_type not in EntityType:
            raise InvalidEntityTypeError(
                f"Invalid entity type: {entity_type}",
                details={"entity_type": str(entity_type)},
            )
        event_type = f"{entity_type.value}."
        return self._event_publisher.router.subscribe(event_type, callback, prefix_match=True)

    def unsubscribe(self, subscription_id: uuid.UUID) -> bool:
        """Unsubscribe from state changes.

        Args:
            subscription_id: Subscription identifier.

        Returns:
            bool: True if unsubscribed successfully.

        Raises:
            EntityNotFoundError: If subscription does not exist.
        """
        return self._event_publisher.router.unsubscribe(subscription_id)

    # ── Entity Registration Operations ───────────────────────────────────

    def register_project(self, project: ProjectState) -> None:
        """Register a project state."""
        if self._entity_exists(EntityType.PROJECT, project.project_id):
            raise DuplicateEntityError(
                f"Project with ID {project.project_id} already exists",
                details={"entity_id": str(project.project_id), "entity_type": "project"},
            )
        self._persistence.write_state(EntityType.PROJECT, project.project_id, project)

    def register_workflow(self, workflow: WorkflowState) -> None:
        """Register a workflow state."""
        if self._entity_exists(EntityType.WORKFLOW, workflow.workflow_id):
            raise DuplicateEntityError(
                f"Workflow with ID {workflow.workflow_id} already exists",
                details={"entity_id": str(workflow.workflow_id), "entity_type": "workflow"},
            )
        self._persistence.write_state(EntityType.WORKFLOW, workflow.workflow_id, workflow)

    def register_loop(self, loop: EngineeringLoopState) -> None:
        """Register an engineering loop state."""
        if self._entity_exists(EntityType.LOOP, loop.loop_id):
            raise DuplicateEntityError(
                f"Loop with ID {loop.loop_id} already exists",
                details={"entity_id": str(loop.loop_id), "entity_type": "loop"},
            )
        self._persistence.write_state(EntityType.LOOP, loop.loop_id, loop)

    def register_task(self, task: TaskState) -> None:
        """Register a task state."""
        if self._entity_exists(EntityType.TASK, task.task_id):
            raise DuplicateEntityError(
                f"Task with ID {task.task_id} already exists",
                details={"entity_id": str(task.task_id), "entity_type": "task"},
            )
        self._persistence.write_state(EntityType.TASK, task.task_id, task)

    def register_worker(self, worker: WorkerState) -> None:
        """Register a worker state."""
        if self._entity_exists(EntityType.WORKER, worker.worker_id):
            raise DuplicateEntityError(
                f"Worker with ID {worker.worker_id} already exists",
                details={"entity_id": str(worker.worker_id), "entity_type": "worker"},
            )
        self._persistence.write_state(EntityType.WORKER, worker.worker_id, worker)

    def register_recovery(self, recovery: RecoveryState) -> None:
        """Register a recovery state."""
        if self._entity_exists(EntityType.RECOVERY, recovery.recovery_id):
            raise DuplicateEntityError(
                f"Recovery with ID {recovery.recovery_id} already exists",
                details={"entity_id": str(recovery.recovery_id), "entity_type": "recovery"},
            )
        self._persistence.write_state(EntityType.RECOVERY, recovery.recovery_id, recovery)

    # ── Internal Helpers ─────────────────────────────────────────────────

    def _get_project(self, project_id: uuid.UUID) -> ProjectState:
        """Get a project state by ID."""
        state = self._persistence.read_state(EntityType.PROJECT, project_id)
        if not isinstance(state, ProjectState):
            raise EntityNotFoundError(
                f"Project with ID {project_id} not found",
                details={"entity_id": str(project_id), "entity_type": "project"},
            )
        return state

    def _get_task(self, task_id: uuid.UUID) -> TaskState:
        """Get a task state by ID."""
        state = self._persistence.read_state(EntityType.TASK, task_id)
        if not isinstance(state, TaskState):
            raise EntityNotFoundError(
                f"Task with ID {task_id} not found",
                details={"entity_id": str(task_id), "entity_type": "task"},
            )
        return state

    def _entity_exists(self, entity_type: EntityType, entity_id: uuid.UUID) -> bool:
        """Check if an entity exists."""
        try:
            self._persistence.read_state(entity_type, entity_id)
            return True
        except EntityNotFoundError:
            return False

    def _publish_event(self, event_name: str, payload: dict[str, Any]) -> None:
        """Publish an event."""
        self._event_publisher._publish(
            {
                "event_id": str(uuid.uuid4()),
                "event_type": event_name,
                **payload,
            }
        )

    # ── Component Accessors ──────────────────────────────────────────────

    @property
    def persistence(self) -> PersistenceLayer:
        """Get the persistence layer."""
        return self._persistence

    @property
    def transition_engine(self) -> StateTransitionEngine:
        """Get the state transition engine."""
        return self._transition_engine

    @property
    def checkpoint_manager(self) -> CheckpointManager:
        """Get the checkpoint manager."""
        return self._checkpoint_manager

    @property
    def query_engine(self) -> QueryEngine:
        """Get the query engine."""
        return self._query_engine

    @property
    def recovery_manager(self) -> RecoveryManager:
        """Get the recovery manager."""
        return self._recovery_manager

    @property
    def lifecycle(self) -> RuntimeLifecycle:
        """Get the runtime lifecycle."""
        return self._lifecycle

    @property
    def event_publisher(self) -> EventPublisher:
        """Get the event publisher."""
        return self._event_publisher