"""Durable Idempotency Store — canonical operation identity, atomic claims and side-effect safety.

Phase 18-J (Durable Execution + Resume + Idempotency), step 18-J.4
------------------------------------------------------------------
This module closes the side-effect duplication gap after J.3 workflow resume:
A task or attempt can survive process crashes and resume, but any external
side effect (e.g. HTTP API request, payment call, external tool invocation,
or external mutation) performed before the crash could be executed again
during Attempt N+1 unless protected by durable idempotency.

Authoritative Foundation:
-------------------------
All idempotency records are stored through the runtime's single
:class:`~autoforge_runtime.persistence.PersistenceLayer` (SQLite in WAL mode
with BEGIN IMMEDIATE transactions). No second database, no Redis, no Kafka,
no Temporal.

Guarantees & Semantics:
-----------------------
1. Logical Operation Identity:
   Separated from physical execution attempt identity. A physical retry of an
   execution (Attempt 1 -> Attempt 2) derives the EXACT SAME logical
   idempotency key for the same logical operation.
2. Request Fingerprinting:
   Deterministic SHA-256 hash of canonicalized JSON request payloads. Reusing
   the same idempotency key with a differing payload is rejected with a
   deterministic conflict error.
3. Atomic Claim Protocol:
   Atomic SQLite transaction guarantees that only ONE concurrent process
   obtains the side-effect claim. The other observer is informed of the running
   or completed state.
4. Completion Durability:
   State is durably committed before observational events announce completion.
   Completed operations return their durable prior result without re-executing.
5. Interruption & Ambiguity:
   Operations interrupted in-flight against external providers without idempotency
   support are explicitly marked as ambiguous rather than falsely claiming
   exactly-once execution.
"""

from __future__ import annotations

import copy
import hashlib
import json
import logging
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
    EntityType,
    IdempotentOperationState,
    OPERATION_RECORD_VERSION,
    OperationStatus,
    StateTransition,
)
from autoforge_runtime.persistence import PersistenceLayer
from autoforge_runtime.validation import (
    is_operation_recoverable,
    is_operation_terminal,
    validate_operation_transition,
)

logger = logging.getLogger("autoforge.runtime.idempotency")

#: Namespace UUID used to derive canonical UUIDv5 operation identifiers.
IDEMPOTENT_OPERATION_NAMESPACE = uuid.UUID("a74f8804-6330-4be6-8e5f-fcf138e07920")

#: Neutral state label used as ``from_state`` when a record is first created.
_CREATED_FROM_STATE = "none"

#: Sensitive field names stripped or masked in diagnostic metadata.
SENSITIVE_FIELD_NAMES = frozenset(
    {
        "authorization",
        "api_key",
        "apikey",
        "token",
        "access_token",
        "refresh_token",
        "password",
        "secret",
        "client_secret",
        "private_key",
    }
)


# ── Exceptions ───────────────────────────────────────────────────────────


class IdempotencyError(PersistenceError):
    """Base exception for all idempotency protocol errors."""


class FingerprintConflictError(IdempotencyError):
    """Raised when an idempotency key is reused with a different request payload."""


class ConcurrentOperationError(IdempotencyError):
    """Raised when an operation is currently claimed and running by another active process."""


class AmbiguousSideEffectError(IdempotencyError):
    """Raised when an interrupted operation cannot guarantee external completion status."""


class OperationFailedError(IdempotencyError):
    """Raised when an operation previously failed and its retry policy rejects execution."""


# ── Canonical Key Derivation & Identification ─────────────────────────────


def default_operation_owner_id() -> str:
    """Return the identity of the current process (``host:pid``)."""
    return f"{socket.gethostname()}:{os.getpid()}"


def _now() -> datetime:
    """Return the current timezone-aware UTC timestamp."""
    return datetime.now(timezone.utc)


def _op_transition_id(operation_id: uuid.UUID | None, suffix: str) -> uuid.UUID:
    """Derive a deterministic history-row ID from an operation ID."""
    if operation_id is None:
        return uuid.uuid4()
    return uuid.uuid5(operation_id, suffix)


