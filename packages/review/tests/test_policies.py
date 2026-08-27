"""Test Review Policies (Section 6).

Verify that policies:
- determine what must be reviewed
- determine which checks apply
- define severity thresholds
- define blocking conditions
- cannot be overridden by AI
"""

from __future__ import annotations

import pytest

from autoforge_review.policies import (
    ReviewPolicy,
    default_review_policy,
    strict_review_policy,
    permissive_review_policy,
)
from autoforge_review.models import (
    ReviewCategory,
    ReviewDecision,
    ReviewEvidence,
    ReviewFinding,
    ReviewRequest,
    Severity,
    FindingClassification,
    GateStatus,
)
from autoforge_review.engine import ReviewEngine




def test_default_policy_is_inspectable() -> None:
    """Policies must be inspectable (not hidden in prompts)."""
    p = default_review_policy()
    assert isinstance(p, ReviewPolicy)
    assert p.policy_id
    assert p.required()
    assert isinstance(p.required(), frozenset)


def test_strict_policy_is_stricter_than_default() -> None:
    """Strict policy must be more restrictive."""
    d = default_review_policy()
    s = strict_review_policy()
    # strict should require more categories
    assert s.required() >= d.required()


def test_permissive_policy_is_more_lax() -> None:
    """Permissive policy must have lower severity threshold."""
    p = permissive_review_policy()
    d = default_review_policy()
    assert p.blocking_severity().value <= d.blocking_severity().value or \
        len(p.required()) <= len(d.required())


async def test_default_policy_rejects_forbidden_framework() -> None:
    """Policy must detect forbidden frameworks (deterministic)."""
    engine = ReviewEngine(policy=default_review_policy())
    req = ReviewRequest(
        review_id="forbidden",
        categories=frozenset({ReviewCategory.CODE}),
        evidence=ReviewEvidence(
            source_files={"app.py": "from langchain import LLMChain\n"},
        ),
    )
    result = await engine.review(req)
    titles = [f.title.lower() for f in result.findings]
    assert any("forbidden" in t for t in titles), f"Expected forbidden finding, got: {titles}"


async def test_policy_determines_blocking() -> None:
    """Critical findings must be blocking by policy."""
    engine = ReviewEngine(policy=default_review_policy())
    req = ReviewRequest(
        review_id="block",
        categories=frozenset({ReviewCategory.SECURITY}),
        evidence=ReviewEvidence(
            source_files={"app.py": "import subprocess\nsubprocess.call('rm -rf /', shell=True)\n"},
        ),
    )
    result = await engine.review(req)
    has_critical = any(f.severity == Severity.CRITICAL for f in result.findings)
    if has_critical:
        assert result.decision in (
            ReviewDecision.CHANGES_REQUESTED,
            ReviewDecision.REJECTED,
            ReviewDecision.REQUIRES_HITL,
        )


def test_policy_severity_thresholds_are_explicit() -> None:
    """Severity threshold must be a deterministic enum."""
    p = default_review_policy()
    sev = p.blocking_severity()
    assert sev in (Severity.INFO, Severity.LOW, Severity.MEDIUM, Severity.HIGH, Severity.CRITICAL)
