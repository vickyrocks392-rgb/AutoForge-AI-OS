"""Adversarial matrix A + B — evidence and evaluation (Gate 14 A/B).

Every case here must fail closed. The shared assertion is that a promotion is
refused, that nothing becomes active, and that the reason is inspectable —
never a silent success.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from autoforge_learning.evaluation import (
    MAX_EVIDENCE_AGE_SECONDS,
    EvaluationOutcome,
    RegressionEvaluator,
)
from autoforge_learning.invariants import InvariantStatus, ProtectedInvariant
from autoforge_learning.models import (
    EvidenceRef,
    EvidenceSource,
    LearningCandidate,
    LearningScope,
    LearningScopeKind,
    ValidationTruth,
)
from tests.helpers import empty_metrics, evidence_payload_for, healthy_metrics

# ── A. EVIDENCE ───────────────────────────────────────────────────────────────


def test_no_evidence_evaluates_every_required_invariant_as_unavailable(
    service, project_id
):
    """A.1 missing evidence — reported as absent, never as PASS."""
    record = service.create_candidate(
        LearningCandidate(
            scope=LearningScope(kind=LearningScopeKind.PROJECT, project_id=project_id),
            kind="pattern_template",
            summary="candidate with no evidence at all",
        )
    )
    report = service.evaluate(
        record=record,
        baseline=healthy_metrics(),
        candidate_metrics=healthy_metrics(),
    )
    assert report.promotable is False
    assert report.outcome is EvaluationOutcome.FAILED
    required = [
        r for r in report.results if r.invariant is not ProtectedInvariant.PI8_CUSTOMER_OUTCOMES
    ]
    assert all(r.status is InvariantStatus.UNAVAILABLE for r in required)
    assert len(report.unavailable_invariants) == 8


def test_partial_evidence_leaves_only_unmeasured_invariants_unavailable(
    service, project_id, candidate
):
    """A.1 — absence is per-invariant, never silently backfilled."""
    record = service.create_candidate(candidate)
    partial = evidence_payload_for(
        healthy_metrics(validation_truth=ValidationTruth.UNAVAILABLE), project_id
    )
    record = service.record_evidence(record, partial)
    report = service.evaluate(
        record=record,
        baseline=healthy_metrics(),
        candidate_metrics=healthy_metrics(),
    )
    statuses = report.status_by_invariant
    assert statuses["PI-2"].value == "unavailable"
    assert statuses["PI-1"].value == "pass"
    assert "PI-2" in report.blocking_invariants
    assert report.promotable is False


def test_malformed_evidence_is_rejected(service, project_id, candidate):
    """A.2 malformed — a truncated content hash cannot support a PASS."""
    record = service.create_candidate(candidate)
    good = evidence_payload_for(healthy_metrics(), project_id)
    tampered = tuple(
        e.model_copy(update={"content_hash": "deadbeef"}) if i == 0 else e
        for i, e in enumerate(good)
    )
    record = service.record_evidence(record, tampered)
    report = service.evaluate(
        record=record,
        baseline=healthy_metrics(),
        candidate_metrics=healthy_metrics(),
    )
    assert report.promotable is False
    assert "PI-1" in report.blocking_invariants


def test_conflicting_evidence_for_one_invariant_blocks(service, project_id, candidate):
    """A.3 conflicting — two different hashes for the same source ref."""
    good = evidence_payload_for(healthy_metrics(), project_id)
    conflict = good[0].model_copy(update={"content_hash": "a" * 64})
    record = service.create_candidate(candidate)
    record = service.record_evidence(record, tuple(good) + (conflict,))
    report = service.evaluate(
        record=record,
        baseline=healthy_metrics(),
        candidate_metrics=healthy_metrics(),
    )
    assert report.promotable is False
    assert "PI-1" in report.blocking_invariants


def test_stale_evidence_blocks(service, project_id, candidate):
    """A.4 stale — old evidence is not evidence about the present."""
    old_time = datetime.now(timezone.utc) - timedelta(seconds=MAX_EVIDENCE_AGE_SECONDS + 60)
    good = evidence_payload_for(healthy_metrics(), project_id)
    stale = tuple(e.model_copy(update={"observed_at": old_time}) for e in good)
    record = service.create_candidate(candidate)
    record = service.record_evidence(record, stale)
    report = service.evaluate(
        record=record,
        baseline=healthy_metrics(),
        candidate_metrics=healthy_metrics(),
    )
    assert report.promotable is False
    assert len(report.unavailable_invariants) == 8


def test_evidence_from_another_project_is_rejected(service, other_project_id, candidate):
    """A.5 project mismatch — evidence must belong to the candidate's project."""
    foreign = evidence_payload_for(healthy_metrics(), other_project_id)
    record = service.create_candidate(candidate)
    record = service.record_evidence(record, foreign)
    report = service.evaluate(
        record=record,
        baseline=healthy_metrics(),
        candidate_metrics=healthy_metrics(),
    )
    assert report.promotable is False
    assert len(report.unavailable_invariants) == 8


def test_model_generated_evidence_never_satisfies_an_invariant(
    service, project_id, candidate
):
    """Gate 4/CR-05: Q4 (model) evidence is never a basis."""
    model_ref = EvidenceRef(
        source=EvidenceSource.NON_AUTHORITATIVE,
        source_ref=f"security:security_violations:{project_id}",
        content_hash="f" * 64,
    )
    record = service.create_candidate(candidate)
    record = service.record_evidence(record, (model_ref,))
    report = service.evaluate(
        record=record,
        baseline=healthy_metrics(),
        candidate_metrics=healthy_metrics(),
    )
    assert report.promotable is False
    assert report.result_for(ProtectedInvariant.PI1_SECURITY).status is (
        InvariantStatus.UNAVAILABLE
    )


