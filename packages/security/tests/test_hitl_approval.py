"""
Unit tests for HITLManager, gate lifecycle, multi-approver, and resume tokens.
"""

from __future__ import annotations

import pytest

from autoforge_security.errors import (
    ApprovalGateExpiredError,
    GovernanceError,
    SelfApprovalForbiddenError,
)
from autoforge_security.hitl import HITLManager
from autoforge_security.models import (
    ApprovalGateStatus,
    ConsequentialAction,
    Subject,
    SubjectType,
)
from autoforge_security.roles import Roles


def test_hitl_approval_lifecycle(
    hitl_manager: HITLManager,
    sample_human_engineer: Subject,
    sample_human_reviewer: Subject,
) -> None:
    # 1. Create gate
    gate = hitl_manager.create_gate(
        action=ConsequentialAction.ARCHITECTURE_FINALIZATION,
        requested_by=sample_human_engineer,
        description="Finalize target microservices architecture.",
        project_id="proj_legacy_01",
    )
    assert gate.status == ApprovalGateStatus.PENDING
    assert gate.resume_token is None

    # 2. Check pending list
    pending = hitl_manager.list_pending_gates(project_id="proj_legacy_01")
    assert len(pending) == 1
    assert pending[0].gate_id == gate.gate_id

    # 3. Reviewer approves
    updated = hitl_manager.submit_decision(
        gate_id=gate.gate_id,
        approver=sample_human_reviewer,
        status=ApprovalGateStatus.APPROVED,
        reason="Architecture thoroughly validated and compliant with standards.",
    )
    assert updated.status == ApprovalGateStatus.APPROVED
    assert updated.resume_token is not None
    assert updated.resume_token.startswith("rst_")

    # 4. Verify resume token
    assert hitl_manager.verify_resume_token(gate.gate_id, updated.resume_token) is True
    assert hitl_manager.verify_resume_token(gate.gate_id, "forged_token") is False


def test_hitl_rejection(
    hitl_manager: HITLManager,
    sample_human_engineer: Subject,
    sample_human_reviewer: Subject,
) -> None:
    gate = hitl_manager.create_gate(
        action=ConsequentialAction.DEPLOYMENT,
        requested_by=sample_human_engineer,
        description="Production cutover deployment.",
    )

    rejected_gate = hitl_manager.submit_decision(
        gate_id=gate.gate_id,
        approver=sample_human_reviewer,
        status=ApprovalGateStatus.REJECTED,
        reason="Security audit unresolved.",
    )
    assert rejected_gate.status == ApprovalGateStatus.REJECTED
    assert rejected_gate.resume_token is None


def test_worker_cannot_approve(
    hitl_manager: HITLManager,
    sample_human_engineer: Subject,
    sample_worker_subject: Subject,
) -> None:
    gate = hitl_manager.create_gate(
        action=ConsequentialAction.MIGRATION_EXECUTION,
        requested_by=sample_human_engineer,
        description="Execute database migration.",
    )

    with pytest.raises(SelfApprovalForbiddenError):
        hitl_manager.submit_decision(
            gate_id=gate.gate_id,
            approver=sample_worker_subject,
            status=ApprovalGateStatus.APPROVED,
        )


def test_gate_expiry(
    hitl_manager: HITLManager,
    sample_human_engineer: Subject,
    sample_human_reviewer: Subject,
) -> None:
    # TTL of 0 seconds triggers instant expiration
    gate = hitl_manager.create_gate(
        action=ConsequentialAction.DEPLOYMENT,
        requested_by=sample_human_engineer,
        description="Deploy",
        ttl_seconds=-10,
    )

    with pytest.raises(ApprovalGateExpiredError):
        hitl_manager.submit_decision(
            gate_id=gate.gate_id,
            approver=sample_human_reviewer,
            status=ApprovalGateStatus.APPROVED,
        )
