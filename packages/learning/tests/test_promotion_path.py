"""End-to-end promotion path — the happy path, proven exactly once.

Every adversarial case lives in a sibling module. This file proves the
*intended* behaviour works against the real certified security platform, so
the negative tests cannot pass merely because the path is broken.
"""

from __future__ import annotations

import uuid

from autoforge_learning.audit import LearningAuditAction
from autoforge_learning.models import LearningCandidate, LearningScope, LearningScopeKind
from autoforge_learning.store import ApprovalStatus, PromotionState
from tests.helpers import healthy_metrics

NIL_UUID = uuid.UUID(int=0)


def test_candidate_is_persisted_through_the_security_boundary(
    service, stored_candidate
):
    assert stored_candidate.project_id == stored_candidate.scope.project_id
    assert service.store.get_candidate(
        stored_candidate.project_id, stored_candidate.candidate_id
    ) is not None
    assert service.auditor.count(LearningAuditAction.CANDIDATE_CREATED) >= 1


def test_all_nine_invariants_receive_an_explicit_result(passing_report):
    assert len(passing_report.results) == 9
    statuses = passing_report.status_by_invariant
    assert set(statuses) == {f"PI-{i}" for i in range(1, 10)}
    # PI-8 is the single contract-deferred invariant.
    assert statuses["PI-8"].value == "not_applicable"
    for inv in ("PI-1", "PI-2", "PI-3", "PI-4", "PI-5", "PI-6", "PI-7", "PI-9"):
        assert statuses[inv].value == "pass", f"{inv} should pass: {statuses[inv]}"
    assert passing_report.outcome.value == "passed"
    assert passing_report.promotable is True


def test_approval_requires_a_human_and_records_lineage(approved):
    assert approved.status is ApprovalStatus.APPROVED
    assert approved.approver_subject_type == "human"
    assert approved.approver_id
    assert approved.hitl_gate_id
    assert approved.resume_token_present is True
    assert approved.is_human_approved is True


def test_promotion_creates_the_handle_before_it_activates(
    service, promoted, project_id
):
    assert promoted.state is PromotionState.PROMOTED
    assert promoted.rollback_handle_id != NIL_UUID
    assert promoted.new_state is not None
    assert promoted.new_state.version_number == 1
    # The handle is durable *before* the commit and still readable after.
    handle = service.store.get_rollback_handle(project_id, promoted.rollback_handle_id)
    assert handle is not None
    assert handle.is_intact is True


def test_promotion_makes_the_state_active(service, promoted, project_id):
    active = service.active_state(project_id, "pattern_template", "template-alpha")
    assert active is not None
    assert active.candidate_id == promoted.candidate_id
    assert active.version_id == promoted.new_state.version_id


def test_full_audit_trail_is_emitted(service, promoted):
    for action in (
        LearningAuditAction.CANDIDATE_CREATED,
        LearningAuditAction.EVIDENCE_COLLECTED,
        LearningAuditAction.EVALUATION_STARTED,
        LearningAuditAction.EVALUATION_COMPLETED,
        LearningAuditAction.APPROVAL_REQUESTED,
        LearningAuditAction.APPROVAL_GRANTED,
        LearningAuditAction.ROLLBACK_HANDLE_CREATED,
        LearningAuditAction.PROMOTION_ATTEMPTED,
        LearningAuditAction.PROMOTION_SUCCEEDED,
    ):
        assert service.auditor.count(action) >= 1, f"missing audit event {action}"


def test_audit_records_land_in_the_certified_audit_engine(
    service, promoted, security_platform
):
    """Gate 9: reuse the existing AuditEngine, do not create a parallel one."""
    records = security_platform.audit.query_records(
        action=LearningAuditAction.PROMOTION_SUCCEEDED.value
    )
    assert records, "promotion must be recorded by the certified AuditEngine"
    assert records[0].project_id == str(promoted.project_id)


