"""Test Quality Gates (Section 16).

Quality Gates must be deterministic, produce structured results
(PASS/FAIL/BLOCKED/REQUIRES_HITL), and never collapse important semantics
into a single boolean.
"""

from __future__ import annotations

import pytest

from autoforge_review.engine import QualityGate, ReviewEngine, _build_gates
from autoforge_review.models import (
    FindingClassification,
    FindingKind,
    GateStatus,
    QualityGateResult,
    ReviewCategory,
    ReviewDecision,
    ReviewEvidence,
    ReviewFinding,
    ReviewRequest,
    Severity,
)
from autoforge_review.policies import ReviewPolicy, default_review_policy


def _gate_finding(**overrides: object) -> ReviewFinding:
    payload: dict[str, object] = {
        "review_id": "r-1",
        "category": ReviewCategory.CODE,
        "severity": Severity.MEDIUM,
        "title": "F",
        "classification": FindingClassification.DETERMINISTIC,
    }
    payload.update(overrides)
    return ReviewFinding(**payload)  # type: ignore[arg-type]


def test_gates_are_structured() -> None:
    """Each gate returns (bool, message) — structured, not a bare boolean."""
    gates = _build_gates(default_review_policy())
    for g in gates:
        passed, msg = g.check([], ReviewEvidence())
        assert isinstance(passed, bool)
        assert isinstance(msg, str)


def test_critical_finding_violates_no_critical_gate() -> None:
    """A CRITICAL blocking finding violates no_critical_findings (s.16)."""
    gates = _build_gates(default_review_policy())
    critical = [_gate_finding(severity=Severity.CRITICAL, blocking=True)]
    for g in gates:
        passed, _ = g.check(critical, ReviewEvidence())
        if g.name == "no_critical_findings":
            assert not passed


def test_no_findings_passes_all_context_free_gates() -> None:
    """No findings → every context-free gate passes."""
    gates = _build_gates(default_review_policy())
    for g in gates:
        passed, msg = g.check([], ReviewEvidence())
        assert passed, f"Gate {g.name} should pass with no findings (msg={msg})"


def test_medium_findings_do_not_fail_gates() -> None:
    """MEDIUM findings are advisory — they do not fail the default gates."""
    gates = _build_gates(default_review_policy())
    medium = [_gate_finding()]
    for g in gates:
        passed, _ = g.check(medium, ReviewEvidence())
        assert passed, f"Gate {g.name} must not fail on MEDIUM findings"


async def test_quality_gate_status_values() -> None:
    """Gate status must have explicit canonical values."""
    assert GateStatus.PASS.value == "pass"
    assert GateStatus.FAIL.value == "fail"
    assert GateStatus.BLOCKED.value == "blocked"
    assert GateStatus.REQUIRES_HITL.value == "requires_hitl"


async def test_gate_result_preserves_status_semantics() -> None:
    """QualityGateResult must not collapse PASS/FAIL/BLOCKED/HITL to a boolean."""
    result = QualityGateResult(
        status=GateStatus.BLOCKED,
        reasons=["Blocked by policy"],
        violated_gates=["no_critical_findings"],
    )
    assert result.status != GateStatus.PASS
    assert result.reasons == ["Blocked by policy"]
    assert not result.passed


def test_default_gates_are_inspectable() -> None:
    """The default gate set is explicit, named, and deterministic (s.6)."""
    gates = QualityGate.default_gates(default_review_policy())
    names = [g.name for g in gates]
    assert "no_critical_findings" in names
    assert "no_blocking_findings" in names
    assert "tests_pass" in names


async def test_engine_gate_pass_clean(engine: ReviewEngine) -> None:
    """Clean evidence → gate PASS → APPROVED."""
    req = ReviewRequest(
        review_id="gate-pass",
        categories=frozenset({ReviewCategory.DOCUMENTATION}),
        evidence=ReviewEvidence(source_files={"README.md": "# T\n\nBody."}),
    )
    result = await engine.review(req)
    assert result.gate.status == GateStatus.PASS
    assert result.gate.satisfied_gates
    assert result.gate.violated_gates == []
    assert result.decision == ReviewDecision.APPROVED


async def test_engine_gate_fail_on_failing_tests(engine: ReviewEngine) -> None:
    """Failing tests → tests_pass violated → gate FAIL → CHANGES_REQUESTED."""
    from autoforge_execution.models import TestResultSummary

    req = ReviewRequest(
        review_id="gate-fail",
        categories=frozenset({ReviewCategory.CODE}),
        evidence=ReviewEvidence(
            source_files={"app.py": "x = 1\n"},
            test_results=TestResultSummary(
                total_tests=2, failed_tests=2, failure_details=["a", "b"]
            ),
        ),
    )
    result = await engine.review(req)
    assert result.gate.status == GateStatus.FAIL
    assert "tests_pass" in result.gate.violated_gates
    assert "tests_pass" not in result.gate.satisfied_gates
    assert result.decision == ReviewDecision.CHANGES_REQUESTED


async def test_engine_gate_blocked_on_critical(engine: ReviewEngine) -> None:
    """CRITICAL blocking finding → gate BLOCKED → REJECTED (hard stop)."""
    req = ReviewRequest(
        review_id="gate-blocked",
        categories=frozenset({ReviewCategory.CODE}),
        evidence=ReviewEvidence(
            source_files={"app.py": "x = 1\n"},
            build_exit_code=1,
        ),
    )
    result = await engine.review(req)
    assert result.gate.status == GateStatus.BLOCKED
    assert "no_critical_findings" in result.gate.violated_gates
    assert result.decision == ReviewDecision.REJECTED


async def test_engine_gate_required_docs_missing(engine: ReviewEngine) -> None:
    """Documentation in scope with missing README → required_docs gate fails."""
    req = ReviewRequest(
        review_id="gate-docs",
        categories=frozenset({ReviewCategory.DOCUMENTATION}),
        evidence=ReviewEvidence(source_files={"app.py": "x = 1\n"}),
    )
    result = await engine.review(req)
    assert "required_docs_present" in result.gate.violated_gates
    assert result.gate.status == GateStatus.FAIL


async def test_engine_gate_hitl_when_policy_demands(engine: ReviewEngine) -> None:
    """A blocking finding of an HITL-required kind → REQUIRES_HITL (s.17)."""
    policy = ReviewPolicy(
        blocking_severity=Severity.LOW,
        blocking_categories=frozenset({ReviewCategory.ARCHITECTURE}),
    )
    hitl_engine = ReviewEngine(policy=policy)
    # duplicate_responsibility is ARCHITECTURE_EXCEPTION (LOW) → blocking under
    # this policy, and ARCHITECTURE_EXCEPTION is a default HITL-required kind.
    req = ReviewRequest(
        review_id="gate-hitl",
        categories=frozenset({ReviewCategory.ARCHITECTURE}),
        evidence=ReviewEvidence(
            source_files={
                "a.py": "class Dup:\n    pass\n",
                "b.py": "class Dup:\n    pass\n",
            },
        ),
    )
    result = await hitl_engine.review(req)
    dup = [f for f in result.findings if f.kind == FindingKind.ARCHITECTURE_EXCEPTION]
    assert dup, "expected duplicate-responsibility finding"
    assert dup[0].blocking and dup[0].requires_hitl
    assert result.gate.status == GateStatus.REQUIRES_HITL
    assert result.decision == ReviewDecision.REQUIRES_HITL

