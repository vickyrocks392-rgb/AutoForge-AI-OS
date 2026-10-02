"""Adversarial matrix C — approval (Gate 14 C / Gate 5).

The invariant under test throughout: **MODEL PROPOSAL ≠ HUMAN APPROVAL**.
Every path that is not an attributable human decision must fail closed.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from autoforge_learning.approval import ApprovalCoordinator, ApprovalError
from autoforge_learning.audit import LearningAuditAction
from autoforge_learning.promotion import PromotionError
from autoforge_learning.store import ApprovalRecord, ApprovalStatus
from autoforge_security.errors import ApprovalGateExpiredError, SelfApprovalForbiddenError
from tests.helpers import evidence_payload_for, healthy_metrics, make_service, make_worker

KIND = "pattern_template"
KEY = "template-alpha"


def _promote(service, record, report, approval, human, key=KEY):
    return service.promote(
        record=record,
        evaluation=report,
        approval=approval,
        kind=KIND,
        key=key,
        proposed_effect="effect",
        requested_by=human,
    )


# ── C.1 NO APPROVAL ───────────────────────────────────────────────────────────


def test_promotion_without_any_approval_is_refused(
    service, stored_candidate, passing_report, human_approver
):
    """C.1 — a pending approval authorizes nothing."""
    pending = ApprovalRecord(
        candidate_id=stored_candidate.candidate_id,
        project_id=stored_candidate.project_id,
        evaluation_id=passing_report.evaluation_id,
        evaluation_outcome=passing_report.outcome.value,
        requested_scope=f"{KIND}:{KEY}",
        proposed_effect="effect",
        status=ApprovalStatus.PENDING,
        requested_at=datetime.now(timezone.utc),
        hitl_gate_id="hitl_gate_never_decided",
    )
    with pytest.raises(PromotionError):
        _promote(service, stored_candidate, passing_report, pending, human_approver)
    assert service.active_state(stored_candidate.project_id, KIND, KEY) is None


def test_an_approval_record_cannot_be_self_declared_approved():
    """C.7 — the *type* refuses a non-human approver on an APPROVED record."""
    import uuid

    import pydantic

    with pytest.raises(pydantic.ValidationError):
        ApprovalRecord(
            candidate_id=uuid.uuid4(),
            project_id=uuid.uuid4(),
            evaluation_id=uuid.uuid4(),
            evaluation_outcome="passed",
            requested_scope=f"{KIND}:{KEY}",
            proposed_effect="effect",
            status=ApprovalStatus.APPROVED,
            approver_id="model-gpt",
            approver_subject_type="worker",
            requested_at=datetime.now(timezone.utc),
        )


# ── C.2 REJECTED ─────────────────────────────────────────────────────────────


def test_a_rejected_approval_blocks_promotion(
    service, stored_candidate, passing_report, service_requester, human_approver
):
    """C.2 — a human said no; that is final."""
    approval = service.request_approval(
        record=stored_candidate,
        evaluation=passing_report,
        kind=KIND,
        key=KEY,
        proposed_effect="effect",
        requested_by=service_requester,
    )
    rejected = service.approvals.record_decision(
        approval=approval, approver=human_approver, approve=False, reason="no"
    )
    assert rejected.status is ApprovalStatus.REJECTED
    with pytest.raises(PromotionError):
        _promote(service, stored_candidate, passing_report, rejected, human_approver)


# ── C.3 EXPIRED ──────────────────────────────────────────────────────────────


def test_an_expired_approval_blocks_promotion(approved, human_approver, service,
                                              stored_candidate, passing_report):
    """C.3 — expiry is durable and cannot be resurrected."""
    stale = approved.model_copy(
        update={"expires_at": datetime.now(timezone.utc) - timedelta(seconds=1)}
    )
    with pytest.raises(PromotionError, match="expired"):
        _promote(service, stored_candidate, passing_report, stale, human_approver)


def test_an_expired_gate_is_recorded_as_expired(
    service, stored_candidate, passing_report, service_requester, human_approver
):
    """C.3 — the HITL gate's own expiry produces a durable EXPIRED record."""
    approval = service.request_approval(
        record=stored_candidate,
        evaluation=passing_report,
        kind=KIND,
        key=KEY,
        proposed_effect="effect",
        requested_by=service_requester,
        ttl_seconds=1,
    )
    gate = service.approvals._security.hitl.get_gate(approval.hitl_gate_id)
    gate.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)

    with pytest.raises(ApprovalGateExpiredError):
        service.approvals.record_decision(
            approval=approval, approver=human_approver, approve=True, reason="ok"
        )
    stored = service.store.get_approval(stored_candidate.project_id, approval.approval_id)
    assert stored.status is ApprovalStatus.EXPIRED