def test_telemetry_reflects_the_real_run(service, promoted, project_id):
    t = service.telemetry(project_id)
    assert t.candidates_created == 1
    assert t.candidates_evaluated == 1
    assert t.candidates_failed_evaluation == 0
    assert t.approvals_requested == 1
    assert t.approvals_granted == 1
    assert t.promotions_attempted == 1
    assert t.promotions_succeeded == 1
    assert t.promotions_failed == 0
    assert t.data_available is True


def test_rollback_restores_the_exact_prior_state(service, promoted, project_id):
    handle_id = promoted.rollback_handle_id
    record = service.rollback(
        project_id=project_id, handle_id=handle_id, reason="operator requested"
    )
    assert record.handle_id == handle_id
    # There was no prior state, so the correct restoration is "no active state".
    assert record.restored_state is None
    assert service.active_state(project_id, "pattern_template", "template-alpha") is None


def test_rollback_then_repromote_retains_full_history(
    service, stored_candidate, promoted, human_approver, service_requester, project_id
):
    """CF-01/LC-07: prior records are retained, never deleted."""
    service.rollback(project_id=project_id, handle_id=promoted.rollback_handle_id)

    second = LearningCandidate(
        scope=LearningScope(kind=LearningScopeKind.PROJECT, project_id=project_id),
        kind="pattern_template",
        summary="A second learned template",
    )
    rec2 = service.record_evidence(
        service.create_candidate(second), stored_candidate.candidate.evidence
    )
    report2 = service.evaluate(
        record=rec2,
        baseline=healthy_metrics(latency_ms=100.0),
        candidate_metrics=healthy_metrics(latency_ms=95.0),
    )
    approval2 = service.approvals.record_decision(
        approval=service.request_approval(
            record=rec2,
            evaluation=report2,
            kind="pattern_template",
            key="template-alpha",
            proposed_effect="second template",
            requested_by=service_requester,
        ),
        approver=human_approver,
        approve=True,
        reason="ok",
    )
    promo2 = service.promote(
        record=rec2,
        evaluation=report2,
        approval=approval2,
        kind="pattern_template",
        key="template-alpha",
        proposed_effect="second template",
        requested_by=human_approver,
    )
    assert promo2.state is PromotionState.PROMOTED
    assert promo2.new_state.version_number == 1

    # Both promotions and the rollback are still on record.
    assert len(service.store.list_promotions(project_id)) == 2
    assert len(service.store.list_rollbacks(project_id)) == 1
    assert len(service.store.list_candidates(project_id)) == 2


def test_rollback_restores_an_earlier_version_exactly(
    service, stored_candidate, promoted, human_approver, service_requester, project_id
):
    """A second promotion over an existing state, then rollback to version 1."""
    v1 = service.active_state(project_id, "pattern_template", "template-alpha")
    assert v1 is not None

    second = LearningCandidate(
        scope=LearningScope(kind=LearningScopeKind.PROJECT, project_id=project_id),
        kind="pattern_template",
        summary="Second template superseding the first",
    )
    rec2 = service.record_evidence(
        service.create_candidate(second), stored_candidate.candidate.evidence
    )
    report2 = service.evaluate(
        record=rec2,
        baseline=healthy_metrics(latency_ms=100.0),
        candidate_metrics=healthy_metrics(latency_ms=80.0),
    )
    approval2 = service.approvals.record_decision(
        approval=service.request_approval(
            record=rec2,
            evaluation=report2,
            kind="pattern_template",
            key="template-alpha",
            proposed_effect="supersede",
            requested_by=service_requester,
        ),
        approver=human_approver,
        approve=True,
        reason="ok",
    )
    promo2 = service.promote(
        record=rec2,
        evaluation=report2,
        approval=approval2,
        kind="pattern_template",
        key="template-alpha",
        proposed_effect="supersede",
        requested_by=human_approver,
    )
    assert promo2.new_state.version_number == 2

    service.rollback(project_id=project_id, handle_id=promo2.rollback_handle_id)

    restored = service.active_state(project_id, "pattern_template", "template-alpha")
    assert restored.version_id == v1.version_id
    assert restored.version_number == 1
    assert restored.candidate_id == v1.candidate_id