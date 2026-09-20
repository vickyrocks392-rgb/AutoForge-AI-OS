"""Concurrency and Subprocess Crash Tests for Durable Idempotency (Phase 18-J.4).

Covers Matrix:
- G: Concurrent Processes & Threads
  - Multiple threads competing for the same idempotency key (exactly one claimant wins).
  - Multiple OS subprocesses competing for the same idempotency key against the real SQLite file.
- H: Subprocess Crash During Side-Effect Execution
  - Real OS subprocess abruptly killed (SIGKILL / os._exit) mid-execution.
  - New process starts, reconciles durable state.
  - Operation verified not completed, reconciled to INTERRUPTED, and resumed under same logical key.
"""

import concurrent.futures
import multiprocessing
import os
from pathlib import Path
import sys
import uuid
import pytest

from autoforge_runtime.idempotency import (
    ConcurrentOperationError,
    DurableIdempotencyStore,
    derive_idempotency_key,
    operation_id_for_key,
)
from autoforge_runtime.models import (
    EntityType,
    IdempotentOperationState,
    OperationStatus,
)
from autoforge_runtime.persistence import PersistenceLayer


@pytest.fixture
def temp_db_file(tmp_path):
    return str(tmp_path / "concurrent_idempotency.db")


# ── Subprocess Worker Helpers ─────────────────────────────────────────────


def _worker_compete_claim(db_path: str, key: str, payload: dict, result_queue: multiprocessing.Queue):
    """Subprocess worker that attempts to claim an idempotency key."""
    try:
        p = PersistenceLayer(db_path)
        store = DurableIdempotencyStore(p, owner_id=f"proc-host:{os.getpid()}")
        try:
            claim = store.claim_operation(key, request_payload=payload)
            result_queue.put({"success": True, "claimed": claim.claimed, "owner": store.owner_id})
        except ConcurrentOperationError:
            result_queue.put({"success": True, "claimed": False, "reason": "concurrent_duplicate"})
        except Exception as exc:
            result_queue.put({"success": False, "error": str(exc)})
        finally:
            p.close()
    except Exception as exc:
        result_queue.put({"success": False, "error": str(exc)})


def _worker_crash_during_execution(db_path: str, key: str, payload: dict, sync_file: str):
    """Subprocess worker that claims an operation and immediately terminates abruptly via os._exit."""
    p = PersistenceLayer(db_path)
    store = DurableIdempotencyStore(p, owner_id=f"crash-host:{os.getpid()}")
    try:
        claim = store.claim_operation(key, request_payload=payload, supports_provider_idempotency=True)
        # Notify parent that claim is committed to SQLite
        Path(sync_file).write_text(str(claim.operation_id))
        sys.stdout.flush()
        # Simulate abrupt process crash during external side effect (bypassing normal Python exit)
        os._exit(42)
    finally:
        pass


# ── Matrix G: Concurrent Claim Tests ──────────────────────────────────────


def test_matrix_g_cross_thread_concurrency(temp_db_file):
    """Verify that among concurrent threads, exactly ONE obtains the side-effect claim."""
    p = PersistenceLayer(temp_db_file)

    key = "op:thread_test:single_winner"
    payload = {"account_id": "acc_100"}

    def attempt_claim(worker_idx: int):
        thread_store = DurableIdempotencyStore(p, owner_id=f"host:{os.getpid()}:thread-{worker_idx}")
        try:
            res = thread_store.claim_operation(key, request_payload=payload)
            return {"claimed": res.claimed, "status": res.status.value}
        except ConcurrentOperationError:
            return {"claimed": False, "status": "rejected_concurrent"}

    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool:
        futures = [pool.submit(attempt_claim, i) for i in range(5)]
        outcomes = [f.result() for f in futures]

    claimed_count = sum(1 for o in outcomes if o["claimed"] is True)
    assert claimed_count == 1, f"Expected exactly 1 winner, got: {outcomes}"
    p.close()


def test_matrix_g_cross_process_concurrency(temp_db_file):
    """Verify that across multiple independent OS subprocesses, exactly ONE wins the claim."""
    ctx = multiprocessing.get_context("spawn")
    queue = ctx.Queue()

    key = "op:proc_test:single_winner"
    payload = {"data": "cross-process"}

    num_procs = 4
    processes = []
    for _ in range(num_procs):
        proc = ctx.Process(
            target=_worker_compete_claim,
            args=(temp_db_file, key, payload, queue),
        )
        processes.append(proc)

    # Launch all processes simultaneously
    for proc in processes:
        proc.start()

    for proc in processes:
        proc.join(timeout=10)

    results = []
    while not queue.empty():
        results.append(queue.get())

    assert len(results) == num_procs
    winners = [r for r in results if r.get("claimed") is True]
    assert len(winners) == 1, f"Expected exactly 1 cross-process winner, got {len(winners)}: {results}"


# ── Matrix H: Subprocess Crash & Recovery Test ─────────────────────────────


def test_matrix_h_real_subprocess_crash_and_recovery(temp_db_file, tmp_path):
    """Verify that when a process crashes abruptly during a claimed side effect:
    1. The operation is committed as RUNNING before the crash.
    2. The new process detects the crash.
    3. The operation is NOT incorrectly marked as COMPLETED.
    4. Startup reconciliation marks it as INTERRUPTED.
    5. The operation can be resumed under the SAME logical operation key.
    """
    ctx = multiprocessing.get_context("spawn")
    sync_file = str(tmp_path / "sync.txt")

    key = "op:crash_test:payment"
    payload = {"amount": 500, "recipient": "vendor_xyz"}

    # 1. Start worker that crashes mid-execution
    proc = ctx.Process(
        target=_worker_crash_during_execution,
        args=(temp_db_file, key, payload, sync_file),
    )
    proc.start()
    proc.join(timeout=10)

    # Verify process terminated with non-zero code (abrupt termination)
    assert proc.exitcode == 42

    # Read op_id written before crash
    op_id_str = Path(sync_file).read_text().strip()
    op_id = uuid.UUID(op_id_str)

    # 2. Start a fresh new process / persistence layer
    p_restart = PersistenceLayer(temp_db_file)
    store_restart = DurableIdempotencyStore(p_restart, owner_id="host:new-process")

    # 3. Read durable state: operation MUST NOT be completed!
    state_after_crash = store_restart.get_operation(op_id)
    assert state_after_crash.status == OperationStatus.RUNNING
    assert state_after_crash.status != OperationStatus.COMPLETED

    # 4. Reconcile dead owners
    reconciled = store_restart.reconcile_interrupted_operations()
    assert len(reconciled) == 1
    assert reconciled[0].operation_id == op_id
    assert reconciled[0].status == OperationStatus.INTERRUPTED
    assert reconciled[0].is_ambiguous is False  # Because supports_provider_idempotency=True

    # 5. Resume the operation under the SAME logical idempotency key
    resume_claim = store_restart.claim_operation(key, request_payload=payload)
    assert resume_claim.claimed is True
    assert resume_claim.resumed is True
    assert resume_claim.status == OperationStatus.RUNNING
    assert resume_claim.operation_id == op_id  # SAME LOGICAL OPERATION!

    # 6. Complete the operation
    final_state = store_restart.complete_operation(
        op_id,
        result={"transaction_id": "tx_reconciled_123", "success": True},
    )
    assert final_state.status == OperationStatus.COMPLETED
    assert final_state.result["transaction_id"] == "tx_reconciled_123"

    p_restart.close()
