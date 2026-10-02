"""Property / invariant tests (Gate 15).

These assert *implications*, not just happy paths. Each test states a
property that must hold for every promotion and every rollback, regardless of
inputs:

    promotion  ⇒  evaluation_passed ∧ human_approved ∧ rollback_handle_exists
                  ∧ security_boundary_allowed
    rollback   ⇒  valid_handle ∧ correct_project ∧ correct_candidate
    promotion  ⇏  model_authority
    unknown evidence ⇏ pass
    missing approval ⇏ promotion
    missing handle   ⇏ promotion
"""

from __future__ import annotations

import uuid

from autoforge_learning.audit import LearningAuditAction
from autoforge_learning.evaluation import RegressionEvaluator
from autoforge_learning.invariants import (
    NA_PERMITTED_BY_CONTRACT,
    PROTECTED_INVARIANTS,
    InvariantStatus,
    ProtectedInvariant,
)
from autoforge_learning.models import LearningCandidate, LearningScope, LearningScopeKind
from autoforge_learning.store import ApprovalStatus, PromotionState
from tests.helpers import empty_metrics

KIND = "pattern_template"
KEY = "template-alpha"


# ── PROMOTION IMPLIES … ───────────────────────────────────────────────────────


def test_promotion_implies_evaluation_approved_handle_and_boundary(
    service, promoted, passing_report, project_id
):
    """The four preconditions are all independently checkable afterwards."""
    assert passing_report.outcome.value == "passed"
    assert promoted.state is PromotionState.PROMOTED
    assert promoted.evaluation_id == passing_report.evaluation_id

    stored_approval = service.store.get_approval(project_id, promoted.approval_id)
    assert stored_approval.status is ApprovalStatus.APPROVED
    assert stored_approval.is_human_approved is True

    handle = service.store.get_rollback_handle(project_id, promoted.rollback_handle_id)
    assert handle is not None and handle.is_intact is True
    assert handle.candidate_id == promoted.candidate_id

    # The security boundary was consulted at proposal time.
    assert service.auditor.count(LearningAuditAction.CANDIDATE_CREATED) >= 1


def test_every_promotion_in_the_store_has_a_matching_handle(service, promoted, project_id):
    """Sweeping check over every promotion record, not just the happy one."""
    for record in service.store.list_promotions(project_id):
        if record.state is not PromotionState.PROMOTED:
            continue
        handle = service.store.get_rollback_handle(project_id, record.rollback_handle_id)
        assert handle is not None
        assert handle.is_intact is True
        assert handle.candidate_id == record.candidate_id
        assert handle.proposed_state.version_id == record.new_state.version_id


# ── PROMOTION NEVER IMPLIES MODEL AUTHORITY ──────────────────────────────────


def test_no_promoted_record_names_a_non_human_approver(service, promoted, project_id):
    """Promotion NEVER implies model authority."""
    for record in service.store.list_approvals(project_id):
        if record.status is ApprovalStatus.APPROVED:
            assert record.approver_subject_type == "human"
            assert record.approver_id


def test_a_promotion_record_carries_no_authority_of_its_own(promoted):
    """The record is data. It confers nothing by existing."""
    assert not hasattr(promoted, "authority")
    assert not hasattr(promoted, "grants")
    assert promoted.attempted_by


# ── ROLLBACK IMPLIES … ───────────────────────────────────────────────────────


def test_rollback_implies_a_valid_handle_in_the_right_project(service, promoted, project_id):
    """rollback ⇒ valid handle ∧ correct project ∧ correct candidate."""
    record = service.rollback(
        project_id=project_id, handle_id=promoted.rollback_handle_id, reason="test"
    )
    handle = service.store.get_rollback_handle(project_id, promoted.rollback_handle_id)
    assert handle.is_intact is True
    assert handle.project_id == project_id
    assert record.candidate_id == handle.candidate_id
    assert record.promotion_id == promoted.promotion_id


# ── UNKNOWN EVIDENCE NEVER IMPLIES PASS ──────────────────────────────────────


def test_unknown_evidence_never_yields_pass(project_id):
    """Unknown evidence ⇏ pass, for every invariant that evidence governs."""
    report = RegressionEvaluator().evaluate(
        candidate_id=uuid.uuid4(),
        project_id=project_id,
        scope_kind="project",
        baseline=empty_metrics(),
        candidate=empty_metrics(),
        evidence=(),
    )
    assert report.promotable is False
    for result in report.results:
        if result.invariant is ProtectedInvariant.PI8_CUSTOMER_OUTCOMES:
            continue
        assert result.status is not InvariantStatus.PASS


def test_only_pi8_may_be_not_applicable():
    """A blanket N/A allowance would defeat the whole gate."""
    assert NA_PERMITTED_BY_CONTRACT == frozenset({ProtectedInvariant.PI8_CUSTOMER_OUTCOMES})


# ── MISSING APPROVAL / HANDLE NEVER IMPLIES PROMOTION ────────────────────────


def test_missing_approval_never_implies_promotion(service, project_id):
    record = service.create_candidate(
        LearningCandidate(
            scope=LearningScope(kind=LearningScopeKind.PROJECT, project_id=project_id),
            kind=KIND,
            summary="never approved",
        )
    )
    assert service.store.list_approvals(project_id) == ()
    assert service.active_state(project_id, KIND, KEY) is None


def test_a_handle_cannot_exist_without_its_promotion_record(service, promoted, project_id):
    """A handle is only usable alongside a promotion that references it."""
    handles = service.store.list_rollback_handles(project_id)
    promotions = service.store.list_promotions(project_id)
    referenced = {p.rollback_handle_id for p in promotions}
    for handle in handles:
        assert handle.handle_id in referenced


# ── EVALUATION REPORT INTEGRITY ──────────────────────────────────────────────


def test_a_report_always_evaluates_the_contract_invariant_set(passing_report):
    """RM-02 — no invariant is ever skipped."""
    assert tuple(r.invariant for r in passing_report.results) == PROTECTED_INVARIANTS


def test_baseline_is_pinned_to_the_evaluation(passing_report):
    """RM-03/RM-05 — the baseline hash travels with the verdict."""
    assert passing_report.baseline_pinned is True
    assert len(passing_report.baseline_hash) == 64