"""D1 regression tests: GateCondition class structure & GateDecisionRecord.evaluate().

These tests cover the D1 fix: GateCondition was previously truncated to only
three fields (condition_id, kind, description) with the rest of the class body
(status, blocking_reason, is_satisfied, is_blocked, etc.) living at module
scope. The fix moved the state-machine fields and methods back into the class
body. GateDecisionRecord.evaluate() must work end-to-end through real condition
objects.
"""
from __future__ import annotations

import pytest

from autoforge_modernization.planning_gate import (
    GateCondition,
    GateConditionKind,
    GateConditionStatus,
    GateDecision,
    GateDecisionRecord,
)


class TestGateConditionStructure:
    """GateCondition must contain all expected fields and methods."""

    def test_has_status_field(self):
        c = GateCondition(kind=GateConditionKind.REQUIREMENTS_CONFIRMED, description="x")
        assert hasattr(c, "status")
        assert c.status == GateConditionStatus.PENDING

    def test_has_blocking_reason_field(self):
        c = GateCondition(kind=GateConditionKind.REQUIREMENTS_CONFIRMED, description="x")
        assert hasattr(c, "blocking_reason")
        assert c.blocking_reason is None

    def test_has_blocking_finding_ids(self):
        c = GateCondition(kind=GateConditionKind.REQUIREMENTS_CONFIRMED, description="x")
        assert hasattr(c, "blocking_finding_ids")
        assert c.blocking_finding_ids == []

    def test_has_blocking_requirement_ids(self):
        c = GateCondition(kind=GateConditionKind.REQUIREMENTS_CONFIRMED, description="x")
        assert hasattr(c, "blocking_requirement_ids")
        assert c.blocking_requirement_ids == []

    def test_has_satisfied_by_field(self):
        c = GateCondition(kind=GateConditionKind.REQUIREMENTS_CONFIRMED, description="x")
        assert hasattr(c, "satisfied_by")
        assert c.satisfied_by is None

    def test_has_waiver_fields(self):
        c = GateCondition(kind=GateConditionKind.REQUIREMENTS_CONFIRMED, description="x")
        assert hasattr(c, "waived_by")
        assert hasattr(c, "waiver_reason")
        assert c.waived_by is None
        assert c.waiver_reason is None

    def test_has_hitl_fields(self):
        c = GateCondition(kind=GateConditionKind.REQUIREMENTS_CONFIRMED, description="x")
        assert hasattr(c, "is_hitl_required")
        assert hasattr(c, "required_approvers")
        assert c.is_hitl_required is False
        assert c.required_approvers == []

    def test_is_satisfied_method_true(self):
        c = GateCondition(
            kind=GateConditionKind.REQUIREMENTS_CONFIRMED, description="x",
            status=GateConditionStatus.SATISFIED,
        )
        assert c.is_satisfied() is True
        assert c.is_blocked() is False

    def test_is_blocked_method_true(self):
        c = GateCondition(
            kind=GateConditionKind.REQUIREMENTS_CONFIRMED, description="x",
            status=GateConditionStatus.BLOCKED, blocking_reason="missing req",
        )
        assert c.is_blocked() is True
        assert c.is_satisfied() is False

    def test_default_status_is_pending(self):
        c = GateCondition(kind=GateConditionKind.REQUIREMENTS_CONFIRMED, description="x")
        assert c.status == GateConditionStatus.PENDING
        assert c.is_satisfied() is False
        assert c.is_blocked() is False


class TestGateDecisionRecordEvaluate:
    """evaluate() must run the real condition path, not be bypassed."""

    def test_evaluate_approved_for_satisfied_conditions(self):
        rec = GateDecisionRecord(project_id="p1", conditions=[
            GateCondition(
                kind=GateConditionKind.REQUIREMENTS_CONFIRMED, description="r",
                status=GateConditionStatus.SATISFIED,
            ),
            GateCondition(
                kind=GateConditionKind.BUSINESS_INTENT_RESOLVED, description="i",
                status=GateConditionStatus.SATISFIED,
            ),
        ])
        d = rec.evaluate()
        assert d == GateDecision.APPROVED
        assert rec.satisfied_count == 2
        assert rec.blocked_count == 0

    def test_evaluate_blocked_for_blocking_condition(self):
        rec = GateDecisionRecord(project_id="p2", conditions=[
            GateCondition(
                kind=GateConditionKind.REQUIREMENTS_CONFIRMED, description="r",
                status=GateConditionStatus.SATISFIED,
            ),
            GateCondition(
                kind=GateConditionKind.BUSINESS_INTENT_RESOLVED, description="i",
                status=GateConditionStatus.BLOCKED, blocking_reason="unresolved",
            ),
        ])
        d = rec.evaluate()
        assert d == GateDecision.BLOCKED
        assert rec.blocked_count == 1

    def test_unresolved_business_intent_not_auto_approved(self):
        rec = GateDecisionRecord(project_id="p3", conditions=[
            GateCondition(
                kind=GateConditionKind.REQUIREMENTS_CONFIRMED, description="r",
                status=GateConditionStatus.SATISFIED,
            ),
            GateCondition(
                kind=GateConditionKind.BUSINESS_INTENT_RESOLVED, description="bi",
                status=GateConditionStatus.BLOCKED, blocking_reason="unresolved",
            ),
        ])
        d = rec.evaluate()
        assert d == GateDecision.BLOCKED
        assert d != GateDecision.APPROVED

    def test_all_conditions_participate_in_decision(self):
        rec = GateDecisionRecord(project_id="p4", conditions=[
            GateCondition(kind=GateConditionKind.REQUIREMENTS_CONFIRMED, description="r",
                status=GateConditionStatus.SATISFIED),
            GateCondition(kind=GateConditionKind.BUSINESS_RULES_RESOLVED, description="br",
                status=GateConditionStatus.SATISFIED),
            GateCondition(kind=GateConditionKind.CURRENT_BEHAVIOR_MODELED, description="cb",
                status=GateConditionStatus.SATISFIED),
            GateCondition(kind=GateConditionKind.BUSINESS_INTENT_RESOLVED, description="bi",
                status=GateConditionStatus.SATISFIED),
            GateCondition(kind=GateConditionKind.GAP_FINDINGS_APPROVED, description="gf",
                status=GateConditionStatus.SATISFIED),
        ])
        d = rec.evaluate()
        assert d == GateDecision.APPROVED
        assert rec.satisfied_count == 5
        assert rec.total_conditions == 5
        assert rec.blocked_count == 0

    def test_hitl_required_without_approval_blocks(self):
        rec = GateDecisionRecord(
            project_id="p5", hitl_required=True, hitl_approved=False,
            conditions=[GateCondition(
                kind=GateConditionKind.REQUIREMENTS_CONFIRMED, description="r",
                status=GateConditionStatus.SATISFIED,
            )],
        )
        assert rec.evaluate() == GateDecision.BLOCKED

    def test_hitl_required_with_approval_approves(self):
        rec = GateDecisionRecord(
            project_id="p6", hitl_required=True, hitl_approved=True,
            conditions=[GateCondition(
                kind=GateConditionKind.REQUIREMENTS_CONFIRMED, description="r",
                status=GateConditionStatus.SATISFIED,
            )],
        )
        assert rec.evaluate() == GateDecision.APPROVED

    def test_not_applicable_condition_does_not_block(self):
        rec = GateDecisionRecord(project_id="p7", conditions=[
            GateCondition(kind=GateConditionKind.REQUIREMENTS_CONFIRMED, description="r",
                status=GateConditionStatus.SATISFIED),
            GateCondition(kind=GateConditionKind.PLANNING_GATE_MANUAL, description="m",
                status=GateConditionStatus.NOT_APPLICABLE),
        ])
        assert rec.evaluate() == GateDecision.APPROVED

    def test_pending_returns_pending_not_approved(self):
        rec = GateDecisionRecord(project_id="p8", conditions=[
            GateCondition(kind=GateConditionKind.REQUIREMENTS_CONFIRMED, description="r",
                status=GateConditionStatus.PENDING),
        ])
        d = rec.evaluate()
        assert d == GateDecision.PENDING
        assert d != GateDecision.APPROVED

    def test_get_blocked_reasons_lists_all_blocked(self):
        rec = GateDecisionRecord(project_id="p9", conditions=[
            GateCondition(kind=GateConditionKind.GAP_FINDINGS_APPROVED, description="g1",
                status=GateConditionStatus.BLOCKED, blocking_reason="gap A"),
            GateCondition(kind=GateConditionKind.FIX_RECOMMENDATIONS_APPROVED, description="f1",
                status=GateConditionStatus.BLOCKED, blocking_reason="fix B"),
        ])
        rec.evaluate()
        reasons = rec.get_blocked_reasons()
        assert len(reasons) == 2
        assert any("gap A" in r for r in reasons)
        assert any("fix B" in r for r in reasons)
