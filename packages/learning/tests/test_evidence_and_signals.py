"""Evidence collection and signal derivation tests — Gate 3 / Gate 4."""

from __future__ import annotations

import uuid

from autoforge_learning.evidence import EvidenceCollector
from autoforge_learning.models import (
    EvidenceRef,
    EvidenceSource,
    LearningScope,
    LearningScopeKind,
    SignalPolarity,
    ValidationTruth,
)
from autoforge_learning.signals import (
    derive_confidence,
    disqualifying_signal,
)


class _FakeArtifact:
    def __init__(self, artifact_id, content_hash, status="COMMITTED"):
        self.artifact_id = artifact_id
        self.content_hash = content_hash
        self.status = status
        self.workflow_id = uuid.uuid4()


def _success_result(validation=None, approved=True):
    review = {"approved": approved, "reason": "ok", "evidence_files": 2}
    if validation is not None:
        review["validation"] = validation
    return {"success": True, "project_id": str(uuid.uuid4()), "final_review": review}


# ── REAL VALIDATION EVIDENCE ──────────────────────────────────────────────────


def test_real_passing_validation_is_recorded_as_passed():
    rec = EvidenceCollector().collect(
        project_id=uuid.uuid4(),
        finalize_result=_success_result(
            validation={
                "required": True,
                "passed": True,
                "reason": "all tests passed",
                "test_results": {"total_tests": 12, "passed_tests": 12, "failed_tests": 0},
            }
        ),
    )
    assert rec.validation.truth is ValidationTruth.PASSED
    assert rec.validation.test_outcome.total == 12
    assert rec.validation.test_outcome.passed == 12


def test_real_failing_validation_is_recorded_as_failed():
    rec = EvidenceCollector().collect(
        project_id=uuid.uuid4(),
        finalize_result=_success_result(
            validation={"required": True, "passed": False, "reason": "2 tests failed"}
        ),
    )
    assert rec.validation.truth is ValidationTruth.FAILED


def test_not_required_validation_is_not_a_pass():
    rec = EvidenceCollector().collect(
        project_id=uuid.uuid4(),
        finalize_result=_success_result(
            validation={"required": False, "passed": None, "reason": "no validation configured"}
        ),
    )
    assert rec.validation.truth is ValidationTruth.NOT_APPLICABLE
    assert not rec.validation.truth.is_positive


# ── MISSING / MALFORMED EVIDENCE ─────────────────────────────────────────────


def test_missing_validation_is_unavailable_not_passed():
    rec = EvidenceCollector().collect(
        project_id=uuid.uuid4(), finalize_result=_success_result(validation=None)
    )
    assert rec.validation.truth is ValidationTruth.UNAVAILABLE
    assert not rec.validation.is_available


def test_no_completion_result_yields_unavailable_not_success():
    rec = EvidenceCollector().collect(project_id=uuid.uuid4(), finalize_result=None)
    assert rec.validation.truth is ValidationTruth.UNAVAILABLE
    assert rec.completion_succeeded is None
    assert rec.review_approved is None
    assert not rec.is_evidence_backed


def test_malformed_validation_payload_is_unavailable():
    rec = EvidenceCollector().collect(
        project_id=uuid.uuid4(),
        finalize_result=_success_result(validation="totally not a mapping"),
    )
    assert rec.validation.truth is ValidationTruth.UNAVAILABLE


def test_missing_test_results_are_none_not_zero():
    rec = EvidenceCollector().collect(
        project_id=uuid.uuid4(),
        finalize_result=_success_result(validation={"required": True, "passed": True}),
    )
    assert rec.validation.test_outcome.total is None
    assert rec.validation.test_outcome.passed is None
    assert not rec.validation.test_outcome.is_available


# ── ARTIFACT EVIDENCE + PROVENANCE ───────────────────────────────────────────


def test_artifact_evidence_is_captured_with_content_hashes():
    artifacts = [
        _FakeArtifact(uuid.uuid4(), "a" * 64),
        _FakeArtifact(uuid.uuid4(), "b" * 64),
    ]
    rec = EvidenceCollector().collect(
        project_id=uuid.uuid4(),
        finalize_result=_success_result(),
        durable_artifacts=artifacts,
    )
    assert rec.artifact_count == 2
    assert set(rec.artifact_hashes) == {"a" * 64, "b" * 64}
    assert rec.is_evidence_backed
    assert rec.has_q1_evidence


