"""
Phase 9 — Approval gate tests.

Covers:
- Gate creation and initial state.
- approve() single approver.
- Multi-approver approval (requires N approvals).
- reject() immediately closes gate.
- timeout() transitions to TIMED_OUT.
- Double-decide on terminal gate raises ApprovalError.
- is_resolved predicate.
- is_timed_out_now() with short timeout.
- Snapshot / restore round-trip.
"""

from __future__ import annotations

import time
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from autoforge_workflows.approval import (
    ApprovalDecision,
    ApprovalGate,
    ApprovalOutcome,
    ApprovalStatus,
)
from autoforge_workflows.errors import ApprovalError


def _make_gate(
    gate_id: str = "gate-1",
    task_id: str = "task-1",
    required_approvers: int = 1,
    timeout_seconds: float | None = None,
) -> ApprovalGate:
    return ApprovalGate(
        gate_id=gate_id,
        task_id=task_id,
        workflow_id=uuid.uuid4(),
        required_approvers=required_approvers,
        timeout_seconds=timeout_seconds,
    )


def _approve(decided_by: str = "alice") -> ApprovalDecision:
    return ApprovalDecision(outcome=ApprovalOutcome.APPROVED, decided_by=decided_by)


def _reject(decided_by: str = "bob", reason: str = "") -> ApprovalDecision:
    return ApprovalDecision(outcome=ApprovalOutcome.REJECTED, decided_by=decided_by, reason=reason)


class TestApprovalGateCreation:
    """Tests for initial gate state."""

    def test_initial_status(self) -> None:
        gate = _make_gate()
        assert gate.status == ApprovalStatus.PENDING_APPROVAL

    def test_not_resolved_initially(self) -> None:
        gate = _make_gate()
        assert gate.is_resolved is False

    def test_approval_count_zero(self) -> None:
        gate = _make_gate()
        assert gate.approval_count == 0
        assert gate.rejection_count == 0


class TestSingleApprover:
    """Tests for single-approver gates."""

    def test_approve_transitions_to_approved(self) -> None:
        gate = _make_gate()
        new_status = gate.decide(_approve())
        assert new_status == ApprovalStatus.APPROVED
        assert gate.status == ApprovalStatus.APPROVED
        assert gate.is_resolved is True

    def test_reject_transitions_to_rejected(self) -> None:
        gate = _make_gate()
        new_status = gate.decide(_reject())
        assert new_status == ApprovalStatus.REJECTED
        assert gate.status == ApprovalStatus.REJECTED

    def test_approval_count_increments(self) -> None:
        gate = _make_gate()
        gate.decide(_approve())
        assert gate.approval_count == 1

    def test_rejection_count_increments(self) -> None:
        gate = _make_gate()
        gate.decide(_reject())
        assert gate.rejection_count == 1


class TestMultiApprover:
    """Tests for multi-approver gates (required_approvers > 1)."""

    def test_partial_approval_stays_pending(self) -> None:
        gate = _make_gate(required_approvers=2)
        gate.decide(_approve("alice"))
        assert gate.status == ApprovalStatus.PENDING_APPROVAL

    def test_full_approval_transitions_to_approved(self) -> None:
        gate = _make_gate(required_approvers=2)
        gate.decide(_approve("alice"))
        gate.decide(_approve("bob"))
        assert gate.status == ApprovalStatus.APPROVED

    def test_reject_before_full_approval_closes_gate(self) -> None:
        gate = _make_gate(required_approvers=2)
        gate.decide(_approve("alice"))
        gate.decide(_reject("bob"))
        assert gate.status == ApprovalStatus.REJECTED


class TestTerminalGate:
    """Tests for double-decide on terminal gate."""

    def test_decide_on_approved_gate_raises(self) -> None:
        gate = _make_gate()
        gate.decide(_approve())
        with pytest.raises(ApprovalError):
            gate.decide(_approve())

    def test_decide_on_rejected_gate_raises(self) -> None:
        gate = _make_gate()
        gate.decide(_reject())
        with pytest.raises(ApprovalError):
            gate.decide(_approve())

    def test_timeout_on_terminal_gate_raises(self) -> None:
        gate = _make_gate()
        gate.decide(_approve())
        with pytest.raises(ApprovalError):
            gate.timeout()


class TestTimeout:
    """Tests for timeout handling."""

    def test_timeout_transitions_to_timed_out(self) -> None:
        gate = _make_gate()
        gate.timeout()
        assert gate.status == ApprovalStatus.TIMED_OUT
        assert gate.is_resolved is True

    def test_is_timed_out_now_no_timeout_config(self) -> None:
        gate = _make_gate(timeout_seconds=None)
        assert gate.is_timed_out_now() is False

    def test_is_timed_out_now_with_very_short_timeout(self) -> None:
        # Gate with 0.001 second timeout should be expired.
        wf_id = uuid.uuid4()
        gate = ApprovalGate(
            gate_id="g1",
            task_id="t1",
            workflow_id=wf_id,
            timeout_seconds=0.001,
            created_at=datetime.now(timezone.utc) - timedelta(seconds=1),
        )
        assert gate.is_timed_out_now() is True

    def test_is_timed_out_now_not_expired(self) -> None:
        gate = _make_gate(timeout_seconds=3600.0)  # 1 hour
        assert gate.is_timed_out_now() is False


class TestSnapshotRestore:
    """Tests for ApprovalGate snapshot / restore round-trip."""

    def test_pending_gate_round_trip(self) -> None:
        gate = _make_gate()
        snap = gate.to_snapshot()
        restored = ApprovalGate.from_snapshot(snap)
        assert restored.gate_id == gate.gate_id
        assert restored.task_id == gate.task_id
        assert restored.status == ApprovalStatus.PENDING_APPROVAL

    def test_approved_gate_round_trip(self) -> None:
        gate = _make_gate()
        gate.decide(_approve("charlie"))
        snap = gate.to_snapshot()
        restored = ApprovalGate.from_snapshot(snap)
        assert restored.status == ApprovalStatus.APPROVED
        assert restored.approval_count == 1
        assert restored.decisions[0].decided_by == "charlie"

    def test_rejected_gate_round_trip(self) -> None:
        gate = _make_gate()
        gate.decide(_reject("dave", reason="policy violation"))
        snap = gate.to_snapshot()
        restored = ApprovalGate.from_snapshot(snap)
        assert restored.status == ApprovalStatus.REJECTED
        assert restored.decisions[0].reason == "policy violation"
