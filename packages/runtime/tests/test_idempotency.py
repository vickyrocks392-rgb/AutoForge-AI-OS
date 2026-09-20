"""Comprehensive Unit Tests for Durable Idempotency & Side-Effect Protection (Phase 18-J.4).

Covers Matrix:
- A: Identity (Logical vs physical attempt identity)
- B: Request Fingerprinting & Conflict Detection
- C: Atomic Claim & Duplicate Protection
- D: Completion Durability & Result Caching
- E: Failure & Retry Policies
- F: Interrupted Recovery Semantics & Provider Idempotency Support
- I: Cache Coherence (Commit, Rollback, Cache Hit/Miss, Restart)
- K: Audit History & Replay Safety
"""

import uuid
from datetime import datetime, timezone
import pytest

from autoforge_runtime.idempotency import (
    AmbiguousSideEffectError,
    ConcurrentOperationError,
    DurableIdempotencyStore,
    FingerprintConflictError,
    IdempotencyError,
    OperationFailedError,
    compute_request_fingerprint,
    default_operation_owner_id,
    derive_idempotency_key,
    derive_task_idempotency_key,
    operation_id_for_key,
    sanitize_payload,
)
from autoforge_runtime.models import (
    EntityType,
    IdempotentOperationState,
    OperationStatus,
)
from autoforge_runtime.persistence import PersistenceLayer, SQLiteStorage
from autoforge_runtime.side_effects import SideEffectExecutor


@pytest.fixture
def temp_db_path(tmp_path):
    return str(tmp_path / "test_idempotency.db")


@pytest.fixture
def persistence(temp_db_path):
    p = PersistenceLayer(temp_db_path)
    yield p
    p.close()


@pytest.fixture
def store(persistence):
    return DurableIdempotencyStore(persistence, owner_id="test-host:12345")


# ── Matrix A: Identity ───────────────────────────────────────────────────


def test_matrix_a_logical_identity_distinct_from_attempt_identity():
    """Verify that logical operation identity remains identical across retried attempts."""
    wf_id = uuid.uuid4()
    exec_id = uuid.uuid4()
    task_id = "process-payment"

    # Attempt 1
    key_attempt_1 = derive_task_idempotency_key(wf_id, task_id, "charge_card")
    op_id_attempt_1 = operation_id_for_key(key_attempt_1)

    # Attempt 2 (retry after crash)
    key_attempt_2 = derive_task_idempotency_key(wf_id, task_id, "charge_card")
    op_id_attempt_2 = operation_id_for_key(key_attempt_2)

    assert key_attempt_1 == key_attempt_2
    assert op_id_attempt_1 == op_id_attempt_2
    assert "attempt" not in key_attempt_1


def test_matrix_a_different_logical_operations_have_different_keys():
    """Verify distinct logical operations receive distinct keys and IDs."""
    exec_id = uuid.uuid4()
    k1 = derive_idempotency_key(exec_id, "http_call", "post_invoice", step_or_call_id=1)
    k2 = derive_idempotency_key(exec_id, "http_call", "post_invoice", step_or_call_id=2)
    k3 = derive_idempotency_key(exec_id, "tool_call", "send_email")

    assert k1 != k2
    assert k1 != k3
    assert operation_id_for_key(k1) != operation_id_for_key(k2)


# ── Matrix B: Request Fingerprinting ──────────────────────────────────────


def test_matrix_b_deterministic_request_fingerprint():
    """Verify canonical dictionary key ordering and stable SHA-256 generation."""
    payload_a = {"b": 2, "a": 1, "nested": {"z": 10, "y": 20}}
    payload_b = {"a": 1, "nested": {"y": 20, "z": 10}, "b": 2}

    fp_a = compute_request_fingerprint(payload_a)
    fp_b = compute_request_fingerprint(payload_b)

    assert fp_a == fp_b
    assert fp_a.startswith("sha256:")


def test_matrix_b_same_key_different_payload_causes_conflict(store):
    """Verify reusing an idempotency key with differing payload raises FingerprintConflictError."""
    key = "op:payment:transfer_funds"
    req_1 = {"amount": 100, "currency": "USD"}
    req_2 = {"amount": 500, "currency": "USD"}  # Changed amount!

    # First claim succeeds
    claim1 = store.claim_operation(key, request_payload=req_1)
    assert claim1.claimed is True

    # Second claim with differing payload MUST fail with FingerprintConflictError
    with pytest.raises(FingerprintConflictError) as exc_info:
        store.claim_operation(key, request_payload=req_2)

    assert "differing request fingerprint" in str(exc_info.value)
    assert exc_info.value.details["idempotency_key"] == key


def test_matrix_b_sensitive_payload_sanitization():
    """Verify sensitive fields like auth tokens and passwords are redacted."""
    sensitive_data = {
        "Authorization": "Bearer secret-token-123",
        "api_key": "super-secret-key",
        "nested": {"password": "admin-password", "visible": "ok"},
    }
    sanitized = sanitize_payload(sensitive_data)

    assert sanitized["Authorization"] == "[REDACTED]"
    assert sanitized["api_key"] == "[REDACTED]"
    assert sanitized["nested"]["password"] == "[REDACTED]"
    assert sanitized["nested"]["visible"] == "ok"


# ── Matrix C & D: Atomic Claim & Completion Durability ─────────────────────


def test_matrix_c_and_d_claim_complete_and_cached_result(store, persistence):
    """Verify atomic claim, durable completion, and subsequent cached result lookup."""
    key = "exec:test-1:tool:send_slack"
    payload = {"channel": "#deploys", "message": "Deploying v1.0"}

    # 1. Initial claim
    claim = store.claim_operation(key, request_payload=payload)
    assert claim.claimed is True
    assert claim.status == OperationStatus.RUNNING
    op_id = claim.operation_id

    # Verify durable record exists in SQLite
    durable_state = store.get_operation(op_id)
    assert durable_state.status == OperationStatus.RUNNING
    assert durable_state.idempotency_key == key

    # 2. Complete operation
    res_data = {"slack_msg_id": "msg_9988", "timestamp": "1234567.89"}
    completed_state = store.complete_operation(op_id, result=res_data)
    assert completed_state.status == OperationStatus.COMPLETED
    assert completed_state.result == res_data
    assert completed_state.completed_at is not None

    # 3. Subsequent claim returns cached result without execution
    subsequent_claim = store.claim_operation(key, request_payload=payload)
    assert subsequent_claim.claimed is False
    assert subsequent_claim.status == OperationStatus.COMPLETED
    assert subsequent_claim.cached_result == res_data


def test_matrix_c_running_operation_blocks_duplicate(store):
    """Verify an active RUNNING operation rejects concurrent duplicate execution."""
    key = "op:render:generate_report"
    payload = {"report_id": "rep_1"}

    claim = store.claim_operation(key, request_payload=payload)
    assert claim.claimed is True

    # Same process or active owner attempting to claim again while RUNNING
    with pytest.raises(ConcurrentOperationError) as exc_info:
        store.claim_operation(key, request_payload=payload)

    assert "currently RUNNING" in str(exc_info.value)


# ── Matrix E: Failure & Retry Policy ──────────────────────────────────────


def test_matrix_e_failed_operation_retry_policy(store):
    """Verify failed operations can be retried when policy allows, incrementing retry count."""
    key = "op:transient:fetch_remote_data"
    payload = {"url": "https://api.example.com/data"}

    # Claim & Fail
    claim = store.claim_operation(key, request_payload=payload)
    failed_state = store.fail_operation(
        claim.operation_id,
        error_code="NetworkTimeout",
        error_message="Connection timed out after 30s",
    )
    assert failed_state.status == OperationStatus.FAILED
    assert failed_state.error_code == "NetworkTimeout"

    # Attempt claim with allow_failed_retry=False -> raises OperationFailedError
    with pytest.raises(OperationFailedError):
        store.claim_operation(key, request_payload=payload, allow_failed_retry=False)

    # Attempt claim with allow_failed_retry=True -> successfully reclaims into RUNNING
    retry_claim = store.claim_operation(key, request_payload=payload, allow_failed_retry=True)
    assert retry_claim.claimed is True
    assert retry_claim.resumed is True
    assert retry_claim.status == OperationStatus.RUNNING
    assert retry_claim.state.retry_count == 1
    assert retry_claim.state.error_code is None


# ── Matrix F: Interrupted Recovery & Ambiguity ────────────────────────────


def test_matrix_f_interrupted_with_provider_idempotency_resumes_cleanly(store):
    """Verify interrupted operations with provider idempotency support resume cleanly."""
    key = "op:stripe:create_charge"
    payload = {"charge_amount": 2500}

    claim = store.claim_operation(
        key,
        request_payload=payload,
        supports_provider_idempotency=True,
    )
    # Simulate crash / interruption
    interrupted = store.mark_interrupted(claim.operation_id, reason="Worker crashed")
    assert interrupted.status == OperationStatus.INTERRUPTED
    assert interrupted.is_ambiguous is False

    # Resume claim
    resumed_claim = store.claim_operation(key, request_payload=payload)
    assert resumed_claim.claimed is True
    assert resumed_claim.resumed is True
    assert resumed_claim.status == OperationStatus.RUNNING
    assert resumed_claim.state.retry_count == 1


def test_matrix_f_interrupted_without_provider_idempotency_is_ambiguous(store):
    """Verify interrupted operations without provider idempotency support are marked ambiguous."""
    key = "op:legacy:non_idempotent_charge"
    payload = {"amount": 500}

    claim = store.claim_operation(
        key,
        request_payload=payload,
        supports_provider_idempotency=False,
    )
    interrupted = store.mark_interrupted(claim.operation_id, reason="Process died")
    assert interrupted.status == OperationStatus.INTERRUPTED
    assert interrupted.is_ambiguous is True
    assert interrupted.ambiguity_reason is not None

    # Resuming an ambiguous operation raises AmbiguousSideEffectError
    with pytest.raises(AmbiguousSideEffectError) as exc_info:
        store.claim_operation(key, request_payload=payload)

    assert "Completion status is ambiguous" in str(exc_info.value)
    assert exc_info.value.details["is_ambiguous"] is True


# ── Matrix I: Cache Coherence & Rollback ───────────────────────────────────


def test_matrix_i_cache_coherence_and_rollback(persistence, store):
    """Verify rollback invalidates cache and does not leave uncommitted state in memory."""
    key = "op:cache:test_rollback"
    op_id = operation_id_for_key(key)
    payload = {"foo": "bar"}

    # Transaction that rolls back
    try:
        with persistence.transaction():
            store.claim_operation(key, request_payload=payload)
            # Verify cache has it during transaction
            cached_during = persistence.cache.get(EntityType.IDEMPOTENT_OPERATION, op_id)
            assert cached_during is not None
            # Force failure and rollback
            raise ValueError("Intentional rollback")
    except ValueError:
        pass

    # After rollback: cache must be invalidated and persistent store must not have it
    cached_after = persistence.cache.get(EntityType.IDEMPOTENT_OPERATION, op_id)
    assert cached_after is None
    assert store.try_get_operation(op_id) is None


def test_matrix_i_cache_hit_equals_fresh_read(persistence, store):
    """Verify cache hits match fresh persistent store reads."""
    key = "op:cache:hit_test"
    op_id = operation_id_for_key(key)
    payload = {"val": 42}

    store.claim_operation(key, request_payload=payload)
    # Read from cache
    read1 = store.get_operation(op_id)

    # Invalidate cache manually to test database fallback
    persistence.cache.invalidate(EntityType.IDEMPOTENT_OPERATION, op_id)
    read2 = store.get_operation(op_id)

    assert read1.operation_id == read2.operation_id
    assert read1.status == read2.status
    assert read1.request_fingerprint == read2.request_fingerprint


# ── Matrix K: Audit & Replay Safety ───────────────────────────────────────


def test_matrix_k_audit_history_records_lifecycle(persistence, store):
    """Verify transitions are recorded in immutable history log."""
    key = "op:audit:trace_lifecycle"
    payload = {"item": "widget"}

    claim = store.claim_operation(key, request_payload=payload)
    op_id = claim.operation_id
    store.complete_operation(op_id, result={"ok": True})

    transitions = persistence.history.read_by_entity(EntityType.IDEMPOTENT_OPERATION, op_id)
    actions = [t.metadata.get("action") for t in transitions]

    assert "operation.claimed" in actions
    assert "operation.completed" in actions
    assert len(transitions) == 2


# ── SideEffectExecutor Tests ──────────────────────────────────────────────


def test_side_effect_executor_executes_once_and_caches(store):
    """Verify SideEffectExecutor executes handler once, caches result, and does not re-run."""
    executor = SideEffectExecutor(store)
    call_count = 0

    def mock_payment_api(req, **kwargs):
        nonlocal call_count
        call_count += 1
        return {"payment_id": f"pay_{call_count}", "status": "approved"}

    req_payload = {"invoice": "INV-101", "amount": 99.95}

    # First execution
    res1 = executor.execute("pay_invoice", req_payload, mock_payment_api)
    assert call_count == 1
    assert res1["payment_id"] == "pay_1"

    # Second execution with same parameters -> handler MUST NOT be called again
    res2 = executor.execute("pay_invoice", req_payload, mock_payment_api)
    assert call_count == 1
    assert res2 == res1


@pytest.mark.asyncio
async def test_async_side_effect_executor(store):
    """Verify async side-effect executor supports async handlers and propagates provider key."""
    executor = SideEffectExecutor(store)
    observed_provider_key = None

    async def mock_async_service(req, provider_idempotency_key=None, **kwargs):
        nonlocal observed_provider_key
        observed_provider_key = provider_idempotency_key
        return {"external_id": "ext-7788", "processed": True}

    req = {"data": "hello"}
    res = await executor.execute_async("async_op", req, mock_async_service)

    assert res["processed"] is True
    assert observed_provider_key is not None
    assert observed_provider_key.startswith("op:generic:async_op")
