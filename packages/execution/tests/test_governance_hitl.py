"""
Unit tests for ExecutionGovernance and HITL approval gating.
"""

import pytest
from autoforge_workflows.approval import ApprovalDecision, ApprovalOutcome, ApprovalStatus

from autoforge_execution.errors import GovernanceApprovalRequired
from autoforge_execution.governance import ExecutionGovernance
from autoforge_execution.models import ConsequentialActionType, GovernancePolicy


def test_governance_policy_checks():
    gov = ExecutionGovernance()
    assert gov.requires_approval(ConsequentialActionType.TECH_STACK_FINALIZATION)
    assert gov.requires_approval(ConsequentialActionType.GIT_PUSH)
    assert not gov.requires_approval(ConsequentialActionType.GIT_COMMIT)


def test_governance_approval_required_flow():
    gov = ExecutionGovernance()

    with pytest.raises(GovernanceApprovalRequired) as exc_info:
        gov.check_and_gate_action(
            action_type=ConsequentialActionType.TECH_STACK_FINALIZATION,
            task_id="task-tech-stack",
            description="Approve Next.js + FastAPI tech stack",
        )

    gate_id = exc_info.value.details["gate_id"]
    assert gate_id is not None
    gate = gov.get_gate(gate_id)
    assert gate is not None
    assert gate.status == ApprovalStatus.PENDING_APPROVAL

    # Human approves
    decision = ApprovalDecision(
        outcome=ApprovalOutcome.APPROVED,
        decided_by="lead_architect@autoforge.ai",
        reason="Approved architecture tech stack",
    )
    status = gov.submit_decision(gate_id, decision)
    assert status == ApprovalStatus.APPROVED

    # Re-checking now passes
    allowed = gov.check_and_gate_action(
        action_type=ConsequentialActionType.TECH_STACK_FINALIZATION,
        task_id="task-tech-stack",
        gate_id=gate_id,
    )
    assert allowed is True


def test_governance_rejection_flow():
    gov = ExecutionGovernance()

    with pytest.raises(GovernanceApprovalRequired) as exc_info:
        gov.check_and_gate_action(
            action_type=ConsequentialActionType.GIT_PUSH,
            task_id="task-push",
        )

    gate_id = exc_info.value.details["gate_id"]

    decision = ApprovalDecision(
        outcome=ApprovalOutcome.REJECTED,
        decided_by="security_admin@autoforge.ai",
        reason="Branch not ready",
    )
    status = gov.submit_decision(gate_id, decision)
    assert status == ApprovalStatus.REJECTED

    allowed = gov.check_and_gate_action(
        action_type=ConsequentialActionType.GIT_PUSH,
        task_id="task-push",
        gate_id=gate_id,
    )
    assert allowed is False
