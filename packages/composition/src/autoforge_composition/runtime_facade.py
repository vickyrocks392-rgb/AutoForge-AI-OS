"""Kernel-facing runtime facade.

Implements the Kernel's ``RuntimeStateManager`` ABC by delegating to the
real :class:`autoforge_runtime.RuntimeStateManager`.

Boundary rules enforced here (see ADR-002):

- The Kernel requests state changes; the Runtime validates and executes
  them. The facade adds NO business logic and never bypasses the Runtime's
  transition engine.
- Identity is preserved: Kernel-generated Project/Task IDs become the
  Runtime state entity IDs, so both subsystems refer to the same aggregates.
- Translation is mechanical (domain model <-> state model) only.
"""

from __future__ import annotations

import uuid
from typing import Any

from autoforge_models.checkpoint import Checkpoint
from autoforge_models.enums import CheckpointType as DomainCheckpointType
from autoforge_models.enums import TaskPriority, TaskStatus
from autoforge_models.project import Project
from autoforge_models.task import Task

from autoforge_kernel.interfaces import RuntimeStateManager

from autoforge_runtime import (
    CheckpointType,
    EntityType,
    RestoreType,
    RuntimeStateManager,
    ProjectState,
    TaskState,
)


def _status_to_str(status: Any) -> str:
    """Normalise a domain status enum/value to a runtime status string."""
    if status is None:
        return "pending"
    return str(getattr(status, "value", status)).lower()


def _state_to_domain_checkpoint(state: Any) -> Checkpoint:
    """Translate a runtime CheckpointState into the domain Checkpoint model.

    Note: the runtime scopes checkpoints to *projects* while the domain
    model references an execution session; the project ID occupies the
    ``execution_session_id`` position and is mirrored in metadata until an
    ExecutionSession aggregate exists on the runtime side (documented in
    ADR-002).
    """
    type_map = {
        "manual": DomainCheckpointType.MANUAL,
        "automatic": DomainCheckpointType.AUTOMATIC,
        "recovery": DomainCheckpointType.RECOVERY,
        "rollback": DomainCheckpointType.ROLLBACK,
        "resume": DomainCheckpointType.RESUME,
    }
    try:
        domain_type = type_map.get(
            str(getattr(state.checkpoint_type, "value", state.checkpoint_type)),
            DomainCheckpointType.MANUAL,
        )
    except AttributeError:  # pragma: no cover - defensive
        domain_type = DomainCheckpointType.MANUAL

    return Checkpoint(
        id=state.checkpoint_id,
        execution_session_id=state.project_id,
        checkpoint_type=domain_type,
        label=state.label or "",
        state_snapshot=dict(state.state_snapshot),
        size_bytes=state.size,
        metadata={**dict(state.metadata), "project_id": str(state.project_id)},
    )


class KernelRuntimeFacade(RuntimeStateManager):
    """Exposes the real runtime to the Kernel through its service ABC."""

    def __init__(self, runtime: RuntimeStateManager) -> None:
        """Wrap the authoritative runtime state manager."""
        self._runtime = runtime

    @property
    def runtime(self) -> RuntimeStateManager:
        """The wrapped authoritative runtime."""
        return self._runtime

    # ── Project lifecycle ────────────────────────────────────────────

    async def create_project(self, project: Project) -> uuid.UUID:
        """Register a new project state under the Kernel-generated ID."""
        state = ProjectState(
            project_id=project.id,
            request={
                "name": project.name,
                "description": project.description,
            },
            configuration=dict(project.metadata),
        )
        self._runtime.register_project(state)
        return project.id

    async def get_project(self, project_id: uuid.UUID) -> Project | None:
        """Fetch the domain view of a project, or None when unknown."""
        try:
            state = self._runtime.get_project_state(project_id)
        except Exception:
            return None
        request = state.request or {}
        return Project(
            id=state.project_id,
            name=str(request.get("name") or f"project-{state.project_id}"),
            description=str(request.get("description") or ""),
            metadata=dict(state.configuration),
        )

    async def update_project(self, project: Project) -> None:
        """Persist domain-level project changes into the runtime state."""
        state = self._runtime.get_project_state(project.id)
        updated = state.model_copy(
            update={
                "request": {
                    "name": project.name,
                    "description": project.description,
                },
                "configuration": dict(project.metadata),
                "version": state.version + 1,
            }
        )
        self._runtime.persistence.write_state(EntityType.PROJECT, project.id, updated)

    async def transition_state(
        self,
        project_id: uuid.UUID,
        new_status: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Request a project state transition — validated BY the runtime."""
        target = new_status.lower()
        curr = self._runtime.get_project_state(project_id)
        if curr and curr.status.value == target:
            return
        self._runtime.transition_project_state(project_id, target, metadata)

    async def get_project_state(self, project_id: uuid.UUID) -> dict[str, Any]:
        """Return the runtime's authoritative view as a plain dict."""
        return self._runtime.get_project_state(project_id).model_dump(mode="python")

    # ── Task lifecycle ───────────────────────────────────────────────

    async def create_task(self, task: Task) -> uuid.UUID:
        """Register a new task state under the Kernel-generated ID."""
        state = TaskState(
            task_id=task.id,
            project_id=task.project_id,
            priority=_status_to_str(task.priority),
            status=_status_to_str(task.status),
            metadata={"title": task.title, "description": task.description},
        )
        self._runtime.register_task(state)
        return task.id

    async def get_task(self, task_id: uuid.UUID) -> Task | None:
        """Fetch the domain view of a task, or None when unknown."""
        try:
            state = self._runtime.get_task_state(task_id)
        except Exception:
            return None
        meta = state.metadata or {}
        return Task(
            id=state.task_id,
            project_id=state.project_id,
            title=str(meta.get("title") or f"task-{state.task_id}"),
            description=str(meta.get("description") or ""),
            status=TaskStatus(str(state.status)),
            priority=TaskPriority(str(state.priority).upper()),
        )

    async def update_task(self, task: Task) -> None:
        """Persist domain-level task changes into the runtime state."""
        state = self._runtime.get_task_state(task.id)
        updated = state.model_copy(
            update={
                "metadata": {
                    **state.metadata,
                    "title": task.title,
                    "description": task.description,
                },
                "version": state.version + 1,
            }
        )
        self._runtime.persistence.write_state(EntityType.TASK, task.id, updated)

    # ── Checkpoints ──────────────────────────────────────────────────

    async def create_checkpoint(self, checkpoint: Checkpoint) -> uuid.UUID:
        """Create a runtime checkpoint scoped to the checkpoint's project."""
        project_raw = checkpoint.metadata.get("project_id")
        if project_raw is None:
            raise ValueError(
                "Kernel checkpoints must carry metadata['project_id'] so the "
                "Runtime can scope the checkpoint to a project aggregate"
            )
        project_id = (
            project_raw
            if isinstance(project_raw, uuid.UUID)
            else uuid.UUID(str(project_raw))
        )
        return self._runtime.create_checkpoint(
            project_id,
            CheckpointType.MANUAL,
            label=checkpoint.label or "",
            metadata=dict(checkpoint.metadata),
        )

    async def get_checkpoint(self, checkpoint_id: uuid.UUID) -> Checkpoint | None:
        """Fetch the domain view of a checkpoint, or None when unknown."""
        try:
            state = self._runtime.get_checkpoint(checkpoint_id)
        except Exception:
            return None
        return _state_to_domain_checkpoint(state)

    async def get_latest_checkpoint(self, project_id: uuid.UUID) -> Checkpoint | None:
        """Fetch the most recent checkpoint of a project."""
        history = self._runtime.checkpoint_manager.get_checkpoint_history(project_id)
        if not history:
            return None
        latest = max(history, key=lambda c: c.created_at)
        return _state_to_domain_checkpoint(latest)

    # ── Health ───────────────────────────────────────────────────────

    async def health_check(self) -> dict[str, Any]:
        """Delegate health verification to the runtime itself."""
        return self._runtime.health_check()

        return self._runtime.get_project_state(project_id).model_dump(mode="python")