def test_every_claim_carries_an_evidence_reference():
    rec = EvidenceCollector().collect(
        project_id=uuid.uuid4(),
        finalize_result=_success_result(validation={"required": True, "passed": True}),
        durable_artifacts=[_FakeArtifact(uuid.uuid4(), "c" * 64)],
    )
    sources = {e.source for e in rec.evidence}
    assert EvidenceSource.COMPLETION_GATE in sources
    assert EvidenceSource.DETERMINISTIC_VALIDATION in sources
    assert EvidenceSource.DURABLE_ARTIFACT in sources
    assert EvidenceSource.REVIEW_ENGINE in sources
    assert all(len(e.content_hash) >= 8 for e in rec.evidence)


def test_evidence_reference_carries_no_payload():
    """Gate 14 OS-03: references, not payloads -- the store cannot leak data."""
    rec = EvidenceCollector().collect(
        project_id=uuid.uuid4(),
        finalize_result=_success_result(validation={"required": True, "passed": True}),
    )
    for ref in rec.evidence:
        dumped = ref.model_dump(mode="json")
        assert set(dumped) == {
            "schema_version",
            "evidence_id",
            "source",
            "source_ref",
            "observed_at",
            "content_hash",
        }


def test_scope_is_project_scoped_by_default():
    rec = EvidenceCollector().collect(
        project_id=uuid.uuid4(), finalize_result=_success_result()
    )
    assert rec.scope.kind is LearningScopeKind.PROJECT


def test_no_result_means_no_fabricated_artifact_count():
    rec = EvidenceCollector().collect(
        project_id=uuid.uuid4(),
        finalize_result=_success_result(),
        durable_artifacts=None,
    )
    assert rec.artifact_count is None


# ── SIGNALS: DERIVED CONFIDENCE (replaces the tautological gate) ─────────────


def _evidence_ref(source=EvidenceSource.DETERMINISTIC_VALIDATION, n=1):
    return tuple(
        EvidenceRef.from_payload(source=source, source_ref=f"r{i}", payload={"i": i})
        for i in range(n)
    )


def test_zero_evidence_yields_zero_confidence_not_a_default():
    assert derive_confidence((), sample_size=50) == 0.0


def test_non_authoritative_evidence_yields_zero_confidence():
    assert (
        derive_confidence(
            _evidence_ref(EvidenceSource.NON_AUTHORITATIVE, 5), sample_size=50
        )
        == 0.0
    )


def test_single_execution_cannot_express_full_confidence():
    ev = _evidence_ref(n=1)
    assert derive_confidence(ev, sample_size=1) < derive_confidence(ev, sample_size=10)


def test_confidence_is_monotonic_in_sample_size():
    ev = _evidence_ref(n=2)
    values = [derive_confidence(ev, sample_size=n) for n in (1, 3, 6, 12, 24)]
    assert values == sorted(values)


def test_deterministic_evidence_outranks_aggregated():
    det = derive_confidence(_evidence_ref(EvidenceSource.DETERMINISTIC_VALIDATION), 12)
    agg = derive_confidence(_evidence_ref(EvidenceSource.TELEMETRY), 12)
    assert det > agg


def test_confidence_never_exceeds_one():
    for n in (1, 3, 10, 100, 1000):
        assert 0.0 <= derive_confidence(_evidence_ref(n=3), n) <= 1.0


def test_security_violation_is_disqualifying_not_a_negative_signal():
    scope = LearningScope(kind=LearningScopeKind.PROJECT, project_id=uuid.uuid4())
    sig = disqualifying_signal(
        scope=scope, metric="security_violation", tripped_constraints=("HC-01",)
    )
    assert sig.is_disqualifying
    assert sig.polarity is SignalPolarity.DISQUALIFYING
    assert sig.confidence == 0.0
    rec = EvidenceCollector().collect(
        project_id=uuid.uuid4(),
        finalize_result=_success_result(validation="totally not a mapping"),
    )
    assert rec.validation.truth is ValidationTruth.UNAVAILABLE


def test_missing_test_results_are_none_not_zero():
    rec = EvidenceCollector().collect(
        project_id=uuid.uuid4(),
        finalize_result=_success_result(validation={"required": True, "passed": True}),
    )
    assert rec.validation.test_outcome.total is None
    assert rec.validation.test_outcome.passed is None
    assert not rec.validation.test_outcome.is_available