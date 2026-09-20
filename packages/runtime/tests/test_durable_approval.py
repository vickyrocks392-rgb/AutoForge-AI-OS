"""Unit tests for DurableApprovalStore, approval identity, lifecycle and caching.

Phase 18-J.5 — Durable Human-in-the-Loop (HITL) Approval & Recovery.
"""

from __future__ import annotations

import copy
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from autoforge_runtime.approval_store import (
    ApprovalConflictError,
    ApprovalError,
    ApprovalExpiredError,
    ApprovalNotFoundError,
    DurableApprovalStore,
    FingerprintConflictError,
    approval_id_for_key,
    compute_request_fingerprint,
    derive_approval_key,
    sanitize_payload,
)
from autoforge_runtime.models import (
    ApprovalRequestState,
    DurableApprovalStatus,
    EntityType,
)
from autoforge_runtime.persistence import PersistenceLayer, SQLiteStorage
from autoforge_runtime.validation import (
    get_allowed_approval_transitions,
    is_approval_recoverable,
    is_approval_terminal,
    validate_approval_transition,
)


@pytest.fixture
def persistence(tmp_path: Path) -> PersistenceLayer:
    """Fixture providing a fresh file-backed PersistenceLayer."""
    db_path = tmp_path / "approval_test.db"
    return PersistenceLayer(db_path=db_path)


@pytest.fixture
def store(persistence: PersistenceLayer) -> DurableApprovalStore:
    """Fixture providing a DurableApprovalStore."""
    return DurableApprovalStore(persistence=persistence, owner_id="test-worker:1234")


# ── Section A & B: Model, Serialization and Identity ──────────────────────


def test_approval_key_and_id_derivation() -> None:
    """Deterministic identity derivation produces identical UUIDs for identical gates."""
    wf_id = uuid.uuid4()
    task_id = "deploy_prod"
    gate_id = "gate_security_review"

    key1 = derive_approval_key(workflow_id=wf_id, task_id=task_id, gate_id=gate_id)
    key2 = derive_approval_key(workflow_id=wf_id, task_id=task_id, gate_id=gate_id)
    assert key1 == key2

    id1 = approval_id_for_key(key1)
    id2 = approval_id_for_key(key2)
    assert id1 == id2
    assert isinstance(id1, uuid.UUID)

    # Different gate yields different key and UUID
    diff_key = derive_approval_key(workflow_id=wf_id, task_id=task_id, gate_id="other_gate")
    assert diff_key != key1
    assert approval_id_for_key(diff_key) != id1


def test_payload_sanitization_and_fingerprinting() -> None:
    """Payload sanitization strips sensitive secrets and computes deterministic hash."""
    payload = {
        "cluster": "prod-us-east",
        "api_key": "secret-super-key",
        "token": "bearer xyz",
        "nested": {
            "password": "pass",
            "safe_val": 42,
        },
    }
    cleaned = sanitize_payload(payload)
    assert cleaned["cluster"] == "prod-us-east"
    assert cleaned["api_key"] == "[REDACTED]"
    assert cleaned["token"] == "[REDACTED]"
    assert cleaned["nested"]["password"] == "[REDACTED]"
    assert cleaned["nested"]["safe_val"] == 42

    fp1 = compute_request_fingerprint(payload)
    fp2 = compute_request_fingerprint(payload)
    assert fp1 == fp2
    assert len(fp1) == 64


def test_approval_creation_and_retrieval(store: DurableApprovalStore) -> None:
    """Approval request is persisted durably and inspectable."""
    wf_id = uuid.uuid4()
    req = store.create_approval_request(
        workflow_id=wf_id,
        task_id="task_audit",
        gate_id="gate_1",
        requested_by="operator@company.com",
        request_payload={"reason": "prod deploy"},
        timeout_seconds=3600,
        metadata={"priority": "high"},
    )

    assert req.status == DurableApprovalStatus.PENDING
    assert req.workflow_id == wf_id
    assert req.task_id == "task_audit"
    assert req.requested_by == "operator@company.com"
    assert req.timeout_seconds == 3600
    assert req.expires_at is not None
    assert req.state_version == 1

    # Read back by ID
    fetched = store.get_approval_request(req.approval_id)
    assert fetched is not None
    assert fetched.approval_id == req.approval_id
    assert fetched.approval_key == req.approval_key
    assert fetched.status == DurableApprovalStatus.PENDING

    # Read back by key
    by_key = store.get_by_key(req.approval_key)
    assert by_key is not None
    assert by_key.approval_id == req.approval_id


