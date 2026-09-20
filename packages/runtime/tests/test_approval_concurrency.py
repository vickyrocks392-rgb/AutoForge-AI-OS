"""Concurrency Tests for Durable Human-In-The-Loop Approval (Phase 18-J.5).

Covers Matrix:
- G: Concurrent Processes & Threads
  - Multiple threads competing to decide the same approval request (exactly one terminal decision wins).
  - Multiple OS subprocesses competing to decide the same approval request against a real SQLite database.
  - Conflicting decision attempts (APPROVE vs REJECT) receive deterministic conflict errors.
"""

from __future__ import annotations

import concurrent.futures
import multiprocessing
import os
import uuid
from pathlib import Path
from typing import Any

import pytest
from autoforge_runtime.approval_store import (
    ApprovalConflictError,
    DurableApprovalStore,
    derive_approval_key,
)
from autoforge_runtime.models import DurableApprovalStatus
from autoforge_runtime.persistence import PersistenceLayer


@pytest.fixture
def temp_db_file(tmp_path: Path) -> str:
    return str(tmp_path / "concurrent_approval.db")


# ── Subprocess Worker Helper ─────────────────────────────────────────────


def _worker_compete_decision(
    db_path: str,
    approval_id_str: str,
    outcome: str,
    decided_by: str,
    result_queue: multiprocessing.Queue,
) -> None:
    """Subprocess worker that attempts to submit a decision."""
    app_uuid = uuid.UUID(approval_id_str)
    try:
        p = PersistenceLayer(db_path)
        store = DurableApprovalStore(p, owner_id=f"proc:{os.getpid()}")
        try:
            res = store.submit_decision(
                app_uuid,
                outcome=outcome,
                decided_by=decided_by,
                reason=f"Decided by {decided_by}",
            )
            result_queue.put({
                "success": True,
                "winner": True,
                "outcome": res.status.value,
                "decided_by": res.resolved_by,
            })
        except ApprovalConflictError as exc:
            result_queue.put({
                "success": True,
                "winner": False,
                "reason": "conflict_rejection",
                "details": str(exc),
            })
        except Exception as exc:
            result_queue.put({
                "success": False,
                "error": str(exc),
            })
        finally:
            p.close()
    except Exception as exc:
        result_queue.put({
            "success": False,
            "error": str(exc),
        })


# ── Cross-Thread Concurrency Tests ────────────────────────────────────────


def test_cross_thread_concurrent_conflicting_decisions(temp_db_file: str) -> None:
    """Multiple threads attempting conflicting decisions (APPROVE vs REJECT) on the same gate.

    Exactly ONE terminal decision must win, and the losers must receive conflict rejections.
    """
    p = PersistenceLayer(temp_db_file)
    store = DurableApprovalStore(p, owner_id="main-thread")

    req = store.create_approval_request(
        gate_id="gate_race_thread",
        task_id="task_race",
        request_payload={"action": "deploy"},
    )
    p.close()

    def decide_worker(worker_id: int) -> dict[str, Any]:
        worker_p = PersistenceLayer(temp_db_file)
        worker_store = DurableApprovalStore(worker_p, owner_id=f"worker-thread-{worker_id}")
        outcome = DurableApprovalStatus.APPROVED if worker_id % 2 == 0 else DurableApprovalStatus.REJECTED
        decider = f"user_{worker_id}"
        try:
            res = worker_store.submit_decision(
                req.approval_id,
                outcome=outcome,
                decided_by=decider,
                reason=f"Vote from {decider}",
            )
            return {
                "worker_id": worker_id,
                "won": True,
                "decision": res.status.value,
                "decided_by": res.resolved_by,
            }
        except ApprovalConflictError:
            return {
                "worker_id": worker_id,
                "won": False,
                "decision": "rejected_by_conflict",
            }
        finally:
            worker_p.close()

    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
        futures = [pool.submit(decide_worker, i) for i in range(6)]
        outcomes = [f.result() for f in futures]

    winners = [o for o in outcomes if o["won"] is True]
    assert len(winners) == 1, f"Expected exactly 1 winning decision, got: {outcomes}"

    # Verify state in DB
    final_p = PersistenceLayer(temp_db_file)
    final_store = DurableApprovalStore(final_p)
    final_req = final_store.get_approval_request(req.approval_id)
    assert final_req is not None
    assert final_req.status.value in {"approved", "rejected"}
    assert final_req.resolved_by == winners[0]["decided_by"]
    final_p.close()


# ── Cross-Process Concurrency Tests ──────────────────────────────────────


def test_cross_process_concurrent_decisions(temp_db_file: str) -> None:
    """Multiple independent OS processes competing to decide the same approval request.

    Proves transactional exclusion and durability across real OS process boundaries.
    """
    p = PersistenceLayer(temp_db_file)
    store = DurableApprovalStore(p, owner_id="init-proc")
    req = store.create_approval_request(
        gate_id="gate_multiprocess_race",
        task_id="task_proc",
        request_payload={"action": "reboot_cluster"},
    )
    p.close()

    queue: multiprocessing.Queue = multiprocessing.Queue()
    procs = []

    # Launch 4 competing processes with differing outcomes
    tasks = [
        ("approved", "operator_alpha"),
        ("rejected", "operator_beta"),
        ("approved", "operator_gamma"),
        ("rejected", "operator_delta"),
    ]

    for outcome, user in tasks:
        proc = multiprocessing.Process(
            target=_worker_compete_decision,
            args=(temp_db_file, str(req.approval_id), outcome, user, queue),
        )
        procs.append(proc)
        proc.start()

    for proc in procs:
        proc.join(timeout=10)
        assert proc.exitcode == 0

    results = []
    while not queue.empty():
        results.append(queue.get_nowait())

    assert len(results) == 4, f"Expected 4 results, got {len(results)}"
    for r in results:
        assert r["success"] is True

    winners = [r for r in results if r.get("winner") is True]
    assert len(winners) == 1, f"Expected exactly 1 winner across processes, got: {results}"

    # Confirm final database state matches the winning process
    verify_p = PersistenceLayer(temp_db_file)
    verify_store = DurableApprovalStore(verify_p)
    saved = verify_store.get_approval_request(req.approval_id)
    assert saved is not None
    assert saved.status.value == winners[0]["outcome"]
    assert saved.resolved_by == winners[0]["decided_by"]
    verify_p.close()
