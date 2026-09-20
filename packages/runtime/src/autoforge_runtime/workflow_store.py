"""Durable Workflow Store — durable workflow identity, state and reconstruction (Phase 18-J.3).

The store is a *projection* over the single runtime persistence foundation:
it owns no database, no cache, and no history log of its own. It delegates
every read and write to the injected :class:`~autoforge_runtime.persistence.PersistenceLayer`.

                    Runtime State
                    SINGLE SOURCE
                         |
          +--------------+--------------+
          |              |              |
          v              v              v
      Workflow        Execution       Recovery
      projection      projection      projection
          |              |              |
          +--------------+--------------+
                         |
                         v
                PersistenceLayer
                         |
                         v
                   SQLiteStorage

What J.3 guarantees:
--------------------
- Durable workflow identity and definition linkage
- Lifecycle transitions with optimistic concurrency (state_version / expected_version)
- Interrupted workflow detection for abandoned processes
- Explicit controlled claim for workflow resume
- Concurrent resume protection
- No second database or external workflow engine
"""

from __future__ import annotations

import copy
import os
import socket
import uuid
from datetime import datetime, timezone
from typing import Any

from autoforge_runtime.exceptions import (
    EntityNotFoundError,
    InvalidStateError,
    InvalidTransitionError,
    PersistenceError,
    ValidationError,
    VersionConflictError,
)
from autoforge_runtime.models import (
    EntityType,
    StateTransition,
    WorkflowState,
    WorkflowStatus,
)
from autoforge_runtime.persistence import PersistenceLayer
from autoforge_runtime.validation import (
    is_workflow_recoverable,
    is_workflow_terminal,
    validate_workflow_transition,
)

__all__ = [
    "DurableWorkflowStore",
    "default_workflow_owner_id",
]

_CREATED_FROM_STATE = "none"


def default_workflow_owner_id() -> str:
    """Return the identity of the current process (``host:pid``)."""
    return f"{socket.gethostname()}:{os.getpid()}"


def _now() -> datetime:
    """Return current timezone-aware UTC datetime."""
    return datetime.now(timezone.utc)


def _op_transition_id(operation_id: uuid.UUID | None, suffix: str) -> uuid.UUID:
    """Derive deterministic history-row ID from operation ID."""
    if operation_id is None:
        return uuid.uuid4()
    return uuid.uuid5(operation_id, suffix)