def test_approval_creation_idempotency_and_conflict(store: DurableApprovalStore) -> None:
    """Duplicate creation with same payload is idempotent; differing payload conflicts."""
    wf_id = uuid.uuid4()
    req1 = store.create_approval_request(
        workflow_id=wf_id,
        task_id="task_a",
        gate_id="gate_main",
        request_payload={"action": "reboot"},
    )
    # Exact duplicate call returns existing record
    req2 = store.create_approval_request(
        workflow_id=wf_id,
        task_id="task_a",
        gate_id="gate_main",
        request_payload={"action": "reboot"},
    )
    assert req1.approval_id == req2.approval_id
    assert req2.state_version == req1.state_version

    # Differing payload raises FingerprintConflictError
    with pytest.raises(FingerprintConflictError):
        store.create_approval_request(
            workflow_id=wf_id,
            task_id="task_a",
            gate_id="gate_main",
            request_payload={"action": "wipe_database"},
        )


# ── Section C & D: State Machine & Decisions ─────────────────────────────


def test_approve_decision_lifecycle(store: DurableApprovalStore) -> None:
    """PENDING -> APPROVED records decision provenance and marks record terminal."""
    wf_id = uuid.uuid4()
    req = store.create_approval_request(
        workflow_id=wf_id,
        task_id="task_approval",
        gate_id="gate_deploy",
    )
    assert req.status == DurableApprovalStatus.PENDING

    approved = store.submit_decision(
        req.approval_id,
        outcome=DurableApprovalStatus.APPROVED,
        decided_by="admin_alice",
        reason="Checks verified",
        metadata={"signature": "rsa_valid"},
    )
    assert approved.status == DurableApprovalStatus.APPROVED
    assert approved.resolved_by == "admin_alice"
    assert approved.resolved_at is not None
    assert approved.decision == "approved"
    assert approved.decision_reason == "Checks verified"
    assert approved.state_version == 2
    assert len(approved.decision_history) == 1
    assert approved.decision_history[0]["decided_by"] == "admin_alice"

    # Terminal state check
    assert is_approval_terminal(approved.status)
    assert not is_approval_recoverable(approved.status)


def test_reject_decision_lifecycle(store: DurableApprovalStore) -> None:
    """PENDING -> REJECTED records rejection reason."""
    wf_id = uuid.uuid4()
    req = store.create_approval_request(
        workflow_id=wf_id,
        task_id="task_migrate",
        gate_id="gate_1",
    )

    rejected = store.submit_decision(
        req.approval_id,
        outcome="rejected",
        decided_by="security_bob",
        reason="Security vulnerabilities unpatched",
    )
    assert rejected.status == DurableApprovalStatus.REJECTED
    assert rejected.resolved_by == "security_bob"
    assert rejected.decision == "rejected"
    assert rejected.decision_reason == "Security vulnerabilities unpatched"
    assert rejected.state_version == 2


def test_decision_idempotency(store: DurableApprovalStore) -> None:
    """Duplicate submission of the exact same decision by the same actor returns existing state."""
    req = store.create_approval_request(gate_id="gate_idem", task_id="t1")
    dec1 = store.submit_decision(
        req.approval_id,
        outcome=DurableApprovalStatus.APPROVED,
        decided_by="human_1",
        reason="Looks good",
    )
    # Submitting identical approve again
    dec2 = store.submit_decision(
        req.approval_id,
        outcome=DurableApprovalStatus.APPROVED,
        decided_by="human_1",
        reason="Looks good",
    )
    assert dec1.approval_id == dec2.approval_id
    assert dec2.state_version == dec1.state_version


def test_conflicting_decision_rejection(store: DurableApprovalStore) -> None:
    """A terminal decision cannot be overturned by a conflicting decision."""
    req = store.create_approval_request(gate_id="gate_conflict", task_id="t2")
    store.submit_decision(
        req.approval_id,
        outcome=DurableApprovalStatus.APPROVED,
        decided_by="human_1",
    )

    # Submitting REJECT after APPROVED must fail with ApprovalConflictError
    with pytest.raises(ApprovalConflictError):
        store.submit_decision(
            req.approval_id,
            outcome=DurableApprovalStatus.REJECTED,
            decided_by="human_2",
        )

    # Submitting by a different resolver also conflicts
    with pytest.raises(ApprovalConflictError):
        store.submit_decision(
            req.approval_id,
            outcome=DurableApprovalStatus.APPROVED,
            decided_by="human_2",
        )


def test_cancel_approval(store: DurableApprovalStore) -> None:
    """PENDING approval can be cancelled; terminal approval cannot."""
    req = store.create_approval_request(gate_id="gate_cancel", task_id="t3")
    cancelled = store.cancel_approval(req.approval_id, reason="wf_cancelled", cancelled_by="operator")
    assert cancelled.status == DurableApprovalStatus.CANCELLED
    assert cancelled.decision == "cancelled"

    # Idempotent cancel
    cancelled2 = store.cancel_approval(req.approval_id)
    assert cancelled2.approval_id == cancelled.approval_id

    # Trying to approve a cancelled request fails
    with pytest.raises(ApprovalConflictError):
        store.submit_decision(
            req.approval_id,
            outcome=DurableApprovalStatus.APPROVED,
            decided_by="someone",
        )


# ── Section E: Expiration & Timeouts ─────────────────────────────────────


def test_durable_expiration(store: DurableApprovalStore) -> None:
    """Explicit expiration transitions PENDING -> EXPIRED."""
    req = store.create_approval_request(gate_id="gate_expire", task_id="t4")
    expired = store.expire_approval(req.approval_id, reason="timed out waiting for manager")
    assert expired.status == DurableApprovalStatus.EXPIRED

    # Deciding on an expired request fails
    with pytest.raises(ApprovalConflictError):
        store.submit_decision(
            req.approval_id,
            outcome=DurableApprovalStatus.APPROVED,
            decided_by="admin",
        )


def test_reconcile_expired_approvals(store: DurableApprovalStore) -> None:
    """Reconciling expired approvals discovers overdue requests and marks them EXPIRED."""
    past_time = datetime.now(timezone.utc) - timedelta(seconds=10)
    future_time = datetime.now(timezone.utc) + timedelta(hours=1)

    # Overdue approval
    req_overdue = store.create_approval_request(
        gate_id="gate_overdue",
        task_id="t5",
        expires_at=past_time,
    )
    # Valid active approval
    req_active = store.create_approval_request(
        gate_id="gate_active",
        task_id="t6",
        expires_at=future_time,
    )

    reconciled = store.reconcile_expired_approvals()
    reconciled_ids = [r.approval_id for r in reconciled]
    assert req_overdue.approval_id in reconciled_ids
    assert req_active.approval_id not in reconciled_ids

    # Overdue is now EXPIRED
    check_overdue = store.get_approval_request(req_overdue.approval_id)
    assert check_overdue is not None
    assert check_overdue.status == DurableApprovalStatus.EXPIRED

    # Active remains PENDING
    check_active = store.get_approval_request(req_active.approval_id)
    assert check_active is not None
    assert check_active.status == DurableApprovalStatus.PENDING


# ── Section F: Cache Coherence & Rollback ─────────────────────────────────


def test_cache_hit_miss_and_coherence(persistence: PersistenceLayer) -> None:
    """Writes update cache; reads hit cache; SQLite remains authoritative."""
    store = DurableApprovalStore(persistence)
    req = store.create_approval_request(gate_id="gate_cache", task_id="tc")

    # Cache hit
    cached = persistence.cache.get(EntityType.APPROVAL_REQUEST, req.approval_id)
    assert cached is not None
    assert isinstance(cached, ApprovalRequestState)
    assert cached.status == DurableApprovalStatus.PENDING

    # Invalidate cache -> fallback to SQLite
    persistence.cache.clear()
    assert persistence.cache.get(EntityType.APPROVAL_REQUEST, req.approval_id) is None

    read_back = store.get_approval_request(req.approval_id)
    assert read_back is not None
    assert read_back.approval_id == req.approval_id

    # Now cached again
    assert persistence.cache.get(EntityType.APPROVAL_REQUEST, req.approval_id) is not None


def test_rollback_does_not_corrupt_cache(persistence: PersistenceLayer) -> None:
    """A failed transaction rolled back does not leave phantom cache entries."""
    store = DurableApprovalStore(persistence)
    req = store.create_approval_request(gate_id="gate_rb", task_id="trb")

    # Attempt an update that raises an error inside transaction
    with pytest.raises(ZeroDivisionError):
        with persistence.transaction():
            store.submit_decision(
                req.approval_id,
                outcome=DurableApprovalStatus.APPROVED,
                decided_by="alice",
            )
            # simulate crash / exception before commit
            1 / 0

    # Verify state rolled back in both cache and DB
    fresh_read = store.get_approval_request(req.approval_id)
    assert fresh_read is not None
    assert fresh_read.status == DurableApprovalStatus.PENDING
    assert fresh_read.state_version == 1


# ── Section G: Audit Trail & HistoryStore ────────────────────────────────


def test_approval_history_audit_trail(persistence: PersistenceLayer) -> None:
    """Every state transition writes an immutable record to HistoryStore."""
    store = DurableApprovalStore(persistence)
    req = store.create_approval_request(gate_id="gate_hist", task_id="thist")
    store.submit_decision(
        req.approval_id,
        outcome=DurableApprovalStatus.APPROVED,
        decided_by="auditor_jane",
        reason="Signed off",
    )

    history = persistence.history.read_by_entity(EntityType.APPROVAL_REQUEST, req.approval_id)
    assert len(history) == 2

    # 1. creation: none -> pending
    assert history[0].from_state == "none"
    assert history[0].to_state == "pending"

    # 2. decision: pending -> approved
    assert history[1].from_state == "pending"
    assert history[1].to_state == "approved"
    assert history[1].actor == "auditor_jane"
    assert history[1].metadata.get("reason") == "Signed off"