# ── B. EVALUATION ────────────────────────────────────────────────────────────


def test_all_nine_invariants_pass_yields_a_promotable_report(passing_report):
    assert passing_report.promotable is True
    assert passing_report.blocking_invariants == ()


@pytest.mark.parametrize(
    ("overrides", "expected_blocking"),
    [
        ({"security_violations": 1}, "PI-1"),
        ({"validation_truth": ValidationTruth.FAILED}, "PI-2"),
        ({"review_approved": False}, "PI-3"),
        ({"completion_succeeded": False}, "PI-4"),
        ({"tests_passed": 8}, "PI-5"),
        ({"failure_rate": 0.5}, "PI-6"),
        ({"retry_rate": 0.4}, "PI-6"),
        ({"latency_ms": 10_000.0}, "PI-7"),
        ({"isolation_violations": 1}, "PI-9"),
        ({"cross_project_access_attempts": 1}, "PI-9"),
    ],
)
def test_a_single_failing_invariant_blocks_promotion(
    service, project_id, candidate, overrides, expected_blocking
):
    """B.2 — one failing invariant is enough; there is no partial credit."""
    metrics = healthy_metrics(**overrides)
    record = service.create_candidate(candidate)
    record = service.record_evidence(record, evidence_payload_for(metrics, project_id))
    report = service.evaluate(
        record=record, baseline=healthy_metrics(), candidate_metrics=metrics
    )
    assert report.promotable is False
    assert expected_blocking in report.blocking_invariants


def test_multiple_failing_invariants_are_all_reported(service, project_id, candidate):
    """B.3 — every failure is named, not just the first."""
    metrics = healthy_metrics(
        security_violations=2,
        validation_truth=ValidationTruth.FAILED,
        latency_ms=99_999.0,
    )
    record = service.create_candidate(candidate)
    record = service.record_evidence(record, evidence_payload_for(metrics, project_id))
    report = service.evaluate(
        record=record, baseline=healthy_metrics(), candidate_metrics=metrics
    )
    assert report.promotable is False
    assert {"PI-1", "PI-2", "PI-7"}.issubset(set(report.blocking_invariants))


def test_security_violation_disqualifies_despite_gains_everywhere_else(
    service, project_id, candidate
):
    """Gate 19A-8 §5 absolute-invariant tripwire (RM-01, no trading)."""
    candidate_metrics = healthy_metrics(
        security_violations=1,  # catastrophic
        latency_ms=1.0,  # enormous gain
    )
    record = service.create_candidate(candidate)
    record = service.record_evidence(
        record, evidence_payload_for(candidate_metrics, project_id)
    )
    report = service.evaluate(
        record=record,
        baseline=healthy_metrics(latency_ms=10_000.0, failure_rate=0.9, retry_rate=0.9),
        candidate_metrics=candidate_metrics,
    )
    assert report.promotable is False
    assert "PI-1" in report.blocking_invariants
    # The gains are still recorded honestly — they simply do not compensate.
    assert report.result_for(ProtectedInvariant.PI7_LATENCY_RESOURCES).status is (
        InvariantStatus.PASS
    )


def test_absent_invariant_metrics_report_unavailable_not_pass(project_id):
    """B.4 — a metric that was never measured is UNAVAILABLE, not PASS."""
    evaluator = RegressionEvaluator()
    report = evaluator.evaluate(
        candidate_id=uuid.uuid4(),
        project_id=project_id,
        scope_kind="project",
        baseline=healthy_metrics(),
        candidate=empty_metrics(),
        evidence=evidence_payload_for(healthy_metrics(), project_id),
    )
    assert report.promotable is False
    assert report.result_for(ProtectedInvariant.PI6_RELIABILITY).status is (
        InvariantStatus.UNAVAILABLE
    )


def test_evaluator_exception_fails_closed(monkeypatch, project_id, passing_evidence):
    """B.6 — an evaluator that blows up reports ERROR, never PASSED."""
    evaluator = RegressionEvaluator()

    def _boom(**kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(evaluator, "_evaluate", _boom)
    report = evaluator.evaluate(
        candidate_id=uuid.uuid4(),
        project_id=project_id,
        scope_kind="project",
        baseline=healthy_metrics(),
        candidate=healthy_metrics(),
        evidence=passing_evidence,
    )
    assert report.outcome is EvaluationOutcome.ERROR
    assert report.promotable is False
    assert all(r.status is InvariantStatus.UNAVAILABLE for r in report.results)


def test_a_report_missing_an_invariant_cannot_be_constructed(passing_report):
    """B.5 — a malformed evaluator result is rejected by the model itself."""
    import pydantic

    payload = passing_report.model_dump(mode="json")
    payload["results"] = payload["results"][:-1]
    with pytest.raises(pydantic.ValidationError):
        type(passing_report).model_validate(payload)


def test_promotable_cannot_be_asserted_against_its_own_results(passing_report):
    """B.5 — a report cannot claim promotability its results contradict."""
    import pydantic

    payload = passing_report.model_dump(mode="json")
    payload["results"][0]["status"] = InvariantStatus.FAIL.value
    with pytest.raises(pydantic.ValidationError):
        type(passing_report).model_validate(payload)