class DurableWorkflowStore:
    """Durable workflow state records, abandoned detection, and resume claim.

    Args:
        persistence: The runtime persistence layer (required).
        owner_id: Identity of the owning process; defaults to ``host:pid``.
    """

    def __init__(
        self,
        persistence: PersistenceLayer,
        *,
        owner_id: str | None = None,
    ) -> None:
        if persistence is None:
            raise PersistenceError(
                "DurableWorkflowStore requires the runtime persistence layer",
                details={},
            )
        self._persistence = persistence
        self._owner_id = owner_id or default_workflow_owner_id()

    @property
    def persistence(self) -> PersistenceLayer:
        """The runtime persistence layer backing this store."""
        return self._persistence

    @property
    def owner_id(self) -> str:
        """Identity of the owning process (``host:pid`` by default)."""
        return self._owner_id

    def __repr__(self) -> str:
        return f"DurableWorkflowStore(owner_id={self._owner_id!r}, db_path={self._persistence.db_path!r})"

    # ── Internal helpers ─────────────────────────────────────────────────

    def _bump(self, state: WorkflowState, **updates: Any) -> WorkflowState:
        """Return a copy of state with updates applied and state_version+1."""
        payload = dict(updates)
        payload["state_version"] = state.state_version + 1
        payload["updated_at"] = _now()
        return state.model_copy(update=payload)

    @staticmethod
    def _require(result: Any, *, what: str) -> None:
        """Raise InvalidTransitionError when a validation failed."""
        if not result.valid:
            raise InvalidTransitionError(
                result.error_message or f"Invalid transition: {what}",
                details=result.details,
            )

    @staticmethod
    def _as_uuid(value: uuid.UUID | str, *, what: str) -> uuid.UUID:
        """Coerce value to UUID."""
        if isinstance(value, uuid.UUID):
            return value
        try:
            return uuid.UUID(str(value))
        except (ValueError, AttributeError) as exc:
            raise ValidationError(
                f"Invalid {what}: {value!r} is not a valid UUID",
                details={what: str(value)},
            ) from exc

    def _store_state(
        self,
        workflow_id: uuid.UUID,
        state: WorkflowState,
        *,
        expected_version: int | None = None,
    ) -> int:
        """Persist state to the runtime store and cache."""
        return self._persistence.write_state(
            EntityType.WORKFLOW,
            workflow_id,
            state,
            expected_version=expected_version,
        )

    def _record_transition(
        self,
        workflow_id: uuid.UUID,
        from_state: str,
        to_state: str,
        *,
        actor: str,
        metadata: dict[str, Any],
        transition_id: uuid.UUID | None = None,
    ) -> None:
        """Append an idempotent history transition."""
        tid = transition_id or uuid.uuid4()
        transition = StateTransition(
            transition_id=tid,
            entity_type=EntityType.WORKFLOW,
            entity_id=workflow_id,
            from_state=from_state,
            to_state=to_state,
            actor=actor,
            timestamp=_now(),
            metadata=metadata,
        )
        self._persistence.write_history(transition)

    # ── Read API ─────────────────────────────────────────────────────────

    def get_workflow(self, workflow_id: uuid.UUID | str) -> WorkflowState:
        """Return the durable workflow state, or raise EntityNotFoundError."""
        wid = self._as_uuid(workflow_id, what="workflow_id")
        state = self._persistence.read_state(EntityType.WORKFLOW, wid)
        if state is None:
            raise EntityNotFoundError(
                f"Workflow {wid} not found",
                details={"workflow_id": str(wid)},
            )
        return state  # type: ignore[return-value]

    def try_get_workflow(self, workflow_id: uuid.UUID | str) -> WorkflowState | None:
        """Return the durable workflow state, or None if not found."""
        try:
            return self.get_workflow(workflow_id)
        except (EntityNotFoundError, ValidationError):
            return None

    def list_workflows(self) -> list[WorkflowState]:
        """Return every durable workflow, ordered by creation time."""
        workflows = [
            s
            for s in self._persistence.read_all(EntityType.WORKFLOW)
            if isinstance(s, WorkflowState)
        ]
        return sorted(workflows, key=lambda w: (w.created_at, str(w.workflow_id)))

    def list_active_workflows(self) -> list[WorkflowState]:
        """Return workflows that are not in terminal status."""
        return [
            w for w in self.list_workflows() if not is_workflow_terminal(w.status)
        ]

    def list_interrupted_workflows(self) -> list[WorkflowState]:
        """Return workflows currently marked INTERRUPTED."""
        return [
            w for w in self.list_workflows() if w.status == WorkflowStatus.INTERRUPTED
        ]

    def find_abandoned_workflows(self) -> list[WorkflowState]:
        """Return active workflows owned by a different process.

        An active workflow whose owner_id is set and differs from this process
        is evidence that the owning process has disappeared or died.
        """
        return [
            w
            for w in self.list_active_workflows()
            if w.owner_id is not None and w.owner_id != self._owner_id
        ]

    def get_transition_history(self, workflow_id: uuid.UUID | str) -> list[StateTransition]:
        """Return transition history records for a workflow."""
        wid = self._as_uuid(workflow_id, what="workflow_id")
        return self._persistence.read_history(EntityType.WORKFLOW, wid)

    # ── Lifecycle API ────────────────────────────────────────────────────

    def register_workflow(
        self,
        workflow_id: uuid.UUID | str,
        *,
        project_id: uuid.UUID | str | None = None,
        definition: dict[str, Any] | None = None,
        status: WorkflowStatus = WorkflowStatus.RUNNING,
        owner_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        transition_id: uuid.UUID | None = None,
    ) -> WorkflowState:
        """Register or initialise a durable workflow record.

        Args:
            workflow_id: Canonical workflow ID.
            project_id: Associated project ID (defaults to workflow_id).
            definition: Serialised WorkflowDefinition dict.
            status: Initial status (default RUNNING).
            owner_id: Owning process ID (defaults to this store's owner).
            metadata: Additional metadata.
            transition_id: Idempotency token for history.

        Returns:
            The created (or existing) WorkflowState.
        """
        wid = self._as_uuid(workflow_id, what="workflow_id")
        pid = self._as_uuid(project_id, what="project_id") if project_id else wid
        owner = owner_id or self._owner_id

        if hasattr(definition, "model_dump"):
            defn_dict = definition.model_dump(mode="python")
        elif isinstance(definition, dict):
            defn_dict = copy.deepcopy(definition)
        else:
            defn_dict = {}

        with self._persistence.transaction():
            existing = self.try_get_workflow(wid)
            if existing is not None:
                # Idempotent: already registered
                return existing

            wf = WorkflowState(
                workflow_id=wid,
                project_id=pid,
                status=status,
                state_version=1,
                owner_id=owner,
                recoverable=(status in {WorkflowStatus.CREATED, WorkflowStatus.RUNNING, WorkflowStatus.INTERRUPTED}),
                definition=defn_dict,
                task_graph=defn_dict,
                task_count=len(defn_dict.get("tasks", [])),
                started_at=_now() if status == WorkflowStatus.RUNNING else None,
                metadata=copy.deepcopy(metadata or {}),
            )
            self._store_state(wid, wf)
            self._record_transition(
                wid,
                _CREATED_FROM_STATE,
                status.value,
                actor=owner,
                metadata={
                    "operation": "workflow.registered",
                    "owner_id": owner,
                },
                transition_id=_op_transition_id(transition_id, "workflow-registered"),
            )
            return wf

    def mark_interrupted(
        self,
        workflow_id: uuid.UUID | str,
        *,
        reason: str | None = None,
        expected_version: int | None = None,
        transition_id: uuid.UUID | None = None,
    ) -> WorkflowState:
        """Classify a workflow as INTERRUPTED (recoverable).

        Called by supervisor reconciliation when a workflow was left in RUNNING
        status by a deceased process.
        """
        wid = self._as_uuid(workflow_id, what="workflow_id")
        with self._persistence.transaction():
            workflow = self.get_workflow(wid)
            if workflow.status == WorkflowStatus.INTERRUPTED:
                return workflow
            if is_workflow_terminal(workflow.status):
                return workflow

            if expected_version is not None and workflow.state_version != expected_version:
                raise VersionConflictError(
                    f"Version conflict for workflow {wid}: expected"
                    f" {expected_version}, stored {workflow.state_version}",
                    details={
                        "workflow_id": str(wid),
                        "expected_version": expected_version,
                        "stored_version": workflow.state_version,
                    },
                )

            self._require(
                validate_workflow_transition(workflow.status, WorkflowStatus.INTERRUPTED),
                what="workflow -> interrupted",
            )
            message = reason or f"Owning process ({workflow.owner_id}) disappeared"
            updated = self._bump(
                workflow,
                status=WorkflowStatus.INTERRUPTED,
                recoverable=True,
            )
            self._store_state(wid, updated, expected_version=workflow.state_version)
            self._record_transition(
                wid,
                workflow.status.value,
                WorkflowStatus.INTERRUPTED.value,
                actor=self._owner_id,
                metadata={
                    "operation": "workflow.interrupted",
                    "reason": message,
                    "previous_owner": workflow.owner_id,
                },
                transition_id=_op_transition_id(transition_id, "workflow-interrupted"),
            )
            return updated

    def reconcile_abandoned_workflows(
        self, *, reason: str | None = None
    ) -> list[WorkflowState]:
        """Reconcile all workflows abandoned by a dead process to INTERRUPTED."""
        reconciled: list[WorkflowState] = []
        for workflow in self.find_abandoned_workflows():
            if workflow.status == WorkflowStatus.INTERRUPTED:
                continue
            msg = reason or (
                f"Workflow was owned by {workflow.owner_id!r}, which is not this"
                f" process ({self._owner_id!r})"
            )
            reconciled.append(self.mark_interrupted(workflow.workflow_id, reason=msg))
        return reconciled

    def claim_workflow_for_resume(
        self,
        workflow_id: uuid.UUID | str,
        *,
        owner_id: str | None = None,
        expected_version: int | None = None,
        transition_id: uuid.UUID | None = None,
    ) -> WorkflowState:
        """Atomically claim an INTERRUPTED workflow for controlled resume (Phase 18-J.3).

        Transitions INTERRUPTED -> RUNNING and claims ownership for the caller.
        Guards against duplicate and concurrent resume attempts using optimistic
        versioning.

        Args:
            workflow_id: Workflow to resume.
            owner_id: Resuming process ID.
            expected_version: Concurrency check on state_version.
            transition_id: Idempotency token.

        Returns:
            The claimed and resumed WorkflowState.
        """
        wid = self._as_uuid(workflow_id, what="workflow_id")
        owner = owner_id or self._owner_id

        with self._persistence.transaction():
            workflow = self.get_workflow(wid)

            # Check optimistic concurrency
            if expected_version is not None and workflow.state_version != expected_version:
                raise VersionConflictError(
                    f"Version conflict for workflow {wid}: expected"
                    f" {expected_version}, stored {workflow.state_version}",
                    details={
                        "workflow_id": str(wid),
                        "expected_version": expected_version,
                        "stored_version": workflow.state_version,
                    },
                )

            # Idempotency: if already running and owned by this process, return as is
            if workflow.status == WorkflowStatus.RUNNING and workflow.owner_id == owner:
                return workflow

            if workflow.status != WorkflowStatus.INTERRUPTED:
                raise InvalidStateError(
                    f"Workflow {wid} is in status {workflow.status.value}; only INTERRUPTED workflows can be claimed for resume",
                    details={"workflow_id": str(wid), "status": workflow.status.value},
                )

            self._require(
                validate_workflow_transition(
                    workflow.status,
                    WorkflowStatus.RUNNING,
                    metadata={"resume": True},
                ),
                what="workflow interrupted->running (resume)",
            )

            updated = self._bump(
                workflow,
                status=WorkflowStatus.RUNNING,
                owner_id=owner,
                recoverable=False,
                started_at=workflow.started_at or _now(),
            )
            self._store_state(wid, updated, expected_version=workflow.state_version)
            self._record_transition(
                wid,
                WorkflowStatus.INTERRUPTED.value,
                WorkflowStatus.RUNNING.value,
                actor=owner,
                metadata={
                    "operation": "workflow.resumed",
                    "owner_id": owner,
                },
                transition_id=_op_transition_id(transition_id, "workflow-resumed"),
            )
            return updated

    def complete_workflow(
        self,
        workflow_id: uuid.UUID | str,
        *,
        result: dict[str, Any] | None = None,
        expected_version: int | None = None,
        transition_id: uuid.UUID | None = None,
    ) -> WorkflowState:
        """Mark workflow as FINISHED (terminal)."""
        wid = self._as_uuid(workflow_id, what="workflow_id")
        with self._persistence.transaction():
            workflow = self.get_workflow(wid)
            if workflow.status == WorkflowStatus.FINISHED:
                return workflow
            if is_workflow_terminal(workflow.status):
                raise InvalidStateError(
                    f"Workflow {wid} is already in terminal state {workflow.status.value}",
                    details={"workflow_id": str(wid), "status": workflow.status.value},
                )
            if expected_version is not None and workflow.state_version != expected_version:
                raise VersionConflictError(
                    f"Version conflict for workflow {wid}: expected {expected_version}, stored {workflow.state_version}",
                    details={"workflow_id": str(wid)},
                )
            self._require(
                validate_workflow_transition(
                    workflow.status,
                    WorkflowStatus.FINISHED,
                    metadata={"all_tasks_completed": True},
                ),
                what="workflow -> finished",
            )
            now = _now()
            meta = copy.deepcopy(workflow.metadata)
            if result:
                meta["result"] = result
            updated = self._bump(
                workflow,
                status=WorkflowStatus.FINISHED,
                actual_duration=(now - workflow.started_at) if workflow.started_at else None,
                metadata=meta,
                recoverable=False,
            )
            self._store_state(wid, updated, expected_version=workflow.state_version)
            self._record_transition(
                wid,
                workflow.status.value,
                WorkflowStatus.FINISHED.value,
                actor=self._owner_id,
                metadata={"operation": "workflow.completed"},
                transition_id=_op_transition_id(transition_id, "workflow-completed"),
            )
            return updated

    def fail_workflow(
        self,
        workflow_id: uuid.UUID | str,
        *,
        reason: str | None = None,
        error_code: str | None = None,
        expected_version: int | None = None,
        transition_id: uuid.UUID | None = None,
    ) -> WorkflowState:
        """Mark workflow as FAILED (terminal)."""
        wid = self._as_uuid(workflow_id, what="workflow_id")
        with self._persistence.transaction():
            workflow = self.get_workflow(wid)
            if workflow.status == WorkflowStatus.FAILED:
                return workflow
            if is_workflow_terminal(workflow.status):
                raise InvalidStateError(
                    f"Workflow {wid} is already in terminal state {workflow.status.value}",
                    details={"workflow_id": str(wid), "status": workflow.status.value},
                )
            if expected_version is not None and workflow.state_version != expected_version:
                raise VersionConflictError(
                    f"Version conflict for workflow {wid}: expected {expected_version}, stored {workflow.state_version}",
                    details={"workflow_id": str(wid)},
                )
            self._require(
                validate_workflow_transition(workflow.status, WorkflowStatus.FAILED),
                what="workflow -> failed",
            )
            meta = copy.deepcopy(workflow.metadata)
            meta["failure_reason"] = reason or "Workflow failed"
            if error_code:
                meta["error_code"] = error_code
            updated = self._bump(
                workflow,
                status=WorkflowStatus.FAILED,
                metadata=meta,
                recoverable=False,
            )
            self._store_state(wid, updated, expected_version=workflow.state_version)
            self._record_transition(
                wid,
                workflow.status.value,
                WorkflowStatus.FAILED.value,
                actor=self._owner_id,
                metadata={"operation": "workflow.failed", "reason": reason or ""},
                transition_id=_op_transition_id(transition_id, "workflow-failed"),
            )
            return updated

    def cancel_workflow(
        self,
        workflow_id: uuid.UUID | str,
        *,
        reason: str | None = None,
        expected_version: int | None = None,
        transition_id: uuid.UUID | None = None,
    ) -> WorkflowState:
        """Mark workflow as CANCELLED (terminal)."""
        wid = self._as_uuid(workflow_id, what="workflow_id")
        with self._persistence.transaction():
            workflow = self.get_workflow(wid)
            if workflow.status == WorkflowStatus.CANCELLED:
                return workflow
            if is_workflow_terminal(workflow.status):
                raise InvalidStateError(
                    f"Workflow {wid} is already in terminal state {workflow.status.value}",
                    details={"workflow_id": str(wid), "status": workflow.status.value},
                )
            if expected_version is not None and workflow.state_version != expected_version:
                raise VersionConflictError(
                    f"Version conflict for workflow {wid}: expected {expected_version}, stored {workflow.state_version}",
                    details={"workflow_id": str(wid)},
                )
            self._require(
                validate_workflow_transition(workflow.status, WorkflowStatus.CANCELLED),
                what="workflow -> cancelled",
            )
            meta = copy.deepcopy(workflow.metadata)
            meta["cancellation_reason"] = reason or "User cancelled"
            updated = self._bump(
                workflow,
                status=WorkflowStatus.CANCELLED,
                metadata=meta,
                recoverable=False,
            )
            self._store_state(wid, updated, expected_version=workflow.state_version)
            self._record_transition(
                wid,
                workflow.status.value,
                WorkflowStatus.CANCELLED.value,
                actor=self._owner_id,
                metadata={"operation": "workflow.cancelled", "reason": reason or ""},
                transition_id=_op_transition_id(transition_id, "workflow-cancelled"),
            )
            return updated
