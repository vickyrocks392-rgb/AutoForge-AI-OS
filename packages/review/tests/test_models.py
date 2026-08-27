"""Test Review domain models (sections 5, 14, 15, 16, 26, 29).

Models are frozen evidence records: field names, defaults, and immutability
are part of the contract consumed by Phase 10/12 and future workers.
"""

from __future__ import annotations

import uuid

import pytest
from pydantic import ValidationError

from autoforge_review.models import (
    AISourceMetadata,
    FindingClassification,
    FindingKind,
    FindingProvenance,
    GateStatus,
    QualityGateResult,
    RepairRequest,
    ReviewCategory,
    ReviewCycleRecord,
    ReviewDecision,
    ReviewEvidence,
    ReviewFinding,
    ReviewLoopResult,
    ReviewLoopStatus,
    ReviewRequest,
    ReviewResult,
    Severity,
)


def _finding(review_id: str = "r-1") -> ReviewFinding:
    return ReviewFinding(
        review_id=review_id,
        category=ReviewCategory.CODE,
        severity=Severity.HIGH,
        title="Issue",
        description="Fix this",
        classification=FindingClassification.DETERMINISTIC,
    )


def test_review_request_defaults_and_identity() -> None:
    """ReviewRequest auto-generates a review_id and defaults categories to all."""
    req = ReviewRequest()
    assert req.review_id
    assert req.attempt_number == 1
    assert req.evidence.source_files == {}
    assert not req.has_scope


def test_review_request_correlation_fields_are_uuid_typed() -> None:
    """Correlation/provenance IDs are UUIDs — strings must not be accepted."""
    with pytest.raises(ValidationError):
        ReviewRequest(correlation_id="not-a-uuid")  # type: ignore[arg-type]
    corr = uuid.uuid4()
    req = ReviewRequest(correlation_id=corr, workflow_id=uuid.uuid4())
    assert req.correlation_id == corr


def test_review_finding_defaults_and_freeze() -> None:
    """Findings are frozen evidence records with a deterministic identity."""
    f = _finding()
    assert isinstance(f.finding_id, uuid.UUID)
    assert f.blocking is False
    assert f.requires_hitl is False
    assert f.is_deterministic
    with pytest.raises(ValidationError):
        f.severity = Severity.CRITICAL  # type: ignore[misc]


def test_finding_provenance_records_rule_and_ai_source() -> None:
    """Provenance records policy version + rule id + AI metadata (s.32)."""
    prov = FindingProvenance(
        policy_version="1.2.3",
        rule_id="secret_leak",
        review_id="r-9",
        correlation_id=uuid.uuid4(),
    )
    assert prov.policy_version == "1.2.3"
    assert prov.rule_id == "secret_leak"
    assert prov.ai_source is None

    ai_prov = FindingProvenance(
        policy_version="1.2.3",
        ai_source=AISourceMetadata(
            executed=True,
            provider_id="p1",
            model_id="m1",
            prompt_version="review.v1",
        ),
    )
    assert ai_prov.ai_source is not None
    assert ai_prov.ai_source.model_id == "m1"
    assert ai_prov.ai_source.executed is True


def test_ai_source_metadata_records_absence() -> None:
    """AISourceMetadata must explicitly record when AI did NOT run."""
    meta = AISourceMetadata(executed=False)
    assert meta.executed is False
    assert meta.model_id is None


def test_review_result_minimal_and_counts() -> None:
    """ReviewResult requires gate + decision; counts default to zero."""
    result = ReviewResult(
        review_id="r-1",
        gate=QualityGateResult(status=GateStatus.PASS),
        decision=ReviewDecision.APPROVED,
    )
    assert result.findings == []
    assert result.categories_run == []
    assert result.deterministic_findings == 0
    assert result.ai_findings == 0
    assert result.blocking_findings == 0
    assert result.repair is None
    assert result.approved and not result.rejected


def test_review_result_rejected_property() -> None:
    """rejected is True for REJECTED and CHANGES_REQUESTED (repair triggers)."""
    for decision in (ReviewDecision.REJECTED, ReviewDecision.CHANGES_REQUESTED):
        result = ReviewResult(
            review_id="r-1",
            gate=QualityGateResult(status=GateStatus.FAIL),
            decision=decision,
        )
        assert result.rejected
    result = ReviewResult(
        review_id="r-1",
        gate=QualityGateResult(status=GateStatus.REQUIRES_HITL),
        decision=ReviewDecision.REQUIRES_HITL,
    )
    assert not result.rejected


def test_review_result_preserves_correlation() -> None:
    """ReviewResult preserves the full project→review correlation chain (s.26)."""
    wf, corr = uuid.uuid4(), uuid.uuid4()
    result = ReviewResult(
        review_id="r-1",
        workflow_id=wf,
        task_id="t-1",
        execution_id="e-1",
        worker_id="wk-1",
        attempt_number=2,
        correlation_id=corr,
        categories_run=["code"],
        gate=QualityGateResult(status=GateStatus.FAIL),
        decision=ReviewDecision.CHANGES_REQUESTED,
    )
    assert result.workflow_id == wf
    assert result.correlation_id == corr
    assert result.attempt_number == 2
    assert result.categories_run == ["code"]


