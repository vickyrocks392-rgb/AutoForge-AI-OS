"""Durable Approval Store — canonical approval identity, lifecycle and decision safety.

Phase 18-J (Durable Execution + Resume + Idempotency), step 18-J.5
------------------------------------------------------------------
This module implements durable Human-in-the-Loop (HITL) approval state:
making human intervention a first-class, durable runtime concept backed
by the authoritative PersistenceLayer / SQLite durability foundation.

Authoritative Foundation:
-------------------------
All approval records are stored through the runtime's single
:class:`~autoforge_runtime.persistence.PersistenceLayer` (SQLite in WAL mode
with BEGIN IMMEDIATE transactions). No second database, no Redis, no Kafka,
no Temporal.

Guarantees & Semantics:
-----------------------
1. Logical Approval Identity:
   Separated from physical execution attempt identity. A physical retry of an
   interrupted task (Attempt 1 -> Attempt 2) derives the EXACT SAME logical
   approval key and UUID.
2. Request Fingerprinting & Sanitization:
   Deterministic SHA-256 hash of canonicalized JSON request payloads. Sensitive
   tokens and credentials are automatically stripped before persistence.
3. Transactional Decision Protocol:
   Atomic SQLite transactions (BEGIN IMMEDIATE + state_version check) guarantee
   that only ONE terminal decision (APPROVE / REJECT / CANCEL / EXPIRE) can win
   across concurrent processes.
4. Idempotent Decision Submission:
   Submitting an identical terminal decision by the same actor returns the existing
   durable decision record without conflict. Conflicting decisions are strictly rejected.
5. Durable Expiration:
   Timeouts and expirations are recorded durably as timestamps. Expired approvals
   are transitioned to EXPIRED and cannot be resurrected upon restart.
6. Audit & Provenance:
   Authoritative durable state is committed before observational events are emitted.
   Every state change writes an append-only record to HistoryStore.
"""

from __future__ import annotations

import copy
import hashlib
import json
import logging
import os
import socket
import uuid
from datetime import datetime, timedelta, timezone
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
    APPROVAL_RECORD_VERSION,
    ApprovalRequestState,
    DurableApprovalStatus,
    EntityType,
    StateTransition,
)
from autoforge_runtime.persistence import PersistenceLayer
from autoforge_runtime.validation import (
    is_approval_recoverable,
    is_approval_terminal,
    validate_approval_transition,
)

logger = logging.getLogger("autoforge.runtime.approval_store")

#: Namespace UUID used to derive canonical UUIDv5 approval identifiers.
APPROVAL_NAMESPACE = uuid.UUID("d637b51b-4f9e-4c07-b371-fa52e46b6ea1")

#: Neutral state label used as ``from_state`` when an approval record is first created.
_CREATED_FROM_STATE = "none"

#: Sensitive field names stripped in request payloads.
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


class ApprovalError(PersistenceError):
    """Base exception for all durable approval protocol errors."""


class ApprovalNotFoundError(ApprovalError, EntityNotFoundError):
    """Raised when an approval request cannot be found."""


class ApprovalConflictError(ApprovalError):
    """Raised when an approval request transition or decision conflicts."""


class ApprovalExpiredError(ApprovalError):
    """Raised when attempting to decide on an expired approval request."""


class FingerprintConflictError(ApprovalError):
    """Raised when an approval key is reused with a different request payload."""


# ── Canonical Key Derivation & Identification ─────────────────────────────


def default_approval_owner_id() -> str:
    """Return the identity of the current process (``host:pid``)."""
    return f"{socket.gethostname()}:{os.getpid()}"


def _now() -> datetime:
    """Return the current timezone-aware UTC timestamp."""
    return datetime.now(timezone.utc)


def derive_approval_key(
    *,
    workflow_id: uuid.UUID | str | None = None,
    task_id: str | None = None,
    gate_id: str | None = None,
    approval_type: str = "gate",
) -> str:
    """Derive a canonical, deterministic logical approval key.

    The key remains stable across retries and restarts of the same work unit.
    """
    parts = [f"type:{approval_type}"]
    if workflow_id:
        parts.append(f"wf:{workflow_id}")
    if task_id:
        parts.append(f"task:{task_id}")
    if gate_id:
        parts.append(f"gate:{gate_id}")
    return ":".join(parts)


def approval_id_for_key(approval_key: str) -> uuid.UUID:
    """Derive a deterministic, collision-resistant UUIDv5 from an approval key."""
    return uuid.uuid5(APPROVAL_NAMESPACE, approval_key)


def sanitize_payload(payload: dict[str, Any] | None) -> dict[str, Any]:
    """Return a sanitized copy of the payload with sensitive fields stripped."""
    if not payload:
        return {}
    sanitized: dict[str, Any] = {}
    for k, v in payload.items():
        if k.lower() in SENSITIVE_FIELD_NAMES:
            sanitized[k] = "[REDACTED]"
        elif isinstance(v, dict):
            sanitized[k] = sanitize_payload(v)
        else:
            sanitized[k] = copy.deepcopy(v)
    return sanitized


def compute_request_fingerprint(payload: dict[str, Any] | None) -> str:
    """Compute deterministic SHA-256 fingerprint from sanitized request payload."""
    clean = sanitize_payload(payload)
    canonical_json = json.dumps(clean, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()


def _approval_transition_id(approval_id: uuid.UUID | None, suffix: str) -> uuid.UUID:
    """Derive a deterministic history-row ID from an approval ID."""
    if approval_id is None:
        return uuid.uuid4()
    return uuid.uuid5(approval_id, suffix)


# ── Durable Approval Store ────────────────────────────────────────────────


class DurableApprovalStore:
    """Transactional, SQLite-backed store for Human-In-The-Loop approval state.

    Args:
        persistence: Authoritative PersistenceLayer instance (required).
        owner_id: Identity of the current process (defaults to ``host:pid``).
    """

    def __init__(
        self,
        persistence: PersistenceLayer,
        *,
        owner_id: str | None = None,
    ) -> None:
        if persistence is None:
            raise PersistenceError(
                "DurableApprovalStore requires the runtime persistence layer",
                details={},
            )
        self._persistence = persistence
        self._owner_id = owner_id or default_approval_owner_id()

    @property
    def persistence(self) -> PersistenceLayer:
        """The runtime persistence layer backing this store."""
        return self._persistence

    @property
    def owner_id(self) -> str:
        """Identity of the current process (``host:pid``)."""
        return self._owner_id

    def create_approval_request(
        self,
        *,
        workflow_id: uuid.UUID | str | None = None,
        task_id: str | None = None,
        gate_id: str | None = None,
        execution_id: uuid.UUID | str | None = None,
        attempt_id: uuid.UUID | str | None = None,
        approval_type: str = "gate",
        requested_by: str = "system",
        request_payload: dict[str, Any] | None = None,
        timeout_seconds: float | None = None,
        expires_at: datetime | None = None,
        required_approvers: int = 1,
        approval_key: str | None = None,
        metadata: dict[str, Any] | None = None,
        provenance: dict[str, Any] | None = None,
    ) -> ApprovalRequestState:
        """Create and durably persist a human approval request.

        If a request with the same canonical approval key already exists:
        - If fingerprint matches: returns the existing record (idempotent creation).
        - If fingerprint differs: raises :class:`FingerprintConflictError`.

        Args:
            workflow_id: Owning workflow ID.
            task_id: Task ID waiting for approval.
            gate_id: Gate identifier (if attached to a gate policy).
            execution_id: Execution ID.
            attempt_id: Current physical attempt ID.
            approval_type: Classification string (e.g. 'gate', 'tool', 'consequential').
            requested_by: Identity of the requester.
            request_payload: Context payload (sanitized before storage).
            timeout_seconds: Optional timeout in seconds.
            expires_at: Explicit expiration timestamp.
            required_approvers: Number of approvals required.
            approval_key: Optional explicit key; derived automatically if omitted.
            metadata: Extensible diagnostic metadata.
            provenance: Provenance details.

        Returns:
            The durable :class:`ApprovalRequestState`.
        """
        w_uuid = uuid.UUID(str(workflow_id)) if workflow_id else None
        e_uuid = uuid.UUID(str(execution_id)) if execution_id else None
        a_uuid = uuid.UUID(str(attempt_id)) if attempt_id else None

        key = approval_key or derive_approval_key(
            workflow_id=w_uuid,
            task_id=task_id,
            gate_id=gate_id,
            approval_type=approval_type,
        )
        app_id = approval_id_for_key(key)

        sanitized = sanitize_payload(request_payload)
        fingerprint = compute_request_fingerprint(sanitized)
        now = _now()

        computed_expires_at = expires_at
        if computed_expires_at is None and timeout_seconds is not None and timeout_seconds > 0:
            computed_expires_at = now + timedelta(seconds=timeout_seconds)

        with self._persistence.transaction():
            existing = self._get_by_id_locked(app_id)
            if existing is not None:
                if existing.request_fingerprint != fingerprint:
                    raise FingerprintConflictError(
                        f"Approval key {key!r} already exists with a different request fingerprint",
                        details={
                            "approval_id": str(app_id),
                            "approval_key": key,
                            "existing_fingerprint": existing.request_fingerprint,
                            "new_fingerprint": fingerprint,
                        },
                    )
                return existing

            record = ApprovalRequestState(
                approval_id=app_id,
                approval_key=key,
                workflow_id=w_uuid,
                task_id=task_id,
                execution_id=e_uuid,
                attempt_id=a_uuid,
                approval_type=approval_type,
                status=DurableApprovalStatus.PENDING,
                requested_by=requested_by,
                requested_at=now,
                request_payload=sanitized,
                request_fingerprint=fingerprint,
                timeout_seconds=timeout_seconds,
                expires_at=computed_expires_at,
                required_approvers=required_approvers,
                state_version=1,
                schema_version=APPROVAL_RECORD_VERSION,
                owner_id=self._owner_id,
                metadata=copy.deepcopy(metadata or {}),
                provenance=copy.deepcopy(provenance or {}),
            )

            self._persistence.write_state(
                EntityType.APPROVAL_REQUEST,
                record.approval_id,
                record,
                expected_version=None,
            )

            # Audit history transition: none -> pending
            self._persistence.write_history(
                StateTransition(
                    transition_id=_approval_transition_id(app_id, "create"),
                    entity_type=EntityType.APPROVAL_REQUEST,
                    entity_id=app_id,
                    from_state=_CREATED_FROM_STATE,
                    to_state=DurableApprovalStatus.PENDING.value,
                    actor=requested_by,
                    timestamp=now,
                    metadata={
                        "approval_key": key,
                        "workflow_id": str(w_uuid) if w_uuid else None,
                        "task_id": task_id,
                    },
                )
            )

            return record

    def get_approval_request(self, approval_id: uuid.UUID | str) -> ApprovalRequestState | None:
        """Retrieve approval request by ID."""
        coerced = uuid.UUID(str(approval_id)) if not isinstance(approval_id, uuid.UUID) else approval_id
        try:
            state = self._persistence.read_state(EntityType.APPROVAL_REQUEST, coerced)
            if isinstance(state, ApprovalRequestState):
                return state
            return None
        except EntityNotFoundError:
            return None

    def get_by_key(self, approval_key: str) -> ApprovalRequestState | None:
        """Retrieve approval request by its canonical logical key."""
        app_id = approval_id_for_key(approval_key)
        return self.get_approval_request(app_id)

    def find_by_workflow(self, workflow_id: uuid.UUID | str) -> list[ApprovalRequestState]:
        """Find all approval requests associated with a workflow."""
        w_uuid = uuid.UUID(str(workflow_id))
        all_records = self._persistence.read_all(EntityType.APPROVAL_REQUEST)
        return [
            r for r in all_records
            if isinstance(r, ApprovalRequestState) and r.workflow_id == w_uuid
        ]

    def find_pending_for_task(
        self,
        workflow_id: uuid.UUID | str,
        task_id: str,
    ) -> ApprovalRequestState | None:
        """Find pending approval request for a specific task in a workflow."""
        for app in self.find_by_workflow(workflow_id):
            if app.task_id == task_id and app.status == DurableApprovalStatus.PENDING:
                return app
        return None

    def list_pending_approvals(self) -> list[ApprovalRequestState]:
        """List all currently pending approval requests across all workflows."""
        all_records = self._persistence.read_all(EntityType.APPROVAL_REQUEST)
        return [
            r for r in all_records
            if isinstance(r, ApprovalRequestState) and r.status == DurableApprovalStatus.PENDING
        ]

    def submit_decision(
        self,
        approval_id: uuid.UUID | str,
        *,
        outcome: DurableApprovalStatus | str,
        decided_by: str,
        reason: str = "",
        metadata: dict[str, Any] | None = None,
        expected_version: int | None = None,
    ) -> ApprovalRequestState:
        """Record an approval or rejection decision transactionally.

        Guarantees:
        - Transactionally exclusive: cross-process concurrency is safely serialized.
        - Decision idempotency: duplicate submission of identical decision returns existing record.
        - Conflict rejection: conflicting decision (e.g. approve after reject) is rejected.
        - Expiration enforcement: decisions on expired approvals fail with :class:`ApprovalExpiredError`.

        Args:
            approval_id: Approval request UUID.
            outcome: Target terminal outcome (APPROVED or REJECTED).
            decided_by: Identity of the decision maker.
            reason: Human-readable rationale.
            metadata: Extensible decision metadata.
            expected_version: Optional expected state_version for OCC.

        Returns:
            The updated terminal :class:`ApprovalRequestState`.
        """
        coerced_id = uuid.UUID(str(approval_id)) if not isinstance(approval_id, uuid.UUID) else approval_id
        target_status = DurableApprovalStatus(outcome.lower() if isinstance(outcome, str) else outcome.value)
        if target_status not in {DurableApprovalStatus.APPROVED, DurableApprovalStatus.REJECTED}:
            raise ApprovalError(
                f"Invalid decision outcome {outcome!r}; must be APPROVED or REJECTED",
                details={"approval_id": str(coerced_id), "outcome": str(outcome)},
            )

        now = _now()

        with self._persistence.transaction():
            current = self._get_by_id_locked(coerced_id)
            if current is None:
                raise ApprovalNotFoundError(
                    f"Approval request {coerced_id} not found",
                    details={"approval_id": str(coerced_id)},
                )

            # Check OCC if requested
            if expected_version is not None and current.state_version != expected_version:
                raise VersionConflictError(
                    f"Approval request {coerced_id} version mismatch: expected {expected_version}, got {current.state_version}",
                    details={"approval_id": str(coerced_id), "version": current.state_version},
                )

            # Check for existing terminal state
            if is_approval_terminal(current.status):
                if current.status == target_status and current.resolved_by == decided_by:
                    # Idempotent re-submission of the same decision
                    logger.debug("Idempotent decision replay for approval %s (%s)", coerced_id, target_status)
                    return current

                raise ApprovalConflictError(
                    f"Approval request {coerced_id} is already in terminal state {current.status.value!r} and cannot transition to {target_status.value!r}",
                    details={
                        "approval_id": str(coerced_id),
                        "current_status": current.status.value,
                        "target_status": target_status.value,
                        "resolved_by": current.resolved_by,
                    },
                )

            # Check expiration
            if current.expires_at and now >= current.expires_at:
                # Transition to expired
                expired_record = self._apply_terminal_transition(
                    current,
                    DurableApprovalStatus.EXPIRED,
                    resolved_by="system",
                    decision="expired",
                    reason="approval_timeout",
                    timestamp=now,
                    suffix="expire_on_decision",
                )
                raise ApprovalExpiredError(
                    f"Approval request {coerced_id} expired at {current.expires_at.isoformat()}",
                    details={
                        "approval_id": str(coerced_id),
                        "expires_at": current.expires_at.isoformat(),
                    },
                )

            # Validate transition
            val = validate_approval_transition(current.status, target_status)
            if not val.valid:
                raise InvalidTransitionError(
                    val.error_message or "Invalid transition",
                    details={"from_state": current.status.value, "to_state": target_status.value},
                )

            decision_entry = {
                "outcome": target_status.value,
                "decided_by": decided_by,
                "reason": reason,
                "decided_at": now.isoformat(),
                "metadata": metadata or {},
            }
            new_history = list(current.decision_history)
            new_history.append(decision_entry)

            updated = ApprovalRequestState(
                approval_id=current.approval_id,
                approval_key=current.approval_key,
                workflow_id=current.workflow_id,
                task_id=current.task_id,
                execution_id=current.execution_id,
                attempt_id=current.attempt_id,
                approval_type=current.approval_type,
                status=target_status,
                requested_by=current.requested_by,
                requested_at=current.requested_at,
                resolved_by=decided_by,
                resolved_at=now,
                decision=target_status.value,
                decision_reason=reason,
                request_payload=current.request_payload,
                request_fingerprint=current.request_fingerprint,
                timeout_seconds=current.timeout_seconds,
                expires_at=current.expires_at,
                required_approvers=current.required_approvers,
                decision_history=new_history,
                state_version=current.state_version + 1,
                schema_version=current.schema_version,
                owner_id=self._owner_id,
                metadata=copy.deepcopy(current.metadata),
                provenance=copy.deepcopy(current.provenance),
            )

            self._persistence.write_state(
                EntityType.APPROVAL_REQUEST,
                updated.approval_id,
                updated,
                expected_version=current.version,
            )

            self._persistence.write_history(
                StateTransition(
                    transition_id=_approval_transition_id(coerced_id, f"decide_{updated.state_version}"),
                    entity_type=EntityType.APPROVAL_REQUEST,
                    entity_id=coerced_id,
                    from_state=current.status.value,
                    to_state=target_status.value,
                    actor=decided_by,
                    timestamp=now,
                    metadata={
                        "reason": reason,
                        "approval_key": current.approval_key,
                        "workflow_id": str(current.workflow_id) if current.workflow_id else None,
                        "task_id": current.task_id,
                    },
                )
            )

            return updated

    def cancel_approval(
        self,
        approval_id: uuid.UUID | str,
        *,
        reason: str = "workflow_cancelled",
        cancelled_by: str = "system",
    ) -> ApprovalRequestState:
        """Cancel an active approval request.

        Args:
            approval_id: Approval request ID.
            reason: Cancellation reason.
            cancelled_by: Actor requesting cancellation.

        Returns:
            The cancelled :class:`ApprovalRequestState`.
        """
        coerced_id = uuid.UUID(str(approval_id)) if not isinstance(approval_id, uuid.UUID) else approval_id
        now = _now()

        with self._persistence.transaction():
            current = self._get_by_id_locked(coerced_id)
            if current is None:
                raise ApprovalNotFoundError(
                    f"Approval request {coerced_id} not found",
                    details={"approval_id": str(coerced_id)},
                )

            if current.status == DurableApprovalStatus.CANCELLED:
                return current

            if is_approval_terminal(current.status):
                raise ApprovalConflictError(
                    f"Approval request {coerced_id} is already terminal ({current.status.value}) and cannot be cancelled",
                    details={"approval_id": str(coerced_id), "current_status": current.status.value},
                )

            return self._apply_terminal_transition(
                current,
                DurableApprovalStatus.CANCELLED,
                resolved_by=cancelled_by,
                decision="cancelled",
                reason=reason,
                timestamp=now,
                suffix="cancel",
            )

    def expire_approval(
        self,
        approval_id: uuid.UUID | str,
        *,
        reason: str = "timeout",
    ) -> ApprovalRequestState:
        """Mark an active approval request as expired."""
        coerced_id = uuid.UUID(str(approval_id)) if not isinstance(approval_id, uuid.UUID) else approval_id
        now = _now()

        with self._persistence.transaction():
            current = self._get_by_id_locked(coerced_id)
            if current is None:
                raise ApprovalNotFoundError(
                    f"Approval request {coerced_id} not found",
                    details={"approval_id": str(coerced_id)},
                )

            if current.status == DurableApprovalStatus.EXPIRED:
                return current

            if is_approval_terminal(current.status):
                raise ApprovalConflictError(
                    f"Approval request {coerced_id} is already terminal ({current.status.value}) and cannot be expired",
                    details={"approval_id": str(coerced_id), "current_status": current.status.value},
                )

            return self._apply_terminal_transition(
                current,
                DurableApprovalStatus.EXPIRED,
                resolved_by="system",
                decision="expired",
                reason=reason,
                timestamp=now,
                suffix="expire",
            )

    def reconcile_expired_approvals(self) -> list[ApprovalRequestState]:
        """Discover and transition overdue pending approvals to EXPIRED.

        Returns:
            List of approval requests that were expired during this pass.
        """
        now = _now()
        expired: list[ApprovalRequestState] = []

        with self._persistence.transaction():
            pending = self.list_pending_approvals()
            for app in pending:
                if app.expires_at and now >= app.expires_at:
                    try:
                        record = self._apply_terminal_transition(
                            app,
                            DurableApprovalStatus.EXPIRED,
                            resolved_by="system",
                            decision="expired",
                            reason="scheduled_expiration_reconciliation",
                            timestamp=now,
                            suffix=f"reconcile_expire_{app.state_version + 1}",
                        )
                        expired.append(record)
                    except Exception as exc:
                        logger.warning("Failed to expire overdue approval %s: %s", app.approval_id, exc)

        return expired

    # ── Internal Helpers ──────────────────────────────────────────────────

    def _get_by_id_locked(self, approval_id: uuid.UUID) -> ApprovalRequestState | None:
        """Fetch approval state from persistence inside an active transaction."""
        try:
            state = self._persistence.read_state(EntityType.APPROVAL_REQUEST, approval_id)
            if isinstance(state, ApprovalRequestState):
                return state
            return None
        except EntityNotFoundError:
            return None

    def _apply_terminal_transition(
        self,
        current: ApprovalRequestState,
        target_status: DurableApprovalStatus,
        *,
        resolved_by: str,
        decision: str,
        reason: str,
        timestamp: datetime,
        suffix: str,
    ) -> ApprovalRequestState:
        """Apply a terminal transition to an approval request and write history."""
        decision_entry = {
            "outcome": target_status.value,
            "decided_by": resolved_by,
            "reason": reason,
            "decided_at": timestamp.isoformat(),
        }
        new_history = list(current.decision_history)
        new_history.append(decision_entry)

        updated = ApprovalRequestState(
            approval_id=current.approval_id,
            approval_key=current.approval_key,
            workflow_id=current.workflow_id,
            task_id=current.task_id,
            execution_id=current.execution_id,
            attempt_id=current.attempt_id,
            approval_type=current.approval_type,
            status=target_status,
            requested_by=current.requested_by,
            requested_at=current.requested_at,
            resolved_by=resolved_by,
            resolved_at=timestamp,
            decision=decision,
            decision_reason=reason,
            request_payload=current.request_payload,
            request_fingerprint=current.request_fingerprint,
            timeout_seconds=current.timeout_seconds,
            expires_at=current.expires_at,
            required_approvers=current.required_approvers,
            decision_history=new_history,
            state_version=current.state_version + 1,
            schema_version=current.schema_version,
            owner_id=self._owner_id,
            metadata=copy.deepcopy(current.metadata),
            provenance=copy.deepcopy(current.provenance),
        )

        self._persistence.write_state(
            EntityType.APPROVAL_REQUEST,
            updated.approval_id,
            updated,
            expected_version=current.version,
        )

        self._persistence.write_history(
            StateTransition(
                transition_id=_approval_transition_id(current.approval_id, suffix),
                entity_type=EntityType.APPROVAL_REQUEST,
                entity_id=current.approval_id,
                from_state=current.status.value,
                to_state=target_status.value,
                actor=resolved_by,
                timestamp=timestamp,
                metadata={
                    "reason": reason,
                    "approval_key": current.approval_key,
                    "workflow_id": str(current.workflow_id) if current.workflow_id else None,
                    "task_id": current.task_id,
                },
            )
        )

        return updated
