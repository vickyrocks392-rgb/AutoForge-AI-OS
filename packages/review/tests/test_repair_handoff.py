"""Test Review to Phase 10 Repair Handoff (Sections 15, 18).

Verifies that:
- Review produces structured RepairRequest when review fails or requests changes
- Findings are grouped by domain category for role-specific workers (backend, security, docs, etc.)
- Provenance and correlation IDs (project_id, workflow_id, task_id, correlation_id) are preserved
- Priority calculation matches the worst severity of any finding
- RepairRequest only carries findings; repair execution is deferred to Phase 10
"""

from __future__ import annotations

import uuid

import pytest

from autoforge_execution.models import TestResultSummary

from autoforge_review.engine import ReviewEngine
from autoforge_review.models import (
    FindingClassification,
    FindingKind,
    RepairRequest,
    ReviewCategory,
    ReviewDecision,
    ReviewEvidence,
    ReviewFinding,
    ReviewRequest,
    Severity,
)


def test_repair_request_grouped_by_category() -> None:
    """RepairRequest groups findings by category string keys."""
    f_code = ReviewFinding(
        review_id="r-test",
        category=ReviewCategory.CODE,
        severity=Severity.HIGH,
        title="Uncaught Exception",
        classification=FindingClassification.DETERMINISTIC,
    )
    f_sec = ReviewFinding(
        review_id="r-test",
        category=ReviewCategory.SECURITY,
        severity=Severity.CRITICAL,
        title="Command Injection",
        classification=FindingClassification.DETERMINISTIC,
        blocking=True,
    )
    f_doc = ReviewFinding(
        review_id="r-test",
        category=ReviewCategory.DOCUMENTATION,
        severity=Severity.LOW,
        title="Missing Section",
        classification=FindingClassification.DETERMINISTIC,
    )

    repair = RepairRequest.build(
        review_id="r-test",
        findings=[f_code, f_sec, f_doc],
    )

    assert repair.review_id == "r-test"
    assert repair.priority == "critical"
    assert "code" in repair.findings_by_category
    assert "security" in repair.findings_by_category
    assert "documentation" in repair.findings_by_category
    assert str(f_code.finding_id) in repair.findings_by_category["code"]
    assert str(f_sec.finding_id) in repair.findings_by_category["security"]
    assert str(f_doc.finding_id) in repair.findings_by_category["documentation"]


def test_repair_request_priority_levels() -> None:
    """Priority drops from critical -> high -> medium based on findings."""
    f_crit = ReviewFinding(
        review_id="r", category=ReviewCategory.CODE, severity=Severity.CRITICAL, title="C"
    )
    f_high = ReviewFinding(
        review_id="r", category=ReviewCategory.CODE, severity=Severity.HIGH, title="H"
    )
    f_med = ReviewFinding(
        review_id="r", category=ReviewCategory.CODE, severity=Severity.MEDIUM, title="M"
    )
    f_low = ReviewFinding(
        review_id="r", category=ReviewCategory.CODE, severity=Severity.LOW, title="L"
    )

    assert RepairRequest.build(review_id="r", findings=[f_crit, f_high]).priority == "critical"
    assert RepairRequest.build(review_id="r", findings=[f_high, f_med]).priority == "high"
    assert RepairRequest.build(review_id="r", findings=[f_med, f_low]).priority == "medium"
    assert RepairRequest.build(review_id="r", findings=[]).priority == "medium"


@pytest.mark.asyncio
async def test_engine_attaches_repair_on_changes_requested() -> None:
    """ReviewResult includes populated RepairRequest on CHANGES_REQUESTED."""
    engine = ReviewEngine()
    project_id = uuid.uuid4()
    workflow_id = uuid.uuid4()
    correlation_id = uuid.uuid4()

    req = ReviewRequest(
        review_id="repair-e2e-1",
        project_id=project_id,
        workflow_id=workflow_id,
        task_id="task-42",
        execution_id="exec-99",
        worker_id="worker-backend",
        attempt_number=1,
        correlation_id=correlation_id,
        categories=frozenset({ReviewCategory.CODE}),
        evidence=ReviewEvidence(
            source_files={"service.py": "def bad():\n    try: pass\n    except: pass\n"},
            test_results=TestResultSummary(total_tests=5, failed_tests=1, failure_details=["assertion error"]),
        ),
    )

    result = await engine.review(req)

    assert result.decision == ReviewDecision.CHANGES_REQUESTED
    assert result.repair is not None
    repair = result.repair
    assert repair.review_id == "repair-e2e-1"
    assert repair.project_id == project_id
    assert repair.workflow_id == workflow_id
    assert repair.task_id == "task-42"
    assert repair.correlation_id == correlation_id
    assert len(repair.findings) >= 1
    assert "code" in repair.findings_by_category