def test_repair_request_build_groups_findings() -> None:
    """RepairRequest.build groups finding ids by category (section 18)."""
    f1 = _finding()
    f2 = ReviewFinding(
        review_id="r-1",
        category=ReviewCategory.SECURITY,
        severity=Severity.CRITICAL,
        title="Sec",
        classification=FindingClassification.DETERMINISTIC,
        blocking=True,
    )
    repair = RepairRequest.build(review_id="r-1", findings=[f1, f2])
    assert repair.review_id == "r-1"
    assert repair.request_id
    assert repair.findings == [f1, f2]
    assert repair.findings_by_category == {
        "code": [str(f1.finding_id)],
        "security": [str(f2.finding_id)],
    }
    assert repair.priority == "critical"  # worst severity wins
    assert "code" in repair.summary and "security" in repair.summary


def test_repair_request_priority_reflects_worst_severity() -> None:
    """Priority is deterministic from the worst finding severity."""
    high = RepairRequest.build(
        review_id="r-1",
        findings=[
            ReviewFinding(
                review_id="r-1",
                category=ReviewCategory.CODE,
                severity=Severity.HIGH,
                title="H",
                classification=FindingClassification.DETERMINISTIC,
            )
        ],
    )
    medium = RepairRequest.build(review_id="r-1", findings=[])
    assert high.priority == "high"
    assert medium.priority == "medium"


def test_repair_request_carries_correlation() -> None:
    """Repair hand-off preserves correlation for the Phase 10 loop (s.26)."""
    corr, wf = uuid.uuid4(), uuid.uuid4()
    repair = RepairRequest.build(
        review_id="r-1",
        findings=[],
        task_id="t-1",
        workflow_id=wf,
        correlation_id=corr,
    )
    assert repair.correlation_id == corr
    assert repair.workflow_id == wf
    assert repair.task_id == "t-1"


def test_review_cycle_record_is_bounded() -> None:
    """ReviewCycleRecord records one bounded cycle (section 29)."""
    record = ReviewCycleRecord(
        cycle=1,
        review_id="r-1",
        gate=QualityGateResult(status=GateStatus.FAIL, reasons=["x"]),
        decision=ReviewDecision.CHANGES_REQUESTED,
        finding_count=3,
    )
    assert record.cycle == 1
    assert record.finding_count == 3
    assert record.gate.status == GateStatus.FAIL


def test_review_loop_result_defaults() -> None:
    """ReviewLoopResult exposes status, cycles, final_result, repair (s.29)."""
    result = ReviewLoopResult(status=ReviewLoopStatus.COMPLETED, cycles=[])
    assert result.status == ReviewLoopStatus.COMPLETED
    assert result.final_result is None
    assert result.repair is None


def test_review_loop_status_vocabulary_is_stable() -> None:
    """Loop statuses cover the canonical bounded outcomes (section 29)."""
    values = {s.value for s in ReviewLoopStatus}
    assert {
        "completed",
        "repair_requested",
        "rejected",
        "blocked",
        "hitl",
        "limit_exceeded",
    }.issubset(values)


def test_gate_status_values() -> None:
    """Quality-gate outcomes are exactly the four canonical values (s.16)."""
    assert {s.value for s in GateStatus} == {
        "pass",
        "fail",
        "blocked",
        "requires_hitl",
    }


def test_quality_gate_result_passed_property() -> None:
    """QualityGateResult.passed reflects PASS only — no boolean collapse."""
    assert QualityGateResult(status=GateStatus.PASS).passed
    assert not QualityGateResult(
        status=GateStatus.REQUIRES_HITL, reasons=["hitl"]
    ).passed


def test_finding_kind_values_are_stable() -> None:
    """FindingKind values are stable ids for future worker routing (s.20)."""
    assert FindingKind.DEFECT.value == "defect"
    assert FindingKind.POLICY_VIOLATION.value == "policy_violation"
    assert FindingKind.SECURITY_VULNERABILITY.value == "security_vulnerability"
    assert FindingKind.PERFORMANCE_REGRESSION.value == "performance_regression"
    assert FindingKind.DOCUMENTATION_GAP.value == "documentation_gap"
    assert FindingKind.ARCHITECTURE_EXCEPTION.value == "architecture_exception"
    assert FindingKind.QUALITY.value == "quality_issue"


def test_review_evidence_review_files_scopes_to_changes() -> None:
    """review_files narrows to changed files when a change set is known."""
    evidence = ReviewEvidence(
        source_files={"a.py": "a", "b.py": "b"},
        changed_files=["a.py"],
    )
    assert evidence.review_files == {"a.py": "a"}
    all_files = ReviewEvidence(source_files={"a.py": "a"})
    assert all_files.review_files == {"a.py": "a"}

