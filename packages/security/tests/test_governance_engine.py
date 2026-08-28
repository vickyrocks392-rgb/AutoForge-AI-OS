"""
Unit tests for GovernancePolicyEngine and consequential action gating.
"""

from __future__ import annotations

import pytest

from autoforge_security.errors import SelfApprovalForbiddenError
from autoforge_security.governance import GovernancePolicyEngine
from autoforge_security.models import (
    ConsequentialAction,
    DecisionType,
    GovernancePolicy,
    Subject,
    SubjectType,
)
from autoforge_security.roles import Roles


def test_consequential_actions_gated_by_default(
    governance_engine: GovernancePolicyEngine,
    sample_human_engineer: Subject,
    sample_worker_subject: Subject,
) -> None:
    # Worker attempting tech stack finalization -> REQUIRE_HITL
    decision_worker = governance_engine.evaluate_consequential_action(
        action=ConsequentialAction.TECH_STACK_FINALIZATION,
        subject=sample_worker_subject,
        has_approved_gate=False,
    )
    assert decision_worker.is_allowed is False
    assert decision_worker.decision == DecisionType.REQUIRE_HITL
    assert "Worker" in decision_worker.reason

    # Human attempting deployment without gate -> REQUIRE_HITL
    decision_human = governance_engine.evaluate_consequential_action(
        action=ConsequentialAction.DEPLOYMENT,
        subject=sample_human_engineer,
        has_approved_gate=False,
    )
    assert decision_human.is_allowed is False
    assert decision_human.decision == DecisionType.REQUIRE_HITL

    # Action with approved gate -> ALLOW
    decision_approved = governance_engine.evaluate_consequential_action(
        action=ConsequentialAction.DEPLOYMENT,
        subject=sample_human_engineer,
        has_approved_gate=True,
    )
    assert decision_approved.is_allowed is True
    assert decision_approved.decision == DecisionType.ALLOW


def test_ai_worker_self_approval_forbidden(
    governance_engine: GovernancePolicyEngine,
    sample_worker_subject: Subject,
) -> None:
    with pytest.raises(SelfApprovalForbiddenError) as exc_info:
        governance_engine.validate_human_approver(
            approver=sample_worker_subject,
            gate_requestor_id="some_requestor",
        )
    assert "AI models and workers are prohibited" in str(exc_info.value) or "cannot approve HITL gates" in str(exc_info.value)
