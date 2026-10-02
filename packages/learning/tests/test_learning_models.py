"""Immutability, schema identity, and scope-isolation tests — Gate 2 / Gate 8."""

from __future__ import annotations

import uuid

import pytest
from pydantic import ValidationError

from autoforge_learning.models import (
    SCHEMA_VERSION,
    EvidenceRef,
    EvidenceSource,
    ExperienceRecord,
    LearningAuthority,
    LearningCandidate,
    LearningScope,
    LearningScopeKind,
    LearningSignal,
    SignalPolarity,
    TestOutcome,
    ValidationSummary,
    ValidationTruth,
)


def _scope(project_id: uuid.UUID | None = None, **kw) -> LearningScope:
    return LearningScope(
        kind=kw.pop("kind", LearningScopeKind.PROJECT),
        project_id=project_id or uuid.uuid4(),
        **kw,
    )


def _evidence(source: EvidenceSource = EvidenceSource.DETERMINISTIC_VALIDATION) -> EvidenceRef:
    return EvidenceRef.from_payload(source=source, source_ref="t", payload={"k": "v"})


# ── IMMUTABILITY ─────────────────────────────────────────────────────────────


def test_experience_record_cannot_be_mutated():
    rec = ExperienceRecord(scope=_scope(), evidence=(_evidence(),))
    with pytest.raises(ValidationError):
        rec.completion_succeeded = True  # type: ignore[misc]


def test_candidate_cannot_be_mutated():
    cand = LearningCandidate(scope=_scope(), kind="pattern_template", summary="s")
    with pytest.raises(ValidationError):
        cand.approval_state = "approved"  # type: ignore[misc]


def test_signal_cannot_be_mutated():
    sig = LearningSignal(scope=_scope(), polarity=SignalPolarity.POSITIVE, metric="m")
    with pytest.raises(ValidationError):
        sig.confidence = 1.0  # type: ignore[misc]


def test_evidence_ref_cannot_be_mutated():
    ref = _evidence()
    with pytest.raises(ValidationError):
        ref.content_hash = "tampered"  # type: ignore[misc]


def test_models_reject_unknown_fields():
    with pytest.raises(ValidationError):
        ExperienceRecord(scope=_scope(), unexpected_field="x")  # type: ignore[call-arg]


# ── SCHEMA IDENTITY / SERIALIZATION ───────────────────────────────────────────


def test_schema_version_is_explicit_on_every_model():
    for model in (
        ExperienceRecord(scope=_scope()),
        LearningCandidate(scope=_scope(), kind="pattern_template", summary="s"),
        LearningSignal(scope=_scope(), polarity=SignalPolarity.POSITIVE, metric="m"),
        _evidence(),
    ):
        assert model.schema_version == SCHEMA_VERSION


def test_serialization_is_stable_and_deterministic():
    rec = ExperienceRecord(scope=_scope(), evidence=(_evidence(),))
    assert rec.canonical_json() == rec.canonical_json()
    assert rec.record_hash() == rec.record_hash()
# ── NO FABRICATED VALUES ──────────────────────────────────────────────────────


def test_unavailable_validation_is_not_a_pass():
    assert ValidationSummary.unavailable().truth is ValidationTruth.UNAVAILABLE
    assert not ValidationSummary.unavailable().is_available
    assert not ValidationSummary.unavailable().truth.is_positive


def test_test_outcome_represents_absence_as_none_not_zero():
    outcome = TestOutcome.unavailable()
    assert outcome.total is None
    assert outcome.passed is None
    assert not outcome.is_available


# ── AUTHORITY / LEVEL 5 ──────────────────────────────────────────────────────


def test_candidate_cannot_carry_level_5_authority():
    with pytest.raises(ValidationError):
        LearningCandidate(
            scope=_scope(),
            kind="pattern_template",
            summary="s",
            authority=LearningAuthority.L5_SECURITY_POLICY,
        )


def test_level_5_is_recognised_but_unreachable():
    assert LearningAuthority.L5_SECURITY_POLICY.level == 5
    assert LearningAuthority.L5_SECURITY_POLICY.is_security_authority


def test_candidate_is_inert_by_default():
    cand = LearningCandidate(scope=_scope(), kind="pattern_template", summary="s")
    assert cand.is_inert


def test_model_annotation_is_typed_non_authoritative():
    cand = LearningCandidate(
        scope=_scope(),
        kind="pattern_template",
        summary="s",
        model_annotation="I am approved",
    )
    assert cand.model_annotation_authoritative is False
    with pytest.raises(ValidationError):
        LearningCandidate(
            scope=_scope(),
            kind="pattern_template",
            summary="s",
            model_annotation_authoritative=True,  # type: ignore[arg-type]
        )


# ── SCOPE / PROJECT ISOLATION ────────────────────────────────────────────────


def test_scope_requires_a_project_id():
    with pytest.raises(ValidationError):
        LearningScope(kind=LearningScopeKind.PROJECT)  # type: ignore[call-arg]


def test_candidate_from_project_a_never_applies_to_project_b():
    a = _scope(uuid.uuid4())
    b = _scope(uuid.uuid4())
    assert not a.matches(b)
    assert not b.matches(a)


def test_project_scope_does_not_widen_to_other_scope_kinds():
    project = _scope()
    task = _scope(project.project_id, kind=LearningScopeKind.TASK_TYPE, task_type="cobol")
    assert not project.matches(task)
    assert task.matches(project) is False


def test_workflow_scope_requires_workflow_id():
    with pytest.raises(ValidationError):
        LearningScope(kind=LearningScopeKind.WORKFLOW_TYPE, project_id=uuid.uuid4())


def test_no_security_scope_kind_exists():
    """Gate 19A §2.1: GLOBAL_SECURITY etc. are absent, not merely unset."""
    values = {k.value for k in LearningScopeKind}
    assert "GLOBAL_SECURITY" not in values
    assert "GLOBAL_IDENTITY" not in values
    assert "GLOBAL_AUTHORIZATION" not in values
    assert "GLOBAL_CREDENTIAL" not in values


def test_global_non_security_scope_never_crosses_projects():
    scope = _scope(kind=LearningScopeKind.GLOBAL_NON_SECURITY)
    assert not scope.matches(_scope(uuid.uuid4()))


# ── EVIDENCE QUALITY ─────────────────────────────────────────────────────────


def test_model_generated_evidence_is_never_authoritative():
    ref = EvidenceRef.from_payload(
        source=EvidenceSource.NON_AUTHORITATIVE, source_ref="m", payload={"x": 1}
    )
    assert not ref.is_authoritative
    rec = ExperienceRecord(scope=_scope(), evidence=(ref,))
    assert not rec.is_evidence_backed


def test_deterministic_evidence_is_q1():
    assert _evidence().quality.value == "q1"
    assert _evidence().is_authoritative


def test_experience_without_evidence_is_not_evidence_backed():
    assert not ExperienceRecord(scope=_scope()).is_evidence_backed
    assert ExperienceRecord(scope=_scope(), evidence=(_evidence(),)).is_evidence_backed


def test_roundtrip_preserves_record():
    rec = ExperienceRecord(scope=_scope(), completion_succeeded=True)
    restored = ExperienceRecord.model_validate_json(rec.canonical_json())
    assert restored.record_hash() == rec.record_hash()