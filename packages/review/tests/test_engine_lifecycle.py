"""Test Review Engine lifecycle (Sections 5, 29).

The engine must: receive a request, identify scope, gather evidence, apply
policies, run deterministic checks, aggregate findings, determine the
quality-gate outcome, produce a structured provenance-aware result, and
terminate deterministically.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest

from autoforge_execution.models import CommandResult, TestResultSummary

from autoforge_review.engine import ReviewEngine
from autoforge_review.errors import ReviewValidationError
from autoforge_review.models import (
    GateStatus,
    ReviewCategory,
    ReviewDecision,
    ReviewEvidence,
    ReviewLoopStatus,
    ReviewRequest,
    ReviewResult,
)

pytestmark = pytest.mark.asyncio


async def test_engine_receives_request_and_produces_result(engine: ReviewEngine) -> None:
    """Engine must accept a request and produce a structured ReviewResult."""
    req = ReviewRequest(
        review_id="lifecycle-1",
        project_id=uuid.uuid4(),
        correlation_id=uuid.uuid4(),
        categories=frozenset({ReviewCategory.DOCUMENTATION}),
        evidence=ReviewEvidence(
            source_files={"README.md": "# Project\n\nA test project."},
        ),
    )
    result = await engine.review(req)
    assert isinstance(result, ReviewResult)
    assert result.review_id == "lifecycle-1"
    assert result.decision in tuple(ReviewDecision)


async def test_engine_preserves_correlation_ids(engine: ReviewEngine) -> None:
    """Engine must preserve the full correlation/provenance chain (s.26)."""
    wf, corr = uuid.uuid4(), uuid.uuid4()
    req = ReviewRequest(
        review_id="corr-1",
        workflow_id=wf,
        task_id="t-1",
        execution_id="e-1",
        worker_id="worker-1",
        attempt_number=2,
        correlation_id=corr,
        categories=frozenset({ReviewCategory.DOCUMENTATION}),
        evidence=ReviewEvidence(source_files={"README.md": "# Title\n\nBody."}),
    )
    result = await engine.review(req)
    assert result.workflow_id == wf
    assert result.task_id == "t-1"
    assert result.execution_id == "e-1"
    assert result.worker_id == "worker-1"
    assert result.attempt_number == 2
    assert result.correlation_id == corr


async def test_engine_records_policy_version(engine: ReviewEngine) -> None:
    """Results must record the policy version for reproducibility (s.32)."""
    req = ReviewRequest(
        review_id="pol-1",
        categories=frozenset({ReviewCategory.DOCUMENTATION}),
        evidence=ReviewEvidence(source_files={"README.md": "# T"}),
    )
    result = await engine.review(req)
    assert result.policy_version == "1.0.0"


async def test_engine_rejects_malformed_request(engine: ReviewEngine) -> None:
    """Engine must reject malformed input deterministically."""
    with pytest.raises(ReviewValidationError):
        await engine.review(None)  # type: ignore[arg-type]


async def test_engine_scopes_review_to_requested_categories(
    engine: ReviewEngine,
) -> None:
    """Engine must only run requested categories (section 5: identify scope)."""
    req = ReviewRequest(
        review_id="scope-1",
        categories=frozenset({ReviewCategory.DOCUMENTATION}),
        evidence=ReviewEvidence(source_files={"README.md": "# Title\n\nBody."}),
    )
    result = await engine.review(req)
    assert result.categories_run == [ReviewCategory.DOCUMENTATION.value]


async def test_clean_review_passes_gate(engine: ReviewEngine) -> None:
    """A clean change with required docs must be APPROVED."""
    req = ReviewRequest(
        review_id="clean-1",
        categories=frozenset({ReviewCategory.DOCUMENTATION, ReviewCategory.CODE}),
        evidence=ReviewEvidence(
            source_files={
                "README.md": "# Title\n\n## Installation\n\n## Usage\n\n## License\n",
                "app.py": "def add(a, b):\n    return a + b\n",
            },
            changed_files=["app.py"],
            test_results=TestResultSummary(total_tests=4, passed_tests=4),
            build_exit_code=0,
        ),
    )
    result = await engine.review(req)
    assert result.decision == ReviewDecision.APPROVED
    assert result.gate.status == GateStatus.PASS
    assert result.gate.passed
    assert result.blocking_findings == 0
    assert result.repair is None


async def test_failing_tests_fail_the_gate(engine: ReviewEngine) -> None:
    """Deterministic test evidence failing → gate FAIL → changes requested."""
    req = ReviewRequest(
        review_id="tests-fail",
        categories=frozenset({ReviewCategory.CODE}),
        evidence=ReviewEvidence(
            source_files={"app.py": "x = 1\n"},
            test_results=TestResultSummary(
                total_tests=8,
                passed_tests=5,
                failed_tests=2,
                failure_details=["test_x failed"],
            ),
        ),
    )
    result = await engine.review(req)
    assert result.gate.status == GateStatus.FAIL
    assert result.decision == ReviewDecision.CHANGES_REQUESTED
    assert "tests_pass" in result.gate.violated_gates
    # A rejected outcome must produce a repair hand-off (section 18).
    assert result.repair is not None
    assert len(result.repair.findings) >= 1


async def test_high_security_finding_requests_changes(engine: ReviewEngine) -> None:
    """A HIGH deterministic security finding is blocking → repair hand-off."""
    req = ReviewRequest(
        review_id="sec-high",
        categories=frozenset({ReviewCategory.SECURITY}),
        evidence=ReviewEvidence(
            source_files={"app.py": "import os\nos.system('ls')\n"},
        ),
    )
    result = await engine.review(req)
    assert result.gate.status == GateStatus.FAIL
    assert result.decision == ReviewDecision.CHANGES_REQUESTED
    # Security is a default blocking category at severity HIGH.
    assert result.blocking_findings >= 1
    assert result.repair is not None
    assert result.repair.priority == "high"
    assert "security" in result.repair.findings_by_category


async def test_critical_finding_blocks_the_gate(engine: ReviewEngine) -> None:
    """A CRITICAL deterministic finding → BLOCKED → REJECTED (section 7)."""
    req = ReviewRequest(
        review_id="crit-block",
        categories=frozenset({ReviewCategory.CODE}),
        evidence=ReviewEvidence(
            source_files={"app.py": "x = 1\n"},
            build_exit_code=1,  # build failure is CRITICAL + blocking
        ),
    )
    result = await engine.review(req)
    assert result.gate.status == GateStatus.BLOCKED
    assert result.decision == ReviewDecision.REJECTED
    assert result.blocking_findings >= 1
    assert result.repair is not None
    assert result.repair.priority == "critical"


async def test_timeout_evidence_is_a_performance_finding(engine: ReviewEngine) -> None:
    """Timed-out command evidence must produce a deterministic perf finding."""
    timed_out = CommandResult(
        command=["pytest", "-q"],
        exit_code=124,
        duration_seconds=61.0,
        timed_out=True,
    )
    req = ReviewRequest(
        review_id="perf-timeout",
        categories=frozenset({ReviewCategory.PERFORMANCE}),
        evidence=ReviewEvidence(command_results=[timed_out]),
    )
    result = await engine.review(req)
    assert result.count_by_category.get("performance", 0) >= 1
    assert result.decision == ReviewDecision.CHANGES_REQUESTED


async def test_empty_evidence_is_explicit_vacuous_pass(engine: ReviewEngine) -> None:
    """No files AND no signals → explicit vacuous pass, not a silent review."""
    req = ReviewRequest(review_id="empty-1", evidence=ReviewEvidence())
    result = await engine.review(req)
    assert result.decision == ReviewDecision.APPROVED
    assert result.categories_run == []
    assert "no_target" in result.gate.satisfied_gates


async def test_engine_review_loop_is_bounded(engine: ReviewEngine) -> None:
    """review_loop must terminate with a deterministic bounded outcome."""
    req = ReviewRequest(
        review_id="bounded-1",
        categories=frozenset({ReviewCategory.DOCUMENTATION}),
        evidence=ReviewEvidence(source_files={"README.md": "# Title\n\nBody."}),
    )
    loop_result = await engine.review_loop(req, max_cycles=3)
    assert 1 <= len(loop_result.cycles) <= 3
    assert loop_result.status == ReviewLoopStatus.COMPLETED
    assert loop_result.final_result is not None
    assert loop_result.final_result.approved


async def test_engine_review_loop_stops_on_rejection(engine: ReviewEngine) -> None:
    """A rejecting review stops the loop deterministically (no retries)."""
    req = ReviewRequest(
        review_id="bounded-2",
        categories=frozenset({ReviewCategory.SECURITY}),
        evidence=ReviewEvidence(
            source_files={"app.py": "import os\nos.system('ls')\n"},
        ),
    )
    loop_result = await engine.review_loop(req, max_cycles=2)
    assert loop_result.status == ReviewLoopStatus.REPAIR_REQUESTED
    assert len(loop_result.cycles) == 1  # rejected → immediate deterministic stop
    assert loop_result.repair is not None