def derive_idempotency_key(
    execution_id: uuid.UUID | str | None = None,
    operation_type: str = "generic",
    operation_name: str = "",
    step_or_call_id: Any = None,
    workflow_id: uuid.UUID | str | None = None,
    task_id: str | None = None,
) -> str:
    """Derive the canonical logical idempotency key for an operation.

    CRITICAL RULE:
    The logical key must NOT contain ``attempt_id`` or ``attempt_number``.
    The same logical side effect across retries must resolve to the EXACT SAME
    idempotency key.

    Derivation rules:
    - Workflow task context: ``workflow:{wf_id}:task:{task_id}:op:{operation_name}[:{step}]``
    - Execution context: ``exec:{exec_id}:{operation_type}:{operation_name}[:{step}]``
    - Standalone context: ``op:{operation_type}:{operation_name}[:{step}]``
    """
    step_suffix = f":{step_or_call_id}" if step_or_call_id is not None and str(step_or_call_id).strip() != "" else ""

    if workflow_id is not None and task_id:
        wf_uuid = uuid.UUID(str(workflow_id))
        return f"workflow:{wf_uuid}:task:{task_id}:op:{operation_name}{step_suffix}"

    if execution_id is not None:
        ex_uuid = uuid.UUID(str(execution_id))
        return f"exec:{ex_uuid}:{operation_type}:{operation_name}{step_suffix}"

    clean_type = operation_type or "generic"
    clean_name = operation_name or "default"
    return f"op:{clean_type}:{clean_name}{step_suffix}"


def derive_task_idempotency_key(
    workflow_id: uuid.UUID | str,
    task_id: str,
    operation_name: str,
    step_or_call_id: Any = None,
) -> str:
    """Convenience helper to derive a workflow-task-scoped idempotency key."""
    return derive_idempotency_key(
        workflow_id=workflow_id,
        task_id=task_id,
        operation_name=operation_name,
        step_or_call_id=step_or_call_id,
    )


def operation_id_for_key(idempotency_key: str) -> uuid.UUID:
    """Derive the canonical UUIDv5 operation ID from its logical idempotency key."""
    if not idempotency_key or not idempotency_key.strip():
        raise ValidationError("idempotency_key must not be empty")
    return uuid.uuid5(IDEMPOTENT_OPERATION_NAMESPACE, idempotency_key.strip())


# ── Deterministic Request Fingerprinting & Sanitization ──────────────────


def _canonicalize_value(val: Any) -> Any:
    """Recursively convert values into canonical deterministic JSON primitives."""
    if val is None or isinstance(val, (bool, int, str)):
        return val
    if isinstance(val, float):
        # Format floats with high precision but stable representation
        return float(f"{val:.12g}")
    if isinstance(val, datetime):
        if val.tzinfo is None:
            val = val.replace(tzinfo=timezone.utc)
        return val.astimezone(timezone.utc).isoformat()
    if isinstance(val, uuid.UUID):
        return str(val)
    if isinstance(val, bytes):
        return val.hex()
    if isinstance(val, dict):
        return {str(k): _canonicalize_value(v) for k, v in sorted(val.items())}
    if isinstance(val, (list, tuple)):
        return [_canonicalize_value(item) for item in val]
    if isinstance(val, (set, frozenset)):
        canonical_items = [_canonicalize_value(item) for item in val]
        return sorted(canonical_items, key=lambda x: json.dumps(x, sort_keys=True))
    # Fallback to string representation for any other custom types
    return str(val)


def compute_request_fingerprint(payload: Any) -> str:
    """Compute a deterministic SHA-256 fingerprint for a request payload.

    Canonicalizes keys recursively, serializes with sorted keys and tight
    separators, and returns ``sha256:<hexdigest>``.
    """
    canonical = _canonicalize_value(payload)
    encoded = json.dumps(
        canonical,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    digest = hashlib.sha256(encoded).hexdigest()
    return f"sha256:{digest}"


def sanitize_payload(payload: Any) -> Any:
    """Return a deep copy of ``payload`` with sensitive values masked."""
    if isinstance(payload, dict):
        sanitized = {}
        for k, v in payload.items():
            if str(k).lower() in SENSITIVE_FIELD_NAMES:
                sanitized[k] = "[REDACTED]"
            else:
                sanitized[k] = sanitize_payload(v)
        return sanitized
    if isinstance(payload, list):
        return [sanitize_payload(x) for x in payload]
    return payload


# ── Claim Result ─────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ClaimResult:
    """Outcome of attempting to claim an idempotent operation."""

    claimed: bool
    """True if caller has acquired the exclusive right to execute the side effect."""

    status: OperationStatus
    """Current durable status of the operation."""

    operation_id: uuid.UUID
    """Canonical durable identifier."""

    idempotency_key: str
    """Logical idempotency key."""

    cached_result: dict[str, Any] | None = None
    """Durable result from previous execution when already COMPLETED."""

    state: IdempotentOperationState | None = None
    """The authoritative durable state record."""

    resumed: bool = False
    """True if this claim resumed an interrupted or failed operation."""

    is_ambiguous: bool = False
    """True if operation was previously interrupted without provider idempotency."""


# ── Durable Idempotency Store ────────────────────────────────────────────


class DurableIdempotencyStore:
    """Durable store and atomic claim protocol for idempotent side-effecting operations.

    Args:
        persistence: The runtime persistence layer (backed by SQLite).
        owner_id: Process identity; defaults to ``host:pid``.
    """

    def __init__(
        self,
        persistence: PersistenceLayer,
        *,
        owner_id: str | None = None,
    ) -> None:
        self._persistence = persistence
        self._owner_id = owner_id or default_operation_owner_id()

    @property
    def persistence(self) -> PersistenceLayer:
        """The underlying runtime persistence layer."""
        return self._persistence

    @property
    def owner_id(self) -> str:
        """The identity of this store instance."""
        return self._owner_id

    # ── Internal Helpers ─────────────────────────────────────────────────

    def _bump(self, state: IdempotentOperationState, **updates: Any) -> IdempotentOperationState:
        """Return a copy of ``state`` with version incremented and updated_at refreshed."""
        data = state.model_dump()
        data["version"] = state.version + 1
        data["updated_at"] = _now()
        data.update(updates)
        return IdempotentOperationState.model_validate(data)

    def _store_state(
        self,
        operation: IdempotentOperationState,
        *,
        expected_version: int | None = None,
    ) -> None:
        """Persist operation state through the runtime persistence layer."""
        self._persistence.write_state(
            EntityType.IDEMPOTENT_OPERATION,
            operation.operation_id,
            operation,
            expected_version=expected_version,
        )

    def _record_transition(
        self,
        operation_id: uuid.UUID,
        from_state: str,
        to_state: str,
        *,
        actor: str,
        metadata: dict[str, Any] | None = None,
        transition_id: uuid.UUID | None = None,
    ) -> None:
        """Record an immutable history audit row."""
        transition = StateTransition(
            transition_id=transition_id or uuid.uuid4(),
            entity_type=EntityType.IDEMPOTENT_OPERATION,
            entity_id=operation_id,
            from_state=from_state,
            to_state=to_state,
            actor=actor,
            timestamp=_now(),
            metadata=metadata or {},
        )
        self._persistence.write_history(transition)

    def _is_owner_alive(self, owner_id: str | None) -> bool:
        """Check if the recorded owner process is still running on this host."""
        if not owner_id:
            return False
        parts = owner_id.split(":")
        if len(parts) != 2:
            return False
        host, pid_str = parts[0], parts[1]
        try:
            pid = int(pid_str)
        except ValueError:
            return False

        current_host = socket.gethostname()
        if host != current_host:
            # Different host: cannot probe via local signal. Assume alive if unknown.
            return True

        if pid == os.getpid():
            return True

        try:
            os.kill(pid, 0)
            return True
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        except OSError:
            return False

    # ── Read API ─────────────────────────────────────────────────────────

    def get_operation(self, operation_id: uuid.UUID | str) -> IdempotentOperationState:
        """Fetch an operation by ID. Raises EntityNotFoundError if absent."""
        op_uuid = uuid.UUID(str(operation_id))
        entity = self._persistence.read_state(EntityType.IDEMPOTENT_OPERATION, op_uuid)
        if not isinstance(entity, IdempotentOperationState):
            raise PersistenceError(
                f"Expected IdempotentOperationState for {op_uuid}, got {type(entity).__name__}"
            )
        return entity

    def try_get_operation(self, operation_id: uuid.UUID | str) -> IdempotentOperationState | None:
        """Fetch an operation by ID, returning None if absent."""
        try:
            return self.get_operation(operation_id)
        except EntityNotFoundError:
            return None

    def get_operation_by_key(self, idempotency_key: str) -> IdempotentOperationState | None:
        """Lookup an operation by its logical idempotency key."""
        op_id = operation_id_for_key(idempotency_key)
        return self.try_get_operation(op_id)

    def list_operations(self) -> list[IdempotentOperationState]:
        """List all idempotent operations in storage."""
        items = self._persistence.read_all(EntityType.IDEMPOTENT_OPERATION)
        return [item for item in items if isinstance(item, IdempotentOperationState)]

    def list_operations_for_execution(
        self, execution_id: uuid.UUID | str
    ) -> list[IdempotentOperationState]:
        """List all idempotent operations linked to a logical execution."""
        ex_uuid = uuid.UUID(str(execution_id))
        return [op for op in self.list_operations() if op.execution_id == ex_uuid]

    def list_operations_for_workflow(
        self, workflow_id: uuid.UUID | str
    ) -> list[IdempotentOperationState]:
        """List all idempotent operations linked to a workflow instance."""
        wf_uuid = uuid.UUID(str(workflow_id))
        return [op for op in self.list_operations() if op.workflow_id == wf_uuid]

    def list_interrupted_operations(self) -> list[IdempotentOperationState]:
        """List all operations currently in INTERRUPTED status."""
        return [op for op in self.list_operations() if op.status == OperationStatus.INTERRUPTED]

    def list_active_operations(self) -> list[IdempotentOperationState]:
        """List all operations currently in RUNNING status."""
        return [op for op in self.list_operations() if op.status == OperationStatus.RUNNING]

    # ── Durable Claim Protocol ───────────────────────────────────────────

    def claim_operation(
        self,
        idempotency_key: str,
        *,
        request_payload: Any = None,
        request_fingerprint: str | None = None,
        operation_id: uuid.UUID | str | None = None,
        execution_id: uuid.UUID | str | None = None,
        attempt_id: uuid.UUID | str | None = None,
        workflow_id: uuid.UUID | str | None = None,
        task_id: str | None = None,
        operation_type: str = "generic",
        supports_provider_idempotency: bool = True,
        provider_idempotency_key: str | None = None,
        allow_failed_retry: bool = True,
        metadata: dict[str, Any] | None = None,
        transition_id: uuid.UUID | None = None,
    ) -> ClaimResult:
        """Atomically claim an idempotent operation for side-effect execution.

        Transactionally checks durable state:
        - If ABSENT: creates record in RUNNING status and returns ``claimed=True``.
        - If COMPLETED: returns ``claimed=False`` with cached durable result.
        - If RUNNING:
            * If current owner alive: raises ``ConcurrentOperationError``.
            * If owner process is dead: marks as INTERRUPTED and recovers if policy allows.
        - If INTERRUPTED:
            * If ``supports_provider_idempotency=True``: reclaims into RUNNING and returns ``claimed=True, resumed=True``.
            * If ``supports_provider_idempotency=False``: raises ``AmbiguousSideEffectError``.
        - If FAILED:
            * If ``allow_failed_retry=True``: retries into RUNNING with incremented retry count.
            * If not retryable: raises ``OperationFailedError``.

        Guarantees:
        - Reusing key with different request fingerprint raises ``FingerprintConflictError``.
        - Two concurrent workers will never both receive ``claimed=True``.
        """
        canonical_op_id = (
            uuid.UUID(str(operation_id))
            if operation_id is not None
            else operation_id_for_key(idempotency_key)
        )
        canonical_exec_id = uuid.UUID(str(execution_id)) if execution_id is not None else None
        canonical_att_id = uuid.UUID(str(attempt_id)) if attempt_id is not None else None
        canonical_wf_id = uuid.UUID(str(workflow_id)) if workflow_id is not None else None

        fingerprint = (
            request_fingerprint
            if request_fingerprint is not None
            else compute_request_fingerprint(request_payload)
        )

        with self._persistence.transaction():
            existing = self.try_get_operation(canonical_op_id)

            if existing is None:
                # ── Absent: Atomically create in RUNNING state ────────────────
                new_state = IdempotentOperationState(
                    operation_id=canonical_op_id,
                    idempotency_key=idempotency_key,
                    execution_id=canonical_exec_id,
                    attempt_id=canonical_att_id,
                    workflow_id=canonical_wf_id,
                    task_id=task_id,
                    operation_type=operation_type,
                    status=OperationStatus.RUNNING,
                    request_fingerprint=fingerprint,
                    owner_id=self._owner_id,
                    supports_provider_idempotency=supports_provider_idempotency,
                    provider_idempotency_key=provider_idempotency_key or idempotency_key,
                    started_at=_now(),
                    metadata=metadata or {},
                )
                self._store_state(new_state)
                self._record_transition(
                    canonical_op_id,
                    _CREATED_FROM_STATE,
                    OperationStatus.RUNNING.value,
                    actor=self._owner_id,
                    metadata={
                        "action": "operation.claimed",
                        "idempotency_key": idempotency_key,
                        "fingerprint": fingerprint,
                        "execution_id": str(canonical_exec_id) if canonical_exec_id else None,
                        "attempt_id": str(canonical_att_id) if canonical_att_id else None,
                    },
                    transition_id=_op_transition_id(transition_id, "operation-claimed"),
                )
                return ClaimResult(
                    claimed=True,
                    status=OperationStatus.RUNNING,
                    operation_id=canonical_op_id,
                    idempotency_key=idempotency_key,
                    state=new_state,
                )

            # ── Fingerprint Verification ─────────────────────────────────────
            if existing.request_fingerprint != fingerprint:
                self._record_transition(
                    canonical_op_id,
                    existing.status.value,
                    existing.status.value,
                    actor=self._owner_id,
                    metadata={
                        "action": "fingerprint_conflict_observed",
                        "idempotency_key": idempotency_key,
                        "expected_fingerprint": existing.request_fingerprint,
                        "incoming_fingerprint": fingerprint,
                    },
                    transition_id=_op_transition_id(transition_id, "fingerprint-conflict"),
                )
                raise FingerprintConflictError(
                    f"Idempotency key {idempotency_key!r} already exists with differing "
                    f"request fingerprint ({existing.request_fingerprint} != {fingerprint}). "
                    f"Reusing an idempotency key with a changed request payload is rejected.",
                    details={
                        "idempotency_key": idempotency_key,
                        "existing_fingerprint": existing.request_fingerprint,
                        "incoming_fingerprint": fingerprint,
                        "operation_id": str(canonical_op_id),
                    },
                )

            # ── COMPLETED: return durable cached result ──────────────────────
            if existing.status == OperationStatus.COMPLETED:
                self._record_transition(
                    canonical_op_id,
                    OperationStatus.COMPLETED.value,
                    OperationStatus.COMPLETED.value,
                    actor=self._owner_id,
                    metadata={
                        "action": "duplicate_request_observed",
                        "idempotency_key": idempotency_key,
                        "cached_completed_at": (
                            existing.completed_at.isoformat() if existing.completed_at else None
                        ),
                    },
                    transition_id=_op_transition_id(transition_id, "duplicate-request"),
                )
                return ClaimResult(
                    claimed=False,
                    status=OperationStatus.COMPLETED,
                    operation_id=canonical_op_id,
                    idempotency_key=idempotency_key,
                    cached_result=existing.result,
                    state=existing,
                )

            # ── RUNNING: reject concurrent duplicate execution ───────────────
            if existing.status == OperationStatus.RUNNING:
                raise ConcurrentOperationError(
                    f"Operation {idempotency_key!r} is currently RUNNING by owner "
                    f"{existing.owner_id!r}. Duplicate execution rejected.",
                    details={
                        "idempotency_key": idempotency_key,
                        "operation_id": str(canonical_op_id),
                        "owner_id": existing.owner_id,
                        "status": existing.status.value,
                    },
                )

            # ── INTERRUPTED: controlled recovery / ambiguous handling ────────
            if existing.status == OperationStatus.INTERRUPTED:
                if not existing.supports_provider_idempotency:
                    raise AmbiguousSideEffectError(
                        f"Operation {idempotency_key!r} was interrupted during execution against "
                        f"an external provider that does not support idempotency keys. "
                        f"Completion status is ambiguous and cannot be safely re-executed.",
                        details={
                            "idempotency_key": idempotency_key,
                            "operation_id": str(canonical_op_id),
                            "supports_provider_idempotency": False,
                            "is_ambiguous": True,
                        },
                    )

                # External provider supports idempotency: safe to resume/retry with same key
                resumed = self._bump(
                    existing,
                    status=OperationStatus.RUNNING,
                    owner_id=self._owner_id,
                    attempt_id=canonical_att_id or existing.attempt_id,
                    interrupted_at=None,
                    started_at=_now(),
                    retry_count=existing.retry_count + 1,
                )
                self._store_state(resumed, expected_version=existing.version)
                self._record_transition(
                    canonical_op_id,
                    OperationStatus.INTERRUPTED.value,
                    OperationStatus.RUNNING.value,
                    actor=self._owner_id,
                    metadata={
                        "action": "operation.recovered",
                        "idempotency_key": idempotency_key,
                        "resume": True,
                        "retry_count": resumed.retry_count,
                    },
                    transition_id=_op_transition_id(transition_id, f"operation-resumed-{resumed.retry_count}"),
                )
                return ClaimResult(
                    claimed=True,
                    status=OperationStatus.RUNNING,
                    operation_id=canonical_op_id,
                    idempotency_key=idempotency_key,
                    state=resumed,
                    resumed=True,
                )

            # ── FAILED: policy-dependent retry ───────────────────────────────
            if existing.status == OperationStatus.FAILED:
                if not allow_failed_retry:
                    raise OperationFailedError(
                        f"Operation {idempotency_key!r} previously failed with code "
                        f"{existing.error_code!r}: {existing.error_message}. Retry not permitted.",
                        details={
                            "idempotency_key": idempotency_key,
                            "operation_id": str(canonical_op_id),
                            "error_code": existing.error_code,
                            "error_message": existing.error_message,
                        },
                    )

                retried = self._bump(
                    existing,
                    status=OperationStatus.RUNNING,
                    owner_id=self._owner_id,
                    attempt_id=canonical_att_id or existing.attempt_id,
                    error_code=None,
                    error_message=None,
                    started_at=_now(),
                    retry_count=existing.retry_count + 1,
                )
                self._store_state(retried, expected_version=existing.version)
                self._record_transition(
                    canonical_op_id,
                    OperationStatus.FAILED.value,
                    OperationStatus.RUNNING.value,
                    actor=self._owner_id,
                    metadata={
                        "action": "operation.retried_from_failure",
                        "idempotency_key": idempotency_key,
                        "retry_count": retried.retry_count,
                    },
                    transition_id=_op_transition_id(transition_id, f"operation-retry-{retried.retry_count}"),
                )
                return ClaimResult(
                    claimed=True,
                    status=OperationStatus.RUNNING,
                    operation_id=canonical_op_id,
                    idempotency_key=idempotency_key,
                    state=retried,
                    resumed=True,
                )

            # ── CANCELLED or other terminal state ────────────────────────────
            raise IdempotencyError(
                f"Operation {idempotency_key!r} is in terminal state {existing.status.value!r}.",
                details={
                    "idempotency_key": idempotency_key,
                    "operation_id": str(canonical_op_id),
                    "status": existing.status.value,
                },
            )

    # ── Completion & Failure ─────────────────────────────────────────────

    def complete_operation(
        self,
        operation_id: uuid.UUID | str,
        *,
        result: dict[str, Any] | None = None,
        result_reference: str | None = None,
        metadata: dict[str, Any] | None = None,
        transition_id: uuid.UUID | None = None,
        expected_version: int | None = None,
    ) -> IdempotentOperationState:
        """Commit the durable completion of an operation with its result.

        CRITICAL DURABILITY GUARANTEE:
        Must be persisted and committed before observational completion events
        are emitted.
        """
        op_uuid = uuid.UUID(str(operation_id))
        with self._persistence.transaction():
            current = self.get_operation(op_uuid)

            val_res = validate_operation_transition(current.status, OperationStatus.COMPLETED)
            if not val_res.valid:
                raise InvalidTransitionError(
                    f"Cannot complete operation {op_uuid} from status {current.status.value}: {val_res.error_message}",
                    details={"operation_id": str(op_uuid), "current_status": current.status.value},
                )

            merged_meta = dict(current.metadata)
            if metadata:
                merged_meta.update(metadata)

            updated = self._bump(
                current,
                status=OperationStatus.COMPLETED,
                result=result or {},
                result_reference=result_reference,
                completed_at=_now(),
                metadata=merged_meta,
            )
            self._store_state(
                updated,
                expected_version=expected_version if expected_version is not None else current.version,
            )
            self._record_transition(
                op_uuid,
                current.status.value,
                OperationStatus.COMPLETED.value,
                actor=self._owner_id,
                metadata={
                    "action": "operation.completed",
                    "idempotency_key": updated.idempotency_key,
                    "has_result_reference": bool(result_reference),
                },
                transition_id=_op_transition_id(transition_id, "operation-completed"),
            )
            return updated

    def fail_operation(
        self,
        operation_id: uuid.UUID | str,
        *,
        error_code: str | None = None,
        error_message: str = "",
        metadata: dict[str, Any] | None = None,
        transition_id: uuid.UUID | None = None,
        expected_version: int | None = None,
    ) -> IdempotentOperationState:
        """Commit failure of an idempotent operation."""
        op_uuid = uuid.UUID(str(operation_id))
        with self._persistence.transaction():
            current = self.get_operation(op_uuid)

            val_res = validate_operation_transition(current.status, OperationStatus.FAILED)
            if not val_res.valid:
                raise InvalidTransitionError(
                    f"Cannot fail operation {op_uuid} from status {current.status.value}: {val_res.error_message}",
                    details={"operation_id": str(op_uuid), "current_status": current.status.value},
                )

            merged_meta = dict(current.metadata)
            if metadata:
                merged_meta.update(metadata)

            updated = self._bump(
                current,
                status=OperationStatus.FAILED,
                error_code=error_code,
                error_message=error_message,
                metadata=merged_meta,
            )
            self._store_state(
                updated,
                expected_version=expected_version if expected_version is not None else current.version,
            )
            self._record_transition(
                op_uuid,
                current.status.value,
                OperationStatus.FAILED.value,
                actor=self._owner_id,
                metadata={
                    "action": "operation.failed",
                    "idempotency_key": updated.idempotency_key,
                    "error_code": error_code,
                    "error_message": error_message[:256] if error_message else None,
                },
                transition_id=_op_transition_id(transition_id, "operation-failed"),
            )
            return updated

    def cancel_operation(
        self,
        operation_id: uuid.UUID | str,
        *,
        reason: str = "",
        transition_id: uuid.UUID | None = None,
    ) -> IdempotentOperationState:
        """Cancel an idempotent operation."""
        op_uuid = uuid.UUID(str(operation_id))
        with self._persistence.transaction():
            current = self.get_operation(op_uuid)

            val_res = validate_operation_transition(current.status, OperationStatus.CANCELLED)
            if not val_res.valid:
                raise InvalidTransitionError(
                    f"Cannot cancel operation {op_uuid} from status {current.status.value}: {val_res.error_message}"
                )

            updated = self._bump(
                current,
                status=OperationStatus.CANCELLED,
                error_message=reason or "Cancelled",
            )
            self._store_state(updated, expected_version=current.version)
            self._record_transition(
                op_uuid,
                current.status.value,
                OperationStatus.CANCELLED.value,
                actor=self._owner_id,
                metadata={"action": "operation.cancelled", "reason": reason},
                transition_id=_op_transition_id(transition_id, "operation-cancelled"),
            )
            return updated

    # ── Interruption & Reconciliation ────────────────────────────────────

    def _transition_to_interrupted(
        self,
        operation: IdempotentOperationState,
        *,
        reason: str,
        transition_id: uuid.UUID | None = None,
    ) -> IdempotentOperationState:
        """Internal helper to mark an operation as INTERRUPTED."""
        is_ambiguous = not operation.supports_provider_idempotency
        ambiguity_reason = (
            "Operation interrupted while running against provider without idempotency support"
            if is_ambiguous
            else None
        )
        updated = self._bump(
            operation,
            status=OperationStatus.INTERRUPTED,
            interrupted_at=_now(),
            is_ambiguous=is_ambiguous,
            ambiguity_reason=ambiguity_reason,
            error_message=reason,
        )
        self._store_state(updated, expected_version=operation.version)
        self._record_transition(
            operation.operation_id,
            operation.status.value,
            OperationStatus.INTERRUPTED.value,
            actor=self._owner_id,
            metadata={
                "action": "operation.interrupted",
                "reason": reason,
                "is_ambiguous": is_ambiguous,
            },
            transition_id=transition_id or uuid.uuid4(),
        )
        return updated

    def mark_interrupted(
        self,
        operation_id: uuid.UUID | str,
        *,
        reason: str = "Process interrupted",
        transition_id: uuid.UUID | None = None,
    ) -> IdempotentOperationState:
        """Explicitly transition an operation to INTERRUPTED."""
        op_uuid = uuid.UUID(str(operation_id))
        with self._persistence.transaction():
            current = self.get_operation(op_uuid)
            return self._transition_to_interrupted(
                current,
                reason=reason,
                transition_id=transition_id,
            )

    def find_abandoned_operations(self) -> list[IdempotentOperationState]:
        """Return active (RUNNING) operations owned by a different process."""
        return [
            op
            for op in self.list_active_operations()
            if op.owner_id is not None and op.owner_id != self._owner_id
        ]

    def reconcile_interrupted_operations(
        self,
        target_owner_id: str | None = None,
        *,
        reason: str | None = None,
    ) -> list[IdempotentOperationState]:
        """Scan active operations and reconcile any abandoned ones to INTERRUPTED.

        If ``target_owner_id`` is supplied, reconciles operations claimed by that owner.
        If omitted, reconciles operations owned by a different process.
        """
        reconciled: list[IdempotentOperationState] = []
        with self._persistence.transaction():
            candidates = (
                self.find_abandoned_operations()
                if target_owner_id is None
                else [op for op in self.list_active_operations() if op.owner_id == target_owner_id]
            )
            for op in candidates:
                msg = reason or (
                    f"Reconciled on startup: owner was {op.owner_id!r}, which is not this process ({self._owner_id!r})"
                )
                updated = self._transition_to_interrupted(
                    op,
                    reason=msg,
                    transition_id=_op_transition_id(op.operation_id, "startup-reconciliation"),
                )
                reconciled.append(updated)
                logger.info(
                    "Reconciled abandoned operation %s (key=%s) to INTERRUPTED (ambiguous=%s)",
                    op.operation_id,
                    op.idempotency_key,
                    updated.is_ambiguous,
                )
        return reconciled
