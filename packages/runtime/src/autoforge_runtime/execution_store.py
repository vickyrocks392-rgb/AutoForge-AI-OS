"""Durable Execution Store — durable execution identity, boundaries and recovery metadata.

Phase 18-J (Durable Execution + Resume + Idempotency), step 18-J.2
------------------------------------------------------------------
This module answers the question that must be answerable after a process
crash:

    "If AutoForge stops in the middle of an execution, what durable
     information allows a new process to determine what execution was
     running, what attempt was running, what work unit was being executed,
     what boundary was last durably reached, what was committed, what was
     in-flight, what must be resumed and what must NOT be blindly executed
     twice?"

Nothing here creates a competing store. Every record is written through the
single runtime :class:`~autoforge_runtime.persistence.PersistenceLayer`
(SQLite) that 18-J.1 established, in the same database as every other runtime
entity:

                    Runtime State
                    SINGLE SOURCE
                         |
             +-----------+-----------+
             |           |           |
             v           v           v
         Workflow     Execution    Recovery
        projection    projection   projection
             |           |           |
             +-----------+-----------+
                         |
                         v
                 PersistenceLayer
                         |
                         v
                  SQLiteStorage

The three durable records
-------------------------

``ExecutionState`` (``EntityType.EXECUTION``)
    One *logical* execution: a work unit such as one task of one workflow
    instance. ``execution_id`` is canonical and stable for the whole life of
    the execution. A retry never mints a new logical execution.

``ExecutionAttemptState`` (``EntityType.EXECUTION_ATTEMPT``)
    One *attempt* of one execution. Attempt identity is distinct from
    execution identity; retry N+1 of execution E is a new attempt of E.

``ExecutionCheckpointState`` (``EntityType.EXECUTION_CHECKPOINT``)
    One *durable boundary* of one attempt: the last committed truth edge of a
    work unit. Boundaries are written deliberately (never on a timer) and are
    monotonic per execution (``sequence``).

Durable state is authoritative
------------------------------
Transitions are committed *before* anything is announced: the store writes
the new record and its history entry inside one
:meth:`PersistenceLayer.transaction` block, and only then returns. Execution
events (published by the Execution Engine) are derived publications and are
never the authoritative commit. A crash after an event but before a commit
leaves durable state unchanged, which is exactly the desired semantics.

What J.2 guarantees
-------------------
``Durable execution state is now reconstructable after process restart.``

* execution identity, attempt identity and boundaries are durable
* critical transitions are atomic and replay-safe (``transition_id``)
* a RUNNING execution from a dead process is detectable and is represented as
  ``interrupted`` (never as ``failed``, never as ``completed``)
* an interrupted execution is *never* resumed automatically by this module

What J.2 does NOT guarantee
---------------------------
* no exactly-once external side effects (18-J.4)
* no automatic workflow resume / queue reconstruction (18-J.3)
* no HITL approval persistence, artifact durability or sandbox recovery
  (18-J.3/J.5)
"""

from __future__ import annotations

import os
import socket
import uuid
from dataclasses import dataclass
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
    AttemptStatus,
    EntityType,
    ExecutionAttemptState,
    ExecutionCheckpointState,
    ExecutionState,
    ExecutionStatus,
    FailureRecord,
    FailureRecoverability,
    FailureSeverity,
    FailureSource,
    StateTransition,
)
from autoforge_runtime.persistence import PersistenceLayer
from autoforge_runtime.validation import (
    is_execution_terminal,
    validate_attempt_transition,
    validate_execution_transition,
)

__all__ = [
    "DurableExecutionStore",
    "ExecutionReconstruction",
    "EXECUTION_ID_NAMESPACE",
    "default_owner_id",
    "execution_id_for_key",
    "execution_key_for_task",
]


#: Stable UUIDv5 namespace used to derive canonical execution identity from a
#: work-unit key. Deterministic derivation is what makes "the same logical
#: execution" reproducible in a *new* process after a crash.
EXECUTION_ID_NAMESPACE = uuid.UUID("6f2f5b1c-9d64-4d2a-9a9f-2d8c5f4b7e18")

#: Neutral state label used as ``from_state`` when a record is first created.
_CREATED_FROM_STATE = "none"


def default_owner_id() -> str:
    """Return the identity of the current process (``host:pid``)."""
    return f"{socket.gethostname()}:{os.getpid()}"


def execution_key_for_task(workflow_id: uuid.UUID | str, task_id: str) -> str:
    """Return the canonical work-unit key of a workflow task.

    One workflow task of one workflow instance *is* one logical execution, so
    the key (and therefore the derived execution identity) is stable across
    retries and across process restarts.
    """
    return f"workflow:{uuid.UUID(str(workflow_id))}:task:{task_id}"


def execution_id_for_key(execution_key: str) -> uuid.UUID:
    """Derive the canonical execution ID for a work-unit key."""
    if not execution_key:
        raise ValidationError("execution_key must not be empty")
    return uuid.uuid5(EXECUTION_ID_NAMESPACE, execution_key)


def _now() -> datetime:
    """Return the current timezone-aware UTC timestamp."""
    return datetime.now(timezone.utc)


def _op_transition_id(operation_id: uuid.UUID | None, suffix: str) -> uuid.UUID:
    """Derive a deterministic history-row ID from an operation ID.

    Replaying an operation with the same ``transition_id`` therefore produces
    identical history row IDs, and the append-only store ignores duplicates —
    a retried transition can never duplicate the audit trail.
    """
    if operation_id is None:
        return uuid.uuid4()
    return uuid.uuid5(operation_id, suffix)


@dataclass(frozen=True)
class ExecutionReconstruction:
    """Durable read model used to rebuild execution state after a restart.

    Every field is derived from durable storage; nothing is inferred from
    in-memory state, worker objects or published events.
    """

    execution: ExecutionState
    attempts: tuple[ExecutionAttemptState, ...]
    checkpoints: tuple[ExecutionCheckpointState, ...]
    latest_checkpoint: ExecutionCheckpointState | None
    active_attempt: ExecutionAttemptState | None
    history: tuple[StateTransition, ...]
    abandoned: bool
    """Durable truth says the owning process is gone (owner differs/unknown)
    while the execution is still active."""

    interrupted: bool
    """The execution was durably marked interrupted."""

    resumable: bool
    """A later phase (18-J.3) may resume this execution. Never true for a
    terminal execution, and never an instruction to resume automatically."""

    @property
    def recovery_metadata(self) -> dict[str, Any]:
        """Return a flat, inspectable recovery summary of the durable facts."""
        execution = self.execution
        checkpoint = self.latest_checkpoint
        return {
            "execution_id": str(execution.execution_id),
            "execution_key": execution.execution_key,
            "workflow_id": str(execution.workflow_id) if execution.workflow_id else None,
            "task_id": execution.task_id,
            "status": execution.status.value,
            "attempt_count": execution.attempt_count,
            "active_attempt_number": (
                self.active_attempt.attempt_number if self.active_attempt else None
            ),
            "last_attempt_number": (
                self.attempts[-1].attempt_number if self.attempts else None
            ),
            "last_attempt_status": (
                self.attempts[-1].status.value if self.attempts else None
            ),
            "last_checkpoint_id": str(checkpoint.checkpoint_id) if checkpoint else None,
            "last_checkpoint_sequence": checkpoint.sequence if checkpoint else None,
            "last_checkpoint_label": checkpoint.label if checkpoint else None,
            "interrupted": self.interrupted,
            "abandoned": self.abandoned,
            "resumable": self.resumable,
            "execution_version": execution.version,
            "transitions": len(self.history),
        }


class DurableExecutionStore:
    """Durable execution records, attempts, boundaries and reconstruction.

    The store is a *projection* over the one runtime persistence foundation:
    it owns no database, no cache and no history log of its own. It delegates
    every read and write to the injected
    :class:`~autoforge_runtime.persistence.PersistenceLayer`, which means:

    * one authoritative durable state (Section 15 of the Runtime State
      Manager Specification),
    * cache coherence rules of 18-J.1 apply unchanged (a rolled-back
      transaction can never leave a stale cache entry),
    * optimistic concurrency (``expected_version``) and idempotent history
      (``transition_id``) keep working exactly as in 18-J.1.

    Args:
        persistence: The runtime persistence layer (required).
        owner_id: Identity of the owning process; defaults to ``host:pid``.
            It is stored on every execution the store starts and is the
            durable evidence used to detect executions abandoned by a dead
            process.
    """

    def __init__(
        self,
        persistence: PersistenceLayer,
        *,
        owner_id: str | None = None,
    ) -> None:
        """Initialize the durable execution store."""
        if persistence is None:  # pragma: no cover - defensive
            raise PersistenceError(
                "DurableExecutionStore requires the runtime persistence layer",
                details={},
            )
        self._persistence = persistence
        self._owner_id = owner_id or default_owner_id()

    # ── Introspection ────────────────────────────────────────────────────

    @property
    def persistence(self) -> PersistenceLayer:
        """The runtime persistence layer backing this store."""
        return self._persistence

    @property
    def owner_id(self) -> str:
        """Identity of the owning process (``host:pid`` by default)."""
        return self._owner_id

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"DurableExecutionStore(owner_id={self._owner_id!r}, db_path={self._persistence.db_path!r})"

    # ── Internal helpers ─────────────────────────────────────────────────

    def _bump(self, state: Any, **updates: Any) -> Any:
        """Return a copy of ``state`` with ``updates`` applied and version+1."""
        payload = dict(updates)
        payload["version"] = state.version + 1
        payload["updated_at"] = _now()
        return state.model_copy(update=payload)

    @staticmethod
    def _require(result: Any, *, what: str) -> None:
        """Raise :class:`InvalidTransitionError` when a validation failed."""
        if not result.valid:
            raise InvalidTransitionError(
                result.error_message or f"Invalid transition: {what}",
                details=dict(result.details or {}),
            )

    def _record_transition(
        self,
        entity_type: EntityType,
        entity_id: uuid.UUID,
        from_state: str,
        to_state: str,
        *,
        actor: str,
        metadata: dict[str, Any] | None = None,
        transition_id: uuid.UUID | None = None,
    ) -> StateTransition:
        """Append one transition to the shared, replay-safe history store."""
        transition = StateTransition(
            transition_id=transition_id or uuid.uuid4(),
            entity_type=entity_type,
            entity_id=entity_id,
            from_state=from_state,
            to_state=to_state,
            actor=actor,
            timestamp=_now(),
            metadata=metadata or {},
        )
        self._persistence.write_history(transition)
        return transition

    def _store_state(
        self,
        entity_type: EntityType,
        entity_id: uuid.UUID,
        state: Any,
        *,
        expected_version: int | None = None,
    ) -> Any:
        """Write one entity state through the persistence layer."""
        self._persistence.write_state(
            entity_type, entity_id, state, expected_version=expected_version
        )
        return state

    def _read_state(self, entity_type: EntityType, entity_id: uuid.UUID) -> Any:
        """Read one entity state and fail loudly on a corrupt payload."""
        state = self._persistence.read_state(entity_type, entity_id)
        return state

    def _typed(self, entity_type: EntityType) -> list[Any]:
        """Read every record of one entity type (typed query, append order)."""
        return list(self._persistence.read_all(entity_type))

    def _resolve_attempt(
        self,
        execution: ExecutionState,
        attempt_id: uuid.UUID | None,
        *,
        require_started: bool = False,
    ) -> ExecutionAttemptState:
        """Resolve the attempt a transition applies to.

        When ``attempt_id`` is omitted the execution's current attempt is used;
        that is the attempt durably recorded as most recently started.
        """
        if attempt_id is not None:
            attempt = self.get_attempt(execution.execution_id, attempt_id)
        elif execution.current_attempt_id is not None:
            attempt = self.get_attempt(execution.execution_id, execution.current_attempt_id)
        else:
            raise InvalidStateError(
                f"Execution {execution.execution_id} has no attempt to transition",
                details={"execution_id": str(execution.execution_id)},
            )
        if require_started and attempt.status != AttemptStatus.STARTED:
            raise InvalidStateError(
                f"Attempt {attempt.attempt_id} is {attempt.status.value}, not started",
                details={
                    "execution_id": str(execution.execution_id),
                    "attempt_id": str(attempt.attempt_id),
                    "attempt_status": attempt.status.value,
                },
            )
        return attempt

    @staticmethod
    def _as_uuid(value: uuid.UUID | str, *, what: str) -> uuid.UUID:
        """Coerce an identifier to a UUID, failing with a runtime error."""
        if isinstance(value, uuid.UUID):
            return value
        try:
            return uuid.UUID(str(value))
        except (TypeError, ValueError) as exc:
            raise ValidationError(
                f"Invalid {what}: {value!r}", details={what: str(value)}
            ) from exc

    # ── Query API (the recovery read path) ───────────────────────────────
    #
    # Every query below reads exactly one runtime entity type from durable
    # storage. None of them rebuilds in-memory worker state, replays events or
    # reconstructs "the universe" first.

    def get_execution(self, execution_id: uuid.UUID | str) -> ExecutionState:
        """Return the durable execution record.

        Raises:
            EntityNotFoundError: If the execution is not durably recorded.
        """
        eid = self._as_uuid(execution_id, what="execution_id")
        state = self._read_state(EntityType.EXECUTION, eid)
        if not isinstance(state, ExecutionState):  # pragma: no cover - defensive
            raise PersistenceError(
                f"Invalid execution state for ID {eid}",
                details={"execution_id": str(eid)},
            )
        return state

    def try_get_execution(self, execution_id: uuid.UUID | str) -> ExecutionState | None:
        """Return the durable execution record, or ``None`` when absent."""
        try:
            return self.get_execution(execution_id)
        except EntityNotFoundError:
            return None

    def get_execution_by_key(self, execution_key: str) -> ExecutionState | None:
        """Return the execution recorded for a work-unit key, if any.

        The canonical ID is derived from the key first (O(1)); the fallback
        scan covers records created with an explicit, non-derived ID.
        """
        if not execution_key:
            raise ValidationError("execution_key must not be empty")
        derived = self.try_get_execution(execution_id_for_key(execution_key))
        if derived is not None and derived.execution_key == execution_key:
            return derived
        for execution in self._typed(EntityType.EXECUTION):
            if execution.execution_key == execution_key:
                return execution
        return derived

    def get_attempt(
        self, execution_id: uuid.UUID | str, attempt_id: uuid.UUID | str
    ) -> ExecutionAttemptState:
        """Return one durable attempt of an execution.

        Raises:
            EntityNotFoundError: If the attempt is absent or belongs to another
                execution (attempt identity is scoped by execution identity).
        """
        eid = self._as_uuid(execution_id, what="execution_id")
        aid = self._as_uuid(attempt_id, what="attempt_id")
        try:
            state = self._read_state(EntityType.EXECUTION_ATTEMPT, aid)
        except EntityNotFoundError:
            raise EntityNotFoundError(
                f"Attempt with ID {aid} not found",
                details={"entity_id": str(aid), "entity_type": "execution_attempt"},
            ) from None
        if not isinstance(state, ExecutionAttemptState) or state.execution_id != eid:
            raise EntityNotFoundError(
                f"Attempt {aid} does not belong to execution {eid}",
                details={
                    "attempt_id": str(aid),
                    "execution_id": str(eid),
                    "attempt_execution_id": str(getattr(state, "execution_id", None)),
                },
            )
        return state

    def get_attempt_by_number(
        self, execution_id: uuid.UUID | str, attempt_number: int
    ) -> ExecutionAttemptState | None:
        """Return the attempt with a specific number, or ``None``."""
        for attempt in self.get_attempts(execution_id):
            if attempt.attempt_number == attempt_number:
                return attempt
        return None

    def get_attempts(self, execution_id: uuid.UUID | str) -> list[ExecutionAttemptState]:
        """Return every durable attempt of an execution, ordered by number."""
        eid = self._as_uuid(execution_id, what="execution_id")
        attempts = [
            attempt
            for attempt in self._typed(EntityType.EXECUTION_ATTEMPT)
            if attempt.execution_id == eid
        ]
        return sorted(attempts, key=lambda attempt: attempt.attempt_number)

    def get_active_attempt(
        self, execution_id: uuid.UUID | str
    ) -> ExecutionAttemptState | None:
        """Return the attempt that is still in flight (``STARTED``), if any.

        A ``None`` result is meaningful after a restart: no attempt of this
        execution was in flight when durable state was last written.
        """
        attempts = self.get_attempts(execution_id)
        for attempt in reversed(attempts):
            if attempt.status == AttemptStatus.STARTED:
                return attempt
        return None

    def get_checkpoints(
        self, execution_id: uuid.UUID | str
    ) -> list[ExecutionCheckpointState]:
        """Return every durable boundary of an execution, ordered by sequence."""
        eid = self._as_uuid(execution_id, what="execution_id")
        checkpoints = [
            checkpoint
            for checkpoint in self._typed(EntityType.EXECUTION_CHECKPOINT)
            if checkpoint.execution_id == eid
        ]
        return sorted(checkpoints, key=lambda checkpoint: checkpoint.sequence)

    def get_latest_checkpoint(
        self, execution_id: uuid.UUID | str
    ) -> ExecutionCheckpointState | None:
        """Return the last durably committed boundary of an execution.

        The execution record carries a pointer to its latest boundary, so the
        common case is a single read; the scan fallback keeps the answer
        correct even if the pointer is stale.
        """
        eid = self._as_uuid(execution_id, what="execution_id")
        execution = self.try_get_execution(eid)
        if execution is not None and execution.last_checkpoint_id is not None:
            try:
                checkpoint = self._read_state(
                    EntityType.EXECUTION_CHECKPOINT, execution.last_checkpoint_id
                )
            except EntityNotFoundError:
                checkpoint = None
            if (
                isinstance(checkpoint, ExecutionCheckpointState)
                and checkpoint.execution_id == eid
            ):
                return checkpoint
        checkpoints = self.get_checkpoints(eid)
        return checkpoints[-1] if checkpoints else None

    def list_executions(self) -> list[ExecutionState]:
        """Return every durable execution, ordered by creation time."""
        executions = list(self._typed(EntityType.EXECUTION))
        return sorted(executions, key=lambda e: (e.created_at, str(e.execution_id)))

    def list_active_executions(self) -> list[ExecutionState]:
        """Return executions that are not terminal (created, running, interrupted)."""
        return [
            execution
            for execution in self.list_executions()
            if not is_execution_terminal(execution.status)
        ]

    def list_interrupted_executions(self) -> list[ExecutionState]:
        """Return executions durably marked ``interrupted`` (recoverable)."""
        return [
            execution
            for execution in self.list_executions()
            if execution.status == ExecutionStatus.INTERRUPTED
        ]

    def list_executions_for_workflow(self, workflow_id: uuid.UUID | str) -> list[ExecutionState]:
        """Return the executions durably linked to a workflow."""
        wid = self._as_uuid(workflow_id, what="workflow_id")
        return [
            execution
            for execution in self.list_executions()
            if execution.workflow_id == wid
        ]

    def list_executions_for_task(self, task_id: str) -> list[ExecutionState]:
        """Return the executions durably linked to a work unit (task)."""
        return [
            execution
            for execution in self.list_executions()
            if execution.task_id == task_id
        ]

    def find_abandoned_executions(self) -> list[ExecutionState]:
        """Return active executions owned by a *different* process.

        This is the positive, non-mutating evidence that a process died while
        it owned executions: the record still says "running", but the owner is
        not this process. Executions with no recorded owner cannot be
        attributed and are therefore not reported.
        """
        return [
            execution
            for execution in self.list_active_executions()
            if execution.owner_id is not None and execution.owner_id != self._owner_id
        ]

    def get_transition_history(self, execution_id: uuid.UUID | str) -> list[StateTransition]:
        """Return every recorded transition of an execution and its records.

        The history is the audit trail of the *same* persistence foundation —
        it is not a second event log, and it is not authoritative state. It is
        ordered by recorded timestamp so it can be used as replay evidence.
        """
        eid = self._as_uuid(execution_id, what="execution_id")
        transitions: list[StateTransition] = list(
            self._persistence.history.read_by_entity(EntityType.EXECUTION, eid)
        )
        for attempt in self.get_attempts(eid):
            transitions.extend(
                self._persistence.history.read_by_entity(
                    EntityType.EXECUTION_ATTEMPT, attempt.attempt_id
                )
            )
        for checkpoint in self.get_checkpoints(eid):
            transitions.extend(
                self._persistence.history.read_by_entity(
                    EntityType.EXECUTION_CHECKPOINT, checkpoint.checkpoint_id
                )
            )
        return sorted(transitions, key=lambda t: (t.timestamp, str(t.transition_id)))

    def reconstruct(self, execution_id: uuid.UUID | str) -> ExecutionReconstruction:
        """Rebuild the durable truth of one execution after a restart.

        This is the primitive 18-J.3 will use to resume work. It performs no
        state change: it reports what was committed, what was in flight, and
        whether durable evidence says the execution was abandoned or
        interrupted.
        """
        eid = self._as_uuid(execution_id, what="execution_id")
        execution = self.get_execution(eid)
        attempts = tuple(self.get_attempts(eid))
        checkpoints = tuple(self.get_checkpoints(eid))
        latest = checkpoints[-1] if checkpoints else None
        active = self.get_active_attempt(eid)
        terminal = is_execution_terminal(execution.status)
        abandoned = (
            not terminal
            and execution.owner_id is not None
            and execution.owner_id != self._owner_id
        )
        interrupted = execution.status == ExecutionStatus.INTERRUPTED
        return ExecutionReconstruction(
            execution=execution,
            attempts=attempts,
            checkpoints=checkpoints,
            latest_checkpoint=latest,
            active_attempt=active,
            history=tuple(self.get_transition_history(eid)),
            abandoned=abandoned,
            interrupted=interrupted,
            resumable=not terminal and (interrupted or abandoned),
        )

    # ── Transition API (durable write path) ──────────────────────────────
    #
    # Every method below commits through PersistenceLayer.transaction(), so a
    # multi-record transition (execution + attempt + history) is atomic: a
    # process that dies mid-transition leaves *no* partial durable state.

    def _create_execution(
        self,
        execution_id: uuid.UUID,
        *,
        execution_key: str | None,
        workflow_id: uuid.UUID | None,
        task_id: str | None,
        correlation_id: uuid.UUID | None,
        owner_id: str,
        metadata: dict[str, Any] | None,
        transition_id: uuid.UUID | None,
    ) -> ExecutionState:
        """Create the durable execution record (``created``)."""
        execution = ExecutionState(
            execution_id=execution_id,
            execution_key=execution_key,
            workflow_id=workflow_id,
            task_id=task_id,
            correlation_id=correlation_id,
            status=ExecutionStatus.CREATED,
            owner_id=owner_id,
            metadata=dict(metadata or {}),
        )
        self._store_state(EntityType.EXECUTION, execution_id, execution, expected_version=None)
        self._record_transition(
            EntityType.EXECUTION,
            execution_id,
            _CREATED_FROM_STATE,
            ExecutionStatus.CREATED.value,
            actor=owner_id,
            metadata={
                "operation": "execution.created",
                "execution_key": execution_key,
                "workflow_id": str(workflow_id) if workflow_id else None,
                "task_id": task_id,
            },
            transition_id=_op_transition_id(transition_id, "execution-created"),
        )
        return execution

    def _start_attempt(
        self,
        execution: ExecutionState,
        *,
        attempt_number: int,
        worker_id: str | None,
        worker_type: str | None,
        max_attempts: int | None,
        transition_id: uuid.UUID | None,
        expected_version: int | None,
    ) -> ExecutionState:
        """Record a new attempt of ``execution`` and point the execution at it."""
        previous = (
            self.get_attempt_by_number(execution.execution_id, attempt_number - 1)
            if attempt_number > 1
            else None
        )
        attempt = ExecutionAttemptState(
            execution_id=execution.execution_id,
            attempt_number=attempt_number,
            status=AttemptStatus.STARTED,
            worker_id=worker_id,
            worker_type=worker_type,
            previous_attempt_id=previous.attempt_id if previous else None,
            max_attempts=max_attempts,
            started_at=_now(),
        )
        self._store_state(
            EntityType.EXECUTION_ATTEMPT, attempt.attempt_id, attempt, expected_version=None
        )
        self._record_transition(
            EntityType.EXECUTION_ATTEMPT,
            attempt.attempt_id,
            _CREATED_FROM_STATE,
            AttemptStatus.STARTED.value,
            actor=self._owner_id,
            metadata={
                "operation": "attempt.started",
                "execution_id": str(execution.execution_id),
                "attempt_number": attempt_number,
                "previous_attempt_id": (
                    str(attempt.previous_attempt_id) if attempt.previous_attempt_id else None
                ),
                "worker_id": worker_id,
                "worker_type": worker_type,
            },
            transition_id=_op_transition_id(
                transition_id, f"attempt-started-{attempt_number}"
            ),
        )
        updated = self._bump(
            execution,
            attempt_count=max(execution.attempt_count, attempt_number),
            current_attempt_id=attempt.attempt_id,
            current_attempt_number=attempt_number,
        )
        self._store_state(
            EntityType.EXECUTION, execution.execution_id, updated, expected_version=expected_version
        )
        return updated

    def begin_execution(
        self,
        execution_id: uuid.UUID | str | None = None,
        *,
        execution_key: str | None = None,
        workflow_id: uuid.UUID | str | None = None,
        task_id: str | None = None,
        correlation_id: uuid.UUID | str | None = None,
        attempt_number: int = 1,
        worker_id: str | None = None,
        worker_type: str | None = None,
        max_attempts: int | None = None,
        owner_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        expected_version: int | None = None,
        transition_id: uuid.UUID | None = None,
    ) -> ExecutionState:
        """Durably record that a logical execution (and its attempt) started.

        This is the "before start commit" of a work unit, and it is idempotent
        in the way a durable system needs it to be:

        * the same work unit (same key) always resolves to the same canonical
          ``execution_id`` — a retry can never mint a second logical execution;
        * replaying the same ``attempt_number`` for an execution that already
          recorded it is a no-op (no duplicate attempt, no duplicate
          transition);
        * a *new* ``attempt_number`` records a new attempt of the *same*
          execution (this is exactly the retry path).

        Args:
            execution_id: Explicit canonical execution ID. When omitted the ID
                is derived from ``execution_key`` (deterministic) or generated.
            execution_key: Work-unit key (see :func:`execution_key_for_task`).
            workflow_id: Durable link to the workflow owning the work unit.
            task_id: Durable link to the work unit inside the workflow.
            correlation_id: Correlation identifier for tracing.
            attempt_number: Attempt to start (defaults to the first attempt).
            worker_id: Worker that owns the attempt, when already known.
            worker_type: Worker role, when known.
            max_attempts: Retry budget in force, when known.
            owner_id: Owning process identity (defaults to this store's owner).
            metadata: Extensible metadata for the execution record.
            expected_version: Optional optimistic guard; the stored execution
                version must match, and a guard against a missing record fails.
            transition_id: Idempotency key for this operation. Replaying the
                same operation ID can never duplicate the audit trail.

        Returns:
            The durable execution record after the attempt was recorded.

        Raises:
            ValidationError: If an argument is structurally invalid.
            VersionConflictError: If ``expected_version`` is stale.
            InvalidStateError: If the execution is terminal, or interrupted
                (re-opening or resuming is *not* a J.2 capability).
        """
        if attempt_number is None or attempt_number < 1:
            raise ValidationError(
                "attempt_number must be >= 1",
                details={"attempt_number": str(attempt_number)},
            )
        wid = self._as_uuid(workflow_id, what="workflow_id") if workflow_id else None
        cid = self._as_uuid(correlation_id, what="correlation_id") if correlation_id else None
        resolved_key = execution_key
        if resolved_key is None and wid is not None and task_id:
            resolved_key = execution_key_for_task(wid, task_id)
        if execution_id is not None:
            eid = self._as_uuid(execution_id, what="execution_id")
        elif resolved_key is not None:
            eid = execution_id_for_key(resolved_key)
        else:
            eid = uuid.uuid4()
        owner = owner_id or self._owner_id

        with self._persistence.transaction():
            execution = self.try_get_execution(eid)
            if expected_version is not None:
                if execution is None:
                    raise VersionConflictError(
                        f"Expected version {expected_version} for execution {eid},"
                        " but no execution exists",
                        details={"execution_id": str(eid), "expected_version": expected_version},
                    )
                if execution.version != expected_version:
                    raise VersionConflictError(
                        f"Version conflict for execution {eid}: expected"
                        f" {expected_version}, stored {execution.version}",
                        details={
                            "execution_id": str(eid),
                            "expected_version": expected_version,
                            "stored_version": execution.version,
                        },
                    )
            if execution is None:
                execution = self._create_execution(
                    eid,
                    execution_key=resolved_key,
                    workflow_id=wid,
                    task_id=task_id,
                    correlation_id=cid,
                    owner_id=owner,
                    metadata=metadata,
                    transition_id=transition_id,
                )
            if is_execution_terminal(execution.status):
                raise InvalidStateError(
                    f"Execution {eid} is {execution.status.value} and cannot be started again",
                    details={
                        "execution_id": str(eid),
                        "status": execution.status.value,
                        "hint": "a new logical execution requires a new execution_id/key",
                    },
                )
            if execution.status == ExecutionStatus.INTERRUPTED:
                if metadata and metadata.get("resume"):
                    resumed_exec, _ = self.resume_execution(
                        eid,
                        owner_id=owner,
                        attempt_number=attempt_number,
                        worker_id=worker_id,
                        worker_type=worker_type,
                        max_attempts=max_attempts,
                        expected_version=expected_version,
                        transition_id=transition_id,
                    )
                    return resumed_exec
                raise InvalidStateError(
                    f"Execution {eid} is interrupted; explicit controlled resume required",
                    details={"execution_id": str(eid), "status": execution.status.value},
                )
            if execution.status == ExecutionStatus.CREATED:
                self._require(
                    validate_execution_transition(
                        execution.status, ExecutionStatus.RUNNING
                    ),
                    what="execution created->running",
                )
                execution = self._bump(
                    execution,
                    status=ExecutionStatus.RUNNING,
                    started_at=execution.started_at or _now(),
                    owner_id=owner,
                )
                self._store_state(EntityType.EXECUTION, eid, execution, expected_version=None)
                self._record_transition(
                    EntityType.EXECUTION,
                    eid,
                    ExecutionStatus.CREATED.value,
                    ExecutionStatus.RUNNING.value,
                    actor=owner,
                    metadata={
                        "operation": "execution.started",
                        "attempt_number": attempt_number,
                        "execution_key": resolved_key,
                        "workflow_id": str(wid) if wid else None,
                        "task_id": task_id,
                    },
                    transition_id=_op_transition_id(transition_id, "execution-started"),
                )
            if self.get_attempt_by_number(eid, attempt_number) is not None:
                # Replay: this attempt start is already durably recorded.
                return execution
            return self._start_attempt(
                execution,
                attempt_number=attempt_number,
                worker_id=worker_id,
                worker_type=worker_type,
                max_attempts=max_attempts,
                transition_id=transition_id,
                expected_version=execution.version,
            )

    def begin_attempt(
        self,
        execution_id: uuid.UUID | str,
        *,
        attempt_number: int | None = None,
        worker_id: str | None = None,
        worker_type: str | None = None,
        max_attempts: int | None = None,
        expected_version: int | None = None,
        transition_id: uuid.UUID | None = None,
    ) -> ExecutionAttemptState:
        """Durably record a new attempt (a retry) of an existing execution.

        The execution identity is untouched: this is the API that proves a
        retry adds an attempt instead of creating a new logical execution.

        Args:
            execution_id: The canonical execution ID.
            attempt_number: Explicit attempt number; defaults to the next one.
            worker_id: Worker that owns the attempt, when known.
            worker_type: Worker role, when known.
            max_attempts: Retry budget in force, when known.
            expected_version: Optional optimistic guard on the execution record.
            transition_id: Idempotency key for this operation.

        Returns:
            The durable attempt record (the existing one when replayed).

        Raises:
            EntityNotFoundError: If the execution is not durably recorded.
            InvalidStateError: If the execution is not ``running``.
            VersionConflictError: If ``expected_version`` is stale.
        """
        eid = self._as_uuid(execution_id, what="execution_id")
        with self._persistence.transaction():
            execution = self.get_execution(eid)
            if execution.status != ExecutionStatus.RUNNING:
                raise InvalidStateError(
                    f"Cannot start an attempt for execution {eid} in status"
                    f" {execution.status.value}",
                    details={"execution_id": str(eid), "status": execution.status.value},
                )
            if expected_version is not None and execution.version != expected_version:
                raise VersionConflictError(
                    f"Version conflict for execution {eid}: expected"
                    f" {expected_version}, stored {execution.version}",
                    details={
                        "execution_id": str(eid),
                        "expected_version": expected_version,
                        "stored_version": execution.version,
                    },
                )
            attempts = self.get_attempts(eid)
            number = (
                attempt_number
                if attempt_number is not None
                else (attempts[-1].attempt_number + 1 if attempts else 1)
            )
            if number < 1:
                raise ValidationError(
                    "attempt_number must be >= 1", details={"attempt_number": str(number)}
                )
            existing = self.get_attempt_by_number(eid, number)
            if existing is not None:
                return existing
            updated = self._start_attempt(
                execution,
                attempt_number=number,
                worker_id=worker_id,
                worker_type=worker_type,
                max_attempts=max_attempts,
                transition_id=transition_id,
                expected_version=execution.version,
            )
            attempt_id = updated.current_attempt_id
            if attempt_id is None:  # pragma: no cover - defensive
                raise PersistenceError(
                    "Attempt start did not record the attempt reference",
                    details={"execution_id": str(eid)},
                )
            return self.get_attempt(eid, attempt_id)

    def resume_execution(
        self,
        execution_id: uuid.UUID | str,
        *,
        owner_id: str | None = None,
        attempt_number: int | None = None,
        worker_id: str | None = None,
        worker_type: str | None = None,
        max_attempts: int | None = None,
        metadata: dict[str, Any] | None = None,
        expected_version: int | None = None,
        transition_id: uuid.UUID | None = None,
    ) -> tuple[ExecutionState, ExecutionAttemptState]:
        """Perform a controlled resume of an interrupted execution (Phase 18-J.3).

        Atomically transitions the execution from INTERRUPTED to RUNNING,
        claims ownership for the current process, and records a new physical
        attempt for this logical execution while preserving the execution identity.

        Args:
            execution_id: Canonical execution ID.
            owner_id: Identity of the resuming process (defaults to this store's owner).
            attempt_number: Explicit attempt number (defaults to execution.attempt_count + 1).
            worker_id: Assigned worker if known.
            worker_type: Worker type if known.
            max_attempts: Max attempts budget.
            expected_version: Optional optimistic concurrency guard.
            transition_id: Idempotency token for history.

        Returns:
            A tuple of (updated ExecutionState, new ExecutionAttemptState).

        Raises:
            EntityNotFoundError: If execution does not exist.
            InvalidStateError: If execution is not INTERRUPTED.
            VersionConflictError: If expected_version is stale.
        """
        eid = self._as_uuid(execution_id, what="execution_id")
        owner = owner_id or self._owner_id

        with self._persistence.transaction():
            execution = self.get_execution(eid)
            if expected_version is not None and execution.version != expected_version:
                raise VersionConflictError(
                    f"Version conflict for execution {eid}: expected"
                    f" {expected_version}, stored {execution.version}",
                    details={
                        "execution_id": str(eid),
                        "expected_version": expected_version,
                        "stored_version": execution.version,
                    },
                )

            next_attempt_num = (
                attempt_number
                if attempt_number is not None
                else execution.attempt_count + 1
            )
            # Idempotency check: if already resumed by this owner with this attempt, return existing
            if execution.status == ExecutionStatus.RUNNING and execution.owner_id == owner:
                active = self.get_active_attempt(eid)
                if active and active.attempt_number == next_attempt_num:
                    return execution, active

            if execution.status != ExecutionStatus.INTERRUPTED:
                raise InvalidStateError(
                    f"Execution {eid} is {execution.status.value}; only INTERRUPTED executions can be resumed",
                    details={"execution_id": str(eid), "status": execution.status.value},
                )

            self._require(
                validate_execution_transition(
                    execution.status, ExecutionStatus.RUNNING, metadata={"resume": True}
                ),
                what="execution interrupted->running (resume)",
            )

            resumed_at = _now()
            execution_updated = self._bump(
                execution,
                status=ExecutionStatus.RUNNING,
                owner_id=owner,
                interrupted_at=None,
                recoverable=False,
                started_at=execution.started_at or resumed_at,
            )
            self._store_state(
                EntityType.EXECUTION,
                eid,
                execution_updated,
                expected_version=execution.version,
            )
            self._record_transition(
                EntityType.EXECUTION,
                eid,
                ExecutionStatus.INTERRUPTED.value,
                ExecutionStatus.RUNNING.value,
                actor=owner,
                metadata={
                    "operation": "execution.resumed",
                    "attempt_number": next_attempt_num,
                    "previous_attempts": execution.attempt_count,
                    "owner_id": owner,
                },
                transition_id=_op_transition_id(transition_id, "execution-resumed"),
            )

            # Check if this attempt was already started (replay safety)
            existing_attempt = self.get_attempt_by_number(eid, next_attempt_num)
            if existing_attempt is not None:
                return execution_updated, existing_attempt

            updated_execution = self._start_attempt(
                execution_updated,
                attempt_number=next_attempt_num,
                worker_id=worker_id,
                worker_type=worker_type,
                max_attempts=max_attempts,
                transition_id=transition_id,
                expected_version=execution_updated.version,
            )
            attempt = self.get_attempt_by_number(eid, next_attempt_num)
            if attempt is None:
                attempt = self.get_active_attempt(eid)
            return updated_execution, attempt

    def record_checkpoint(
        self,
        execution_id: uuid.UUID | str,
        *,
        label: str,
        boundary_state: dict[str, Any] | None = None,
        attempt_id: uuid.UUID | str | None = None,
        checkpoint_id: uuid.UUID | str | None = None,
        created_by: str = "system",
        metadata: dict[str, Any] | None = None,
        expected_version: int | None = None,
        transition_id: uuid.UUID | None = None,
    ) -> ExecutionCheckpointState:
        """Commit a durable execution boundary for the current attempt.

        A boundary is written only when a work unit step reached a state whose
        result is durably known. Sequence numbers are monotonic per execution
        and the boundary links to the previous boundary, the attempt, the
        execution and the work unit.

        This method does **not** claim that side effects performed before the
        boundary are reversible or exactly-once.

        Args:
            execution_id: The canonical execution ID.
            label: Meaningful boundary label (e.g. ``dispatch-completed``).
            boundary_state: Structured, inspectable facts reached here.
            attempt_id: Attempt the boundary belongs to (defaults to current).
            checkpoint_id: Explicit boundary ID (mainly for replay).
            created_by: Actor recording the boundary.
            metadata: Extensible metadata for the boundary record.
            expected_version: Optional optimistic guard on the execution record.
            transition_id: Idempotency key for this operation.

        Returns:
            The durable boundary record.

        Raises:
            EntityNotFoundError: If execution/attempt is not durably recorded.
            InvalidStateError: If the execution is terminal or the attempt is
                no longer in flight.
            VersionConflictError: If ``expected_version`` is stale.
        """
        eid = self._as_uuid(execution_id, what="execution_id")
        explicit_attempt = (
            self._as_uuid(attempt_id, what="attempt_id") if attempt_id is not None else None
        )
        cp_id = (
            self._as_uuid(checkpoint_id, what="checkpoint_id")
            if checkpoint_id is not None
            else uuid.uuid4()
        )
        with self._persistence.transaction():
            execution = self.get_execution(eid)
            if is_execution_terminal(execution.status):
                raise InvalidStateError(
                    f"Cannot record a boundary for terminal execution {eid}",
                    details={"execution_id": str(eid), "status": execution.status.value},
                )
            if expected_version is not None and execution.version != expected_version:
                raise VersionConflictError(
                    f"Version conflict for execution {eid}: expected"
                    f" {expected_version}, stored {execution.version}",
                    details={
                        "execution_id": str(eid),
                        "expected_version": expected_version,
                        "stored_version": execution.version,
                    },
                )
            attempt = self._resolve_attempt(
                execution, explicit_attempt, require_started=True
            )
            sequence = (execution.last_checkpoint_sequence or 0) + 1
            checkpoint = ExecutionCheckpointState(
                checkpoint_id=cp_id,
                execution_id=eid,
                attempt_id=attempt.attempt_id,
                attempt_number=attempt.attempt_number,
                workflow_id=execution.workflow_id,
                task_id=execution.task_id,
                sequence=sequence,
                label=label,
                status=execution.status,
                boundary_state=dict(boundary_state or {}),
                previous_checkpoint_id=execution.last_checkpoint_id,
                created_by=created_by,
                metadata=dict(metadata or {}),
            )
            self._store_state(
                EntityType.EXECUTION_CHECKPOINT, cp_id, checkpoint, expected_version=None
            )
            self._record_transition(
                EntityType.EXECUTION_CHECKPOINT,
                cp_id,
                _CREATED_FROM_STATE,
                "committed",
                actor=created_by,
                metadata={
                    "operation": "checkpoint.committed",
                    "execution_id": str(eid),
                    "attempt_id": str(attempt.attempt_id),
                    "attempt_number": attempt.attempt_number,
                    "sequence": sequence,
                    "label": label,
                    "previous_checkpoint_id": (
                        str(checkpoint.previous_checkpoint_id)
                        if checkpoint.previous_checkpoint_id
                        else None
                    ),
                },
                transition_id=_op_transition_id(transition_id, f"checkpoint-{sequence}"),
            )

            attempt_updated = self._bump(
                attempt,
                last_checkpoint_id=cp_id,
                last_checkpoint_sequence=sequence,
            )
            self._store_state(
                EntityType.EXECUTION_ATTEMPT,
                attempt.attempt_id,
                attempt_updated,
                expected_version=attempt.version,
            )
            execution_updated = self._bump(
                execution,
                last_checkpoint_id=cp_id,
                last_checkpoint_sequence=sequence,
            )
            self._store_state(
                EntityType.EXECUTION,
                eid,
                execution_updated,
                expected_version=execution.version,
            )
            return checkpoint

    def complete_attempt(
        self,
        execution_id: uuid.UUID | str,
        *,
        attempt_id: uuid.UUID | str | None = None,
        result: dict[str, Any] | None = None,
        worker_id: str | None = None,
        expected_version: int | None = None,
        transition_id: uuid.UUID | None = None,
    ) -> ExecutionState:
        """Commit success of the current attempt *and* the execution at once.

        Attempt completion and execution completion are persisted in one
        transaction: it is impossible for durable state to say "attempt
        completed" while the execution still says "running".

        The operation is replay-safe: replaying it after the commit returns the
        already-committed state and writes nothing.

        Args:
            execution_id: The canonical execution ID.
            attempt_id: Attempt to complete (defaults to the current attempt).
            result: Structured outcome summary (never opaque objects).
            worker_id: Worker that produced the outcome, when known.
            expected_version: Optional optimistic guard on the execution record.
            transition_id: Idempotency key for this operation.

        Returns:
            The durable execution record after completion.
        """

        eid = self._as_uuid(execution_id, what="execution_id")
        explicit_attempt = (
            self._as_uuid(attempt_id, what="attempt_id") if attempt_id is not None else None
        )
        with self._persistence.transaction():
            execution = self.get_execution(eid)
            attempt = self._resolve_attempt(execution, explicit_attempt)
            if (
                attempt.status == AttemptStatus.COMPLETED
                and execution.status == ExecutionStatus.COMPLETED
            ):
                return execution
            if expected_version is not None and execution.version != expected_version:
                raise VersionConflictError(
                    f"Version conflict for execution {eid}: expected"
                    f" {expected_version}, stored {execution.version}",
                    details={
                        "execution_id": str(eid),
                        "expected_version": expected_version,
                        "stored_version": execution.version,
                    },
                )
            self._require(
                validate_attempt_transition(attempt.status, AttemptStatus.COMPLETED),
                what=f"attempt {attempt.attempt_number} -> completed",
            )
            self._require(
                validate_execution_transition(execution.status, ExecutionStatus.COMPLETED),
                what="execution -> completed",
            )
            completed_at = _now()
            attempt_updated = self._bump(
                attempt,
                status=AttemptStatus.COMPLETED,
                completed_at=completed_at,
                result=dict(result or {}),
                worker_id=worker_id or attempt.worker_id,
            )
            self._store_state(
                EntityType.EXECUTION_ATTEMPT,
                attempt.attempt_id,
                attempt_updated,
                expected_version=attempt.version,
            )
            self._record_transition(
                EntityType.EXECUTION_ATTEMPT,
                attempt.attempt_id,
                AttemptStatus.STARTED.value,
                AttemptStatus.COMPLETED.value,
                actor=self._owner_id,
                metadata={
                    "operation": "attempt.completed",
                    "execution_id": str(eid),
                    "attempt_number": attempt.attempt_number,
                    "last_checkpoint_sequence": execution.last_checkpoint_sequence,
                },
                transition_id=_op_transition_id(transition_id, "attempt-completed"),
            )
            execution_updated = self._bump(
                execution,
                status=ExecutionStatus.COMPLETED,
                completed_at=completed_at,
                failure=None,
                recoverable=False,
                current_attempt_id=attempt.attempt_id,
                current_attempt_number=attempt.attempt_number,
            )
            self._store_state(
                EntityType.EXECUTION,
                eid,
                execution_updated,
                expected_version=execution.version,
            )
            self._record_transition(
                EntityType.EXECUTION,
                eid,
                ExecutionStatus.RUNNING.value,
                ExecutionStatus.COMPLETED.value,
                actor=self._owner_id,
                metadata={
                    "operation": "execution.completed",
                    "attempt_id": str(attempt.attempt_id),
                    "attempt_number": attempt.attempt_number,
                    "last_checkpoint_sequence": execution.last_checkpoint_sequence,
                },
                transition_id=_op_transition_id(transition_id, "execution-completed"),
            )
            return execution_updated

    def fail_attempt(
        self,
        execution_id: uuid.UUID | str,
        *,
        attempt_id: uuid.UUID | str | None = None,
        error_code: str | None = None,
        error_message: str = "",
        retryable: bool = True,
        source: FailureSource = FailureSource.INTERNAL,
        severity: FailureSeverity = FailureSeverity.ERROR,
        result: dict[str, Any] | None = None,
        worker_id: str | None = None,
        expected_version: int | None = None,
        transition_id: uuid.UUID | None = None,
    ) -> ExecutionState:
        """Commit failure of the current attempt.

        The attempt is always durably recorded as ``failed``. The execution is
        recorded as ``failed`` only when no retry remains (``retryable=False``);
        a retryable failure leaves the execution ``running`` so that the next
        attempt continues the *same* logical execution.

        Replaying the operation after the commit returns the committed state
        and writes nothing.

        Args:
            execution_id: The canonical execution ID.
            attempt_id: Attempt that failed (defaults to the current attempt).
            error_code: Machine-readable failure code.
            error_message: Human-readable failure message.
            retryable: Whether another attempt may follow.
            source: Failure source classification.
            severity: Failure severity classification.
            result: Structured outcome summary.
            worker_id: Worker that failed, when known.
            expected_version: Optional optimistic guard on the execution record.
            transition_id: Idempotency key for this operation.

        Returns:
            The durable execution record after the failure was committed.
        """
        eid = self._as_uuid(execution_id, what="execution_id")
        explicit_attempt = (
            self._as_uuid(attempt_id, what="attempt_id") if attempt_id is not None else None
        )
        message = error_message or error_code or "Attempt failed"
        target_status = ExecutionStatus.RUNNING if retryable else ExecutionStatus.FAILED
        with self._persistence.transaction():
            execution = self.get_execution(eid)
            attempt = self._resolve_attempt(execution, explicit_attempt)
            if attempt.status == AttemptStatus.FAILED and execution.status == target_status:
                return execution
            if expected_version is not None and execution.version != expected_version:
                raise VersionConflictError(
                    f"Version conflict for execution {eid}: expected"
                    f" {expected_version}, stored {execution.version}",
                    details={
                        "execution_id": str(eid),
                        "expected_version": expected_version,
                        "stored_version": execution.version,
                    },
                )
            self._require(
                validate_attempt_transition(attempt.status, AttemptStatus.FAILED),
                what=f"attempt {attempt.attempt_number} -> failed",
            )
            if target_status != execution.status:
                self._require(
                    validate_execution_transition(execution.status, target_status),
                    what=f"execution -> {target_status.value}",
                )

            failed_at = _now()
            failure = FailureRecord(
                source=source,
                severity=severity,
                recoverability=(
                    FailureRecoverability.RECOVERABLE
                    if retryable
                    else FailureRecoverability.NON_RECOVERABLE
                ),
                error_code=error_code,
                error_message=message,
                occurred_at=failed_at,
                checkpoint_id=execution.last_checkpoint_id,
            )
            attempt_updated = self._bump(
                attempt,
                status=AttemptStatus.FAILED,
                completed_at=failed_at,
                failure=failure,
                result=dict(result or {}),
                worker_id=worker_id or attempt.worker_id,
            )
            self._store_state(
                EntityType.EXECUTION_ATTEMPT,
                attempt.attempt_id,
                attempt_updated,
                expected_version=attempt.version,
            )
            self._record_transition(
                EntityType.EXECUTION_ATTEMPT,
                attempt.attempt_id,
                AttemptStatus.STARTED.value,
                AttemptStatus.FAILED.value,
                actor=self._owner_id,
                metadata={
                    "operation": "attempt.failed",
                    "execution_id": str(eid),
                    "attempt_number": attempt.attempt_number,
                    "error_code": error_code,
                    "retryable": retryable,
                    "last_checkpoint_sequence": execution.last_checkpoint_sequence,
                },
                transition_id=_op_transition_id(transition_id, "attempt-failed"),
            )
            updates: dict[str, Any] = {
                "failure": failure,
                "recoverable": retryable,
                "current_attempt_id": attempt.attempt_id,
                "current_attempt_number": attempt.attempt_number,
            }
            if target_status == ExecutionStatus.FAILED:
                updates["status"] = ExecutionStatus.FAILED
                updates["completed_at"] = failed_at
            execution_updated = self._bump(execution, **updates)
            self._store_state(
                EntityType.EXECUTION,
                eid,
                execution_updated,
                expected_version=execution.version,
            )
            if target_status == ExecutionStatus.FAILED:
                self._record_transition(
                    EntityType.EXECUTION,
                    eid,
                    ExecutionStatus.RUNNING.value,
                    ExecutionStatus.FAILED.value,
                    actor=self._owner_id,
                    metadata={
                        "operation": "execution.failed",
                        "attempt_id": str(attempt.attempt_id),
                        "attempt_number": attempt.attempt_number,
                        "error_code": error_code,
                    },
                    transition_id=_op_transition_id(transition_id, "execution-failed"),
                )
            return execution_updated

    def cancel_execution(
        self,
        execution_id: uuid.UUID | str,
        *,
        reason: str | None = None,
        expected_version: int | None = None,
        transition_id: uuid.UUID | None = None,
    ) -> ExecutionState:
        """Durably cancel an execution and its in-flight attempt (if any).

        Cancellation is a *deliberate* terminal transition: it is never used to
        represent a crashed process (that is ``interrupted``).
        """
        eid = self._as_uuid(execution_id, what="execution_id")
        with self._persistence.transaction():
            execution = self.get_execution(eid)
            if execution.status == ExecutionStatus.CANCELLED:
                return execution
            if expected_version is not None and execution.version != expected_version:
                raise VersionConflictError(
                    f"Version conflict for execution {eid}: expected"
                    f" {expected_version}, stored {execution.version}",
                    details={
                        "execution_id": str(eid),
                        "expected_version": expected_version,
                        "stored_version": execution.version,
                    },
                )
            self._require(
                validate_execution_transition(execution.status, ExecutionStatus.CANCELLED),
                what="execution -> cancelled",
            )
            cancelled_at = _now()
            active = self.get_active_attempt(eid)
            if active is not None:
                self._require(
                    validate_attempt_transition(active.status, AttemptStatus.CANCELLED),
                    what=f"attempt {active.attempt_number} -> cancelled",
                )
                active_updated = self._bump(
                    active, status=AttemptStatus.CANCELLED, completed_at=cancelled_at
                )
                self._store_state(
                    EntityType.EXECUTION_ATTEMPT,
                    active.attempt_id,
                    active_updated,
                    expected_version=active.version,
                )
                self._record_transition(
                    EntityType.EXECUTION_ATTEMPT,
                    active.attempt_id,
                    AttemptStatus.STARTED.value,
                    AttemptStatus.CANCELLED.value,
                    actor=self._owner_id,
                    metadata={
                        "operation": "attempt.cancelled",
                        "execution_id": str(eid),
                        "attempt_number": active.attempt_number,
                        "reason": reason,
                    },
                    transition_id=_op_transition_id(transition_id, "attempt-cancelled"),
                )
            execution_updated = self._bump(
                execution,
                status=ExecutionStatus.CANCELLED,
                completed_at=cancelled_at,
                recoverable=False,
                failure=FailureRecord(
                    source=FailureSource.INTERNAL,
                    severity=FailureSeverity.WARNING,
                    recoverability=FailureRecoverability.NON_RECOVERABLE,
                    error_code="EXECUTION_CANCELLED",
                    error_message=reason or "Execution cancelled",
                    occurred_at=cancelled_at,
                    checkpoint_id=execution.last_checkpoint_id,
                ),
            )
            self._store_state(
                EntityType.EXECUTION,
                eid,
                execution_updated,
                expected_version=execution.version,
            )
            self._record_transition(
                EntityType.EXECUTION,
                eid,
                execution.status.value,
                ExecutionStatus.CANCELLED.value,
                actor=self._owner_id,
                metadata={"operation": "execution.cancelled", "reason": reason},
                transition_id=_op_transition_id(transition_id, "execution-cancelled"),
            )
            return execution_updated

    def mark_interrupted(
        self,
        execution_id: uuid.UUID | str,
        *,
        reason: str | None = None,
        expected_version: int | None = None,
        transition_id: uuid.UUID | None = None,
    ) -> ExecutionState:
        """Classify an execution as ``interrupted`` (recoverable), never failed.

        This is the durable representation of "the process that owned this
        execution is gone while the work unit was in flight". It records the
        *truth* (in flight, not completed) and sets ``recoverable`` so that
        18-J.3 can resume it deliberately.
        """
        eid = self._as_uuid(execution_id, what="execution_id")
        with self._persistence.transaction():
            execution = self.get_execution(eid)
            if execution.status == ExecutionStatus.INTERRUPTED:
                return execution
            if execution.status == ExecutionStatus.CREATED:
                # Nothing was ever started, so there is nothing to resume.
                return self.cancel_execution(
                    eid,
                    reason=reason or "Execution never started",
                    expected_version=expected_version,
                    transition_id=transition_id,
                )
            if expected_version is not None and execution.version != expected_version:
                raise VersionConflictError(
                    f"Version conflict for execution {eid}: expected"
                    f" {expected_version}, stored {execution.version}",
                    details={
                        "execution_id": str(eid),
                        "expected_version": expected_version,
                        "stored_version": execution.version,
                    },
                )
            self._require(
                validate_execution_transition(execution.status, ExecutionStatus.INTERRUPTED),
                what="execution -> interrupted",
            )
            interrupted_at = _now()
            message = reason or "Owning process disappeared while the execution was in flight"
            active = self.get_active_attempt(eid)
            if active is not None:
                self._require(
                    validate_attempt_transition(active.status, AttemptStatus.INTERRUPTED),
                    what=f"attempt {active.attempt_number} -> interrupted",
                )
                active_updated = self._bump(
                    active, status=AttemptStatus.INTERRUPTED, completed_at=interrupted_at
                )
                self._store_state(
                    EntityType.EXECUTION_ATTEMPT,
                    active.attempt_id,
                    active_updated,
                    expected_version=active.version,
                )
                self._record_transition(
                    EntityType.EXECUTION_ATTEMPT,
                    active.attempt_id,
                    AttemptStatus.STARTED.value,
                    AttemptStatus.INTERRUPTED.value,
                    actor=self._owner_id,
                    metadata={
                        "operation": "attempt.interrupted",
                        "execution_id": str(eid),
                        "attempt_number": active.attempt_number,
                        "reason": message,
                    },
                    transition_id=_op_transition_id(transition_id, "attempt-interrupted"),
                )

            execution_updated = self._bump(
                execution,
                status=ExecutionStatus.INTERRUPTED,
                interrupted_at=interrupted_at,
                recoverable=True,
                failure=FailureRecord(
                    source=FailureSource.INTERNAL,
                    severity=FailureSeverity.ERROR,
                    recoverability=FailureRecoverability.RECOVERABLE,
                    error_code="EXECUTION_INTERRUPTED",
                    error_message=message,
                    occurred_at=interrupted_at,
                    checkpoint_id=execution.last_checkpoint_id,
                ),
            )
            self._store_state(
                EntityType.EXECUTION,
                eid,
                execution_updated,
                expected_version=execution.version,
            )
            self._record_transition(
                EntityType.EXECUTION,
                eid,
                execution.status.value,
                ExecutionStatus.INTERRUPTED.value,
                actor=self._owner_id,
                metadata={
                    "operation": "execution.interrupted",
                    "reason": message,
                    "last_checkpoint_sequence": execution.last_checkpoint_sequence,
                    "owner_id": execution.owner_id,
                },
                transition_id=_op_transition_id(transition_id, "execution-interrupted"),
            )
            return execution_updated

    def reconcile_interrupted_executions(
        self, *, reason: str | None = None
    ) -> list[ExecutionState]:
        """Mark executions abandoned by a dead process as interrupted.

        This is an **explicit** supervisor action, never an automatic one: J.2
        must not resume work, and it must not silently rewrite history on
        startup. A later phase (18-J.3) calls this once and then decides
        deliberately whether and how to resume what it finds.

        Executions owned by *this* process are left untouched (they are alive),
        and executions with no recorded owner are not attributed.

        Returns:
            The executions whose durable status changed in this call.
        """
        reconciled: list[ExecutionState] = []
        for execution in self.find_abandoned_executions():
            if execution.status == ExecutionStatus.INTERRUPTED:
                continue
            message = reason or (
                f"Execution was owned by {execution.owner_id!r}, which is not this"
                f" process ({self._owner_id!r})"
            )
            reconciled.append(self.mark_interrupted(execution.execution_id, reason=message))
        return reconciled
