"""Adversarial matrix D + E — rollback and promotion (Gate 14 D/E).

The shared property: a refusal leaves the prior state valid, leaves the
candidate non-active, keeps the rollback handle available, and records the
attempt.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from autoforge_learning.promotion import PromotionConflict, PromotionError, RollbackError
from autoforge_learning.store import ApprovalRecord, ApprovalStatus, PromotionState
from tests.helpers import evidence_payload_for, healthy_metrics, make_human, make_service

KIND = "pattern_template"
KEY = "template-alpha"


def build_ready_candidate(service, project_id, evidence, *, latency=95.0, summary="second"):
    """Build, evaluate and fully approve a candidate for ``KIND:KEY``."""
    from autoforge_learning.models import LearningCandidate, LearningScope, LearningScopeKind

    human, requester = make_human(), make_service()
    candidate = LearningCandidate(
        scope=LearningScope(kind=LearningScopeKind.PROJECT, project_id=project_id),
        kind=KIND,
        summary=summary,
    )
    record = service.record_evidence(service.create_candidate(candidate), evidence)
    report = service.evaluate(
        record=record,
        baseline=healthy_metrics(latency_ms=100.0),
        candidate_metrics=healthy_metrics(latency_ms=latency),
    )
    approval = service.approvals.record_decision(
        approval=service.request_approval(
            record=record,
            evaluation=report,
            kind=KIND,
            key=KEY,
            proposed_effect="second",
            requested_by=requester,
        ),
        approver=human,
        approve=True,
        reason="ok",
    )
    return record, report, approval, human


def pending_approval(record, report) -> ApprovalRecord:
    """A PENDING approval — structurally valid, but authorizing nothing."""
    return ApprovalRecord(
        candidate_id=record.candidate_id,
        project_id=record.project_id,
        evaluation_id=report.evaluation_id,
        evaluation_outcome=report.outcome.value,
        requested_scope=f"{KIND}:{KEY}",
        proposed_effect="effect",
        status=ApprovalStatus.PENDING,
        requested_at=datetime.now(timezone.utc),
    )


# ── E.1/E.2 EVALUATION IS NOT BYPASSABLE ─────────────────────────────────────


def test_promotion_without_an_evaluation_is_refused(
    service, stored_candidate, approved, human_approver, project_id
):
    """E.1 — there is no way to reach promotion without a report object."""
    with pytest.raises((AttributeError, TypeError, ValueError)):
        service.promote(
            record=stored_candidate,
            evaluation=None,  # type: ignore[arg-type]
            approval=approved,
            kind=KIND,
            key=KEY,
            proposed_effect="effect",
            requested_by=human_approver,
        )
    assert service.active_state(project_id, KIND, KEY) is None


def test_promotion_with_a_failed_evaluation_is_refused(
    service, project_id, candidate, human_approver, approved, stored_candidate
):
    """E.2 — a failed evaluation blocks promotion outright."""
    metrics = healthy_metrics(security_violations=3)
    record = service.create_candidate(candidate)
    record = service.record_evidence(record, evidence_payload_for(metrics, project_id))
    failed = service.evaluate(
        record=record, baseline=healthy_metrics(), candidate_metrics=metrics
    )
    assert failed.promotable is False
    with pytest.raises(PromotionError, match="passed evaluation"):
        service.promote(
            record=stored_candidate,
            evaluation=failed,
            approval=approved,
            kind=KIND,
            key=KEY,
            proposed_effect="effect",
            requested_by=human_approver,
        )
    assert service.active_state(project_id, KIND, KEY) is None


# ── E.3 PROMOTION WITHOUT HITL ───────────────────────────────────────────────


def test_promotion_without_hitl_is_refused(
    service, stored_candidate, passing_report, human_approver, project_id
):
    """E.3 — nothing self-authorizes."""
    with pytest.raises(PromotionError, match="human approval did not verify"):
        service.promote(
            record=stored_candidate,
            evaluation=passing_report,
            approval=pending_approval(stored_candidate, passing_report),
            kind=KIND,
            key=KEY,
            proposed_effect="effect",
            requested_by=human_approver,
        )
    assert service.active_state(project_id, KIND, KEY) is None


# ── E.4 PROMOTION WITHOUT A ROLLBACK HANDLE ──────────────────────────────────


def test_promotion_aborts_when_the_rollback_handle_cannot_be_written(
    service, stored_candidate, passing_report, approved, human_approver,
    project_id, monkeypatch,
):
    """E.4 — no handle means no promotion. The hard Gate 6 invariant."""

    def _boom(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(service.store, "save_rollback_handle", _boom)

    with pytest.raises(PromotionError, match="disk full"):
        service.promote(
            record=stored_candidate,
            evaluation=passing_report,
            approval=approved,
            kind=KIND,
            key=KEY,
            proposed_effect="effect",
            requested_by=human_approver,
        )
    assert service.active_state(project_id, KIND, KEY) is None
    failures = [
        p for p in service.store.list_promotions(project_id)
        if p.state is PromotionState.FAILED
    ]
    assert failures, "the refused promotion must be retained"
    assert "disk full" in failures[-1].failure_reason
    # No handle exists, and therefore no rollback target exists — which is
    # exactly why promotion was correctly refused.
    assert service.store.list_rollback_handles(project_id) == ()


def test_promotion_aborts_when_the_handle_readback_is_not_intact(
    service, stored_candidate, passing_report, approved, human_approver,
    project_id, monkeypatch,
):
    """E.4 — a handle that cannot be read back is not a handle."""
    monkeypatch.setattr(service.store, "get_rollback_handle", lambda *a, **k: None)
    with pytest.raises(PromotionError, match="rollback handle"):
        service.promote(
            record=stored_candidate,
            evaluation=passing_report,
            approval=approved,
            kind=KIND,
            key=KEY,
            proposed_effect="effect",
            requested_by=human_approver,
        )
    assert service.active_state(project_id, KIND, KEY) is None


# ── E.5/E.6 DUPLICATE AND CONFLICTING PROMOTION ──────────────────────────────


def test_duplicate_promotion_is_idempotent(
    service, stored_candidate, passing_report, approved, promoted,
    human_approver, project_id,
):
    """E.5 — the same candidate promoted twice is a no-op, not a second version."""
    again = service.promote(
        record=stored_candidate,
        evaluation=passing_report,
        approval=approved,
        kind=KIND,
        key=KEY,
        proposed_effect="effect",
        requested_by=human_approver,
    )
    assert again.promotion_id == promoted.promotion_id
    assert again.state is PromotionState.PROMOTED
    assert service.active_state(project_id, KIND, KEY).version_number == 1
    assert len(
        [
            p for p in service.store.list_promotions(project_id)
            if p.state is PromotionState.PROMOTED
        ]
    ) == 1


def test_a_rolled_back_candidate_cannot_silently_reactivate_itself(
    service, passing_evidence, promoted, project_id
):
    """E.6 — a superseded candidate cannot overwrite a newer active state."""
    service.rollback(project_id=project_id, handle_id=promoted.rollback_handle_id)

    record, report, approval, human = build_ready_candidate(
        service, project_id, passing_evidence
    )
    service.promote(
        record=record,
        evaluation=report,
        approval=approval,
        kind=KIND,
        key=KEY,
        proposed_effect="second",
        requested_by=human,
    )
    active = service.active_state(project_id, KIND, KEY)
    assert active.candidate_id == record.candidate_id


# ── E.7/E.8 PARTIAL WRITE AND RECOVERY ───────────────────────────────────────


def test_a_failed_active_state_write_leaves_the_prior_state_intact(
    service, passing_evidence, promoted, project_id, monkeypatch
):
    """E.7 — the atomic commit either happens or does not; never half-way."""
    original = service.active_state(project_id, KIND, KEY)
    assert original is not None

    def _boom(*args, **kwargs):
        raise OSError("commit failed")

    record, report, approval, human = build_ready_candidate(
        service, project_id, passing_evidence
    )
    monkeypatch.setattr(service.store, "set_active_state", _boom)
    with pytest.raises(PromotionError):
        service.promote(
            record=record,
            evaluation=report,
            approval=approval,
            kind=KIND,
            key=KEY,
            proposed_effect="second",
            requested_by=human,
        )

    monkeypatch.undo()
    still = service.active_state(project_id, KIND, KEY)
    assert still.version_id == original.version_id
    assert still.candidate_id == original.candidate_id


def test_a_failed_promotion_is_recorded_not_swallowed(
    service, stored_candidate, passing_report, approved, human_approver,
    project_id, monkeypatch,
):
    """E.8 — the failed attempt is retained for audit (LC-07)."""

    def _boom(*args, **kwargs):
        raise OSError("commit failed")

    monkeypatch.setattr(service.store, "set_active_state", _boom)
    with pytest.raises(PromotionError):
        service.promote(
            record=stored_candidate,
            evaluation=passing_report,
            approval=approved,
            kind=KIND,
            key=KEY,
            proposed_effect="effect",
            requested_by=human_approver,
        )
    records = service.store.list_promotions(project_id)
    assert len(records) == 1
    assert records[0].state is PromotionState.FAILED
    assert "commit failed" in records[0].failure_reason


# ── D.1/D.2 MISSING / TAMPERED HANDLE ────────────────────────────────────────


def test_rollback_with_a_missing_handle_is_refused(service, promoted, project_id):
    """D.1 — a handle that does not exist cannot authorise a rollback."""
    import uuid

    with pytest.raises(RollbackError, match="no rollback handle"):
        service.rollback(project_id=project_id, handle_id=uuid.uuid4())


def test_rollback_with_a_tampered_handle_is_refused(
    service, promoted, project_id, monkeypatch
):
    """D.2 — a tampered handle is detected by its integrity hash."""
    import uuid as uuid_module

    handle = service.store.get_rollback_handle(project_id, promoted.rollback_handle_id)
    assert handle.is_intact is True

    # model_copy(update=...) bypasses validation: exactly what an attacker
    # editing the stored bytes would produce.
    tampered = handle.model_copy(
        update={"proposed_state": handle.proposed_state.model_copy(
            update={"candidate_id": uuid_module.uuid4()}
        )}
    )
    assert tampered.is_intact is False  # the hash no longer matches

    monkeypatch.setattr(
        service.store, "get_rollback_handle", lambda *a, **k: tampered
    )
    with pytest.raises(RollbackError, match="integrity verification"):
        service.rollback(project_id=project_id, handle_id=promoted.rollback_handle_id)


# ── D.3 WRONG PROJECT / WRONG CANDIDATE ──────────────────────────────────────


def test_rollback_from_another_project_is_refused(
    service, promoted, project_id, other_project_id
):
    """D.3 — a handle cannot be used from outside its project."""
    with pytest.raises(RollbackError, match="no rollback handle"):
        service.rollback(project_id=other_project_id, handle_id=promoted.rollback_handle_id)


def test_a_handle_only_restores_its_own_candidates_state(
    service, passing_evidence, promoted, project_id
):
    """D.3 — a handle is bound to its own promotion; it cannot move another's."""
    record, report, approval, human = build_ready_candidate(
        service, project_id, passing_evidence, summary="a different candidate"
    )
    second = service.promote(
        record=record,
        evaluation=report,
        approval=approval,
        kind=KIND,
        key=KEY,
        proposed_effect="second",
        requested_by=human,
    )
    assert second.rollback_handle_id != promoted.rollback_handle_id

    # Rolling back the *second* promotion restores the first candidate's state.
    service.rollback(project_id=project_id, handle_id=second.rollback_handle_id)
    active = service.active_state(project_id, KIND, KEY)
    assert active.candidate_id == promoted.candidate_id
    assert active.version_id == promoted.new_state.version_id


# ── D.4 REPEATED ROLLBACK ────────────────────────────────────────────────────


def test_repeated_rollback_is_idempotent(service, promoted, project_id):
    """D.4 — rolling back twice is the same result, not a second change."""
    first = service.rollback(
        project_id=project_id, handle_id=promoted.rollback_handle_id, reason="one"
    )
    second = service.rollback(
        project_id=project_id, handle_id=promoted.rollback_handle_id, reason="two"
    )
    assert second.handle_id == first.handle_id
    assert (second.restored_state is None) == (first.restored_state is None)
    assert service.active_state(project_id, KIND, KEY) is None


def test_repeated_rollback_preserves_history(service, promoted, project_id):
    """RB-05 — every rollback execution is retained."""
    service.rollback(project_id=project_id, handle_id=promoted.rollback_handle_id)
    service.rollback(project_id=project_id, handle_id=promoted.rollback_handle_id)
    assert len(service.store.list_rollbacks(project_id)) == 2
    assert len(service.store.list_promotions(project_id)) == 1  # never deleted


# ── D.5 ROLLBACK AFTER A FAILED PROMOTION ────────────────────────────────────


def test_the_rollback_handle_survives_a_failed_promotion(
    service, stored_candidate, passing_report, approved, human_approver,
    project_id, monkeypatch,
):
    """D.5 — the handle created before a *failed* commit stays usable."""
    import uuid as uuid_module

    def _boom(*args, **kwargs):
        raise OSError("commit failed")

    monkeypatch.setattr(service.store, "set_active_state", _boom)
    with pytest.raises(PromotionError):
        service.promote(
            record=stored_candidate,
            evaluation=passing_report,
            approval=approved,
            kind=KIND,
            key=KEY,
            proposed_effect="effect",
            requested_by=human_approver,
        )
    handles = service.store.list_rollback_handles(project_id)