# ── C.4 REVOKED ──────────────────────────────────────────────────────────────


def test_a_revoked_approval_blocks_promotion(
    service, stored_candidate, passing_report, approved, human_approver
):
    """C.4 — a withdrawn approval is indistinguishable from never-granted."""
    revoked = service.approvals.revoke(
        approval=approved, revoked_by=human_approver, reason="reconsidered"
    )
    assert revoked.status is ApprovalStatus.REVOKED
    with pytest.raises(PromotionError):
        _promote(service, stored_candidate, passing_report, revoked, human_approver)


def test_a_non_human_cannot_revoke_an_approval(approved, worker_subject):
    with pytest.raises(ApprovalError, match="only a human"):
        ApprovalCoordinator.revoke(
            self=None,
            approval=approved,
            revoked_by=worker_subject,
            reason="self-service",
        )


# ── C.5 MALFORMED ────────────────────────────────────────────────────────────


def test_an_approval_without_hitl_lineage_is_refused(
    service, stored_candidate, passing_report, approved, human_approver
):
    """C.5 — an approval with no certified gate behind it is malformed."""
    forged = approved.model_copy(update={"hitl_gate_id": None})
    assert forged.is_human_approved is True  # the human field still looks right
    with pytest.raises(PromotionError, match="HITL gate lineage"):
        _promote(service, stored_candidate, passing_report, forged, human_approver)


def test_an_approval_with_a_bogus_resume_token_is_refused(
    service, stored_candidate, passing_report, approved, human_approver
):
    """C.5 — the resume token must verify against the certified gate."""
    with pytest.raises(PromotionError):
        service.promote(
            record=stored_candidate,
            evaluation=passing_report,
            approval=approved,
            kind=KIND,
            key=KEY,
            proposed_effect="effect",
            requested_by=human_approver,
            resume_token="rst_forged_token",
        )


# ── C.6 WRONG PROJECT / WRONG CANDIDATE ──────────────────────────────────────


def test_an_approval_for_another_candidate_is_refused(
    service, stored_candidate, passing_report, approved, human_approver
):
    """C.6 — an approval is bound to exactly one candidate."""
    import uuid

    with pytest.raises(PromotionError, match="evaluation does not belong"):
        service.promotion.promote(
            project_id=stored_candidate.project_id,
            candidate_id=uuid.uuid4(),
            evaluation=passing_report,
            approval=approved,
            kind=KIND,
            key=KEY,
            proposed_effect="effect",
            requested_by=human_approver,
        )


def test_an_approval_from_another_project_is_refused(
    service, stored_candidate, passing_report, approved, human_approver, other_project_id
):
    """C.6 — an approval cannot be carried across a project boundary."""
    with pytest.raises(PromotionError):
        service.promotion.promote(
            project_id=other_project_id,
            candidate_id=stored_candidate.candidate_id,
            evaluation=passing_report,
            approval=approved,
            kind=KIND,
            key=KEY,
            proposed_effect="effect",
            requested_by=human_approver,
        )


def test_an_approval_authorising_a_different_scope_is_refused(
    service, stored_candidate, passing_report, approved, human_approver
):
    """C.6 — the approved scope must equal the promoted scope."""
    with pytest.raises(PromotionError, match="authorises scope"):
        _promote(
            service,
            stored_candidate,
            passing_report,
            approved,
            human_approver,
            key="a-different-key",
        )


# ── C.7 MODEL-GENERATED FAKE APPROVAL ────────────────────────────────────────


def test_a_worker_cannot_approve_even_with_the_governance_role(
    service, stored_candidate, passing_report, service_requester, worker_subject
):
    """C.7 — the model cannot impersonate a human approver."""
    with pytest.raises(SelfApprovalForbiddenError):
        service.approvals.record_decision(
            approval=service.request_approval(
                record=stored_candidate,
                evaluation=passing_report,
                kind=KIND,
                key=KEY,
                proposed_effect="effect",
                requested_by=service_requester,
            ),
            approver=worker_subject,
            approve=True,
            reason="I am the model and I approve",
        )
    assert service.auditor.count(LearningAuditAction.APPROVAL_GRANTED) == 0


def test_a_service_principal_cannot_approve(
    service, stored_candidate, passing_report, service_requester
):
    """C.7 — no non-human subject may decide a gate, even holding the role."""
    with pytest.raises(SelfApprovalForbiddenError):
        service.approvals.record_decision(
            approval=service.request_approval(
                record=stored_candidate,
                evaluation=passing_report,
                kind=KIND,
                key=KEY,
                proposed_effect="effect",
                requested_by=service_requester,
            ),
            approver=make_service("service.self", with_governance_role=True),
            approve=True,
            reason="auto",
        )


def test_self_approval_is_refused(service, stored_candidate, passing_report, human_approver):
    """Governance: a human cannot approve their own request either."""
    approval = service.request_approval(
        record=stored_candidate,
        evaluation=passing_report,
        kind=KIND,
        key=KEY,
        proposed_effect="effect",
        requested_by=human_approver,
    )
    with pytest.raises(SelfApprovalForbiddenError):
        service.approvals.record_decision(
            approval=approval, approver=human_approver, approve=True, reason="mine"
        )


def test_a_second_decision_on_a_resolved_gate_is_refused(service, approved, human_approver):
    """A duplicate decision cannot flip an approval or resurrect a gate."""
    with pytest.raises(ApprovalError, match="already"):
        service.approvals.record_decision(
            approval=approved,
            approver=human_approver,
            approve=False,
            reason="changed my mind",
        )


def test_a_failed_evaluation_cannot_request_approval(service, project_id, candidate):
    """C/G — approval is strictly downstream of a passing evaluation."""
    metrics = healthy_metrics(security_violations=1)
    record = service.create_candidate(candidate)
    record = service.record_evidence(record, evidence_payload_for(metrics, project_id))
    report = service.evaluate(
        record=record, baseline=healthy_metrics(), candidate_metrics=metrics
    )
    with pytest.raises(ApprovalError, match="passed every required invariant"):
        service.request_approval(
            record=record,
            evaluation=report,
            kind=KIND,
            key=KEY,
            proposed_effect="effect",
            requested_by=make_service(),
        )


def test_approval_is_impossible_without_the_security_platform(tmp_path, project_id):
    """No security platform means no approval — fail closed, not fail open.

    Two independent refusals are asserted: the proposal boundary denies the
    candidate outright, and the approval coordinator independently refuses to
    act without a certified HITL/governance boundary.
    """
    from autoforge_learning.approval import ApprovalCoordinator
    from autoforge_learning.audit import LearningAuditor
    from autoforge_learning.lifecycle import LearningLifecycleService
    from autoforge_learning.models import LearningCandidate, LearningScope, LearningScopeKind
    from autoforge_learning.store import DurableLearningStore

    bare = LearningLifecycleService.build(store_root=tmp_path / "bare", security_platform=None)
    candidate = LearningCandidate(
        scope=LearningScope(kind=LearningScopeKind.PROJECT, project_id=project_id),
        kind=KIND,
        summary="no security platform available",
    )
    # (1) The proposal boundary itself fails closed when it has no engine.
    with pytest.raises(PermissionError, match="boundary_unavailable"):
        bare.create_candidate(candidate)

    # (2) The approval coordinator refuses independently of the boundary.
    store = DurableLearningStore(tmp_path / "bare")
    coordinator = ApprovalCoordinator(
        security_platform=None, store=store, auditor=LearningAuditor(None)
    )
    assert coordinator.available is False
    with pytest.raises(ApprovalError, match="SecurityPlatform"):
        coordinator.request_approval(
            candidate_id=candidate.candidate_id,
            project_id=project_id,
            evaluation=None,
            requested_scope=f"{KIND}:{KEY}",
            proposed_effect="effect",
            requested_by=make_service(),
        )