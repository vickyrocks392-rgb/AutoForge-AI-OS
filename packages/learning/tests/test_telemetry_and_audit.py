"""Truthful telemetry + audit-contract tests (Gates 9, 16).

Gate 16 forbids fabricated counters. These tests prove the numbers come from
records, that an empty run reports zeros (not "100%"), and that audit records
carry lineage without leaking secrets.
"""

from __future__ import annotations

import uuid

import pytest

from autoforge_learning.audit import ALL_AUDIT_ACTIONS, LearningAuditAction, LearningAuditor
from autoforge_learning.models import LearningCandidate, LearningScope, LearningScopeKind
from autoforge_learning.store import DurableLearningStore
from autoforge_learning.telemetry import TelemetryCollector
from tests.helpers import evidence_payload_for, healthy_metrics, make_human, make_service

KIND = "pattern_template"
KEY = "template-alpha"


def _candidate(project_id, summary="candidate"):
    return LearningCandidate(
        scope=LearningScope(kind=LearningScopeKind.PROJECT, project_id=project_id),
        kind=KIND,
        summary=summary,
    )


# ── GATE 16: TRUTHFUL TELEMETRY ───────────────────────────────────────────────


def test_an_empty_run_reports_zeros_not_success(service, project_id):
    """An empty run must never look like a healthy run."""
    t = service.telemetry(project_id)
    assert t.candidates_created == 0
    assert t.candidates_evaluated == 0
    assert t.promotions_succeeded == 0
    assert t.data_available is False
    assert t.is_all_passing is False
    assert t.pass_rate is None  # no evaluations ⇒ no rate, not 0.0 or 1.0


def test_no_counter_is_a_hardcoded_positive_constant(service, project_id):
    """A fresh collector must produce zeros for an empty project."""
    store = DurableLearningStore(service.store.root / "isolated")
    t = TelemetryCollector(store=store, auditor=service.auditor).collect(project_id)
    for field in (
        "candidates_created",
        "candidates_evaluated",
        "candidates_failed_evaluation",
        "approvals_requested",
        "approvals_granted",
        "approvals_rejected",
        "promotions_attempted",
        "promotions_succeeded",
        "promotions_failed",
        "rollbacks_attempted",
        "rollbacks_succeeded",
        "rollbacks_failed",
    ):
        assert getattr(t, field) == 0, f"{field} must start at zero"


def test_a_failed_evaluation_is_counted_as_a_failure(
    service, project_id, passing_evidence
):
    record = service.record_evidence(
        service.create_candidate(_candidate(project_id)), passing_evidence
    )
    report = service.evaluate(
        record=record,
        baseline=healthy_metrics(),
        candidate_metrics=healthy_metrics(security_violations=5),
    )
    t = service.telemetry(project_id)
    assert t.candidates_evaluated == 1
    assert t.candidates_failed_evaluation == 1
    assert t.pass_rate == 0.0
    assert t.is_all_passing is False
    assert report.promotable is False


def test_counts_track_real_records(service, passing_evidence, project_id, human_approver):
    """Every counter follows from actual stored records."""
    record = service.record_evidence(
        service.create_candidate(_candidate(project_id)), passing_evidence
    )
    good = service.evaluate(
        record=record,
        baseline=healthy_metrics(latency_ms=100.0),
        candidate_metrics=healthy_metrics(latency_ms=80.0),
    )
    bad_record = service.record_evidence(
        service.create_candidate(_candidate(project_id, "failing")),
        evidence_payload_for(healthy_metrics(security_violations=2), project_id),
    )
    service.evaluate(
        record=bad_record,
        baseline=healthy_metrics(),
        candidate_metrics=healthy_metrics(security_violations=2),
    )

    approval = service.approvals.record_decision(
        approval=service.request_approval(
            record=record,
            evaluation=good,
            kind=KIND,
            key=KEY,
            proposed_effect="effect",
            requested_by=make_service(),
        ),
        approver=human_approver,
        approve=True,
        reason="ok",
    )
    service.promote(
        record=record,
        evaluation=good,
        approval=approval,
        kind=KIND,
        key=KEY,
        proposed_effect="effect",
        requested_by=human_approver,
    )

    t = service.telemetry(project_id)
    assert t.candidates_created == 2
    assert t.candidates_evaluated == 2
    assert t.candidates_failed_evaluation == 1
    assert t.approvals_requested == 1
    assert t.approvals_granted == 1
    assert t.promotions_attempted == 1
    assert t.promotions_succeeded == 1
    assert t.promotions_failed == 0
    assert t.pass_rate == 0.5
    assert t.is_all_passing is False
    assert t.data_available is True


# ── GATE 9: AUDIT CONTRACT ───────────────────────────────────────────────────


def test_all_fifteen_canonical_events_are_defined():
    assert len(ALL_AUDIT_ACTIONS) == 15
    assert {a.value for a in ALL_AUDIT_ACTIONS} == {
        "learning.candidate_created",
        "learning.evidence_collected",
        "learning.evaluation_started",
        "learning.evaluation_completed",
        "learning.evaluation_failed",
        "learning.approval_requested",
        "learning.approval_granted",
        "learning.approval_rejected",
        "learning.rollback_handle_created",
        "learning.promotion_attempted",
        "learning.promotion_succeeded",
        "learning.promotion_failed",
        "learning.rollback_attempted",
        "learning.rollback_succeeded",
        "learning.rollback_failed",
    }


def test_audit_records_carry_lineage(service, promoted, project_id, security_platform):
    """Project, candidate, actor, action, result, timestamp and correlation."""
    records = security_platform.audit.query_records(
        action=LearningAuditAction.PROMOTION_SUCCEEDED.value
    )
    assert records
    for record in records:
        assert record.project_id == str(project_id)
        assert record.actor_id
        assert record.action == "learning.promotion_succeeded"
        assert record.timestamp is not None
        assert record.details["promotion_id"] == str(promoted.promotion_id)
        assert record.details["approver_id"]
        assert record.details["approved_by"] == "human"


def test_audit_details_are_redacted_by_the_certified_engine(
    service, project_id, security_platform
):
    """Gate 9 — no credential material reaches the trail."""
    service.auditor.emit(
        LearningAuditAction.CANDIDATE_CREATED,
        project_id=project_id,
        details={
            "password": "hunter2",
            "api_key": "sk-live-abcdef",
            "harmless": "keep-me",
        },
        strict=False,
    )
    records = security_platform.audit.query_records(
        action=LearningAuditAction.CANDIDATE_CREATED.value
    )
    assert records
    details = records[-1].details
    assert details["password"] == "***"
    assert details["api_key"] == "***"
    assert details["harmless"] == "keep-me"
    rendered = str(details)
    assert "hunter2" not in rendered
    assert "sk-live-abcdef" not in rendered


def test_audit_without_an_engine_is_a_hard_failure():
    """An unavailable audit trail is not a licence to promote."""
    from autoforge_learning.audit import LearningAuditError

    auditor = LearningAuditor(None)
    assert auditor.available is False
    with pytest.raises(LearningAuditError):
        auditor.emit(LearningAuditAction.PROMOTION_SUCCEEDED, project_id=uuid.uuid4())


def test_a_non_strict_emission_records_the_degradation_instead_of_raising():
    """Informational events degrade; success events never do."""
    auditor = LearningAuditor(None)
    assert (
        auditor.emit(
            LearningAuditAction.PROMOTION_ATTEMPTED,
            project_id=uuid.uuid4(),
            strict=False,
        )
        is None
    )
    assert auditor.events[-1].outcome == "audit_unavailable"