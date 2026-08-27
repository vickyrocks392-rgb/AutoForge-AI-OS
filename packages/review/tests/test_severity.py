"""Test Severity model and finding classification (Section 15).

Severity is an explicit deterministic model; AI may recommend but never
redefine severity policy.
"""

from __future__ import annotations

import uuid

import pytest

from autoforge_review.models import (
    Severity,
    FindingClassification,
    is_at_least,
    severity_rank,
    ReviewFinding,
    ReviewCategory,
)


def test_severity_has_five_levels() -> None:
    """Severity must be 5-level: INFO/LOW/MEDIUM/HIGH/CRITICAL."""
    assert Severity.INFO.value == "info"
    assert Severity.LOW.value == "low"
    assert Severity.MEDIUM.value == "medium"
    assert Severity.HIGH.value == "high"
    assert Severity.CRITICAL.value == "critical"


def test_severity_rank_orders_correctly() -> None:
    """Severity rank must order: INFO < LOW < MEDIUM < HIGH < CRITICAL."""
    assert severity_rank(Severity.INFO) < severity_rank(Severity.LOW)
    assert severity_rank(Severity.LOW) < severity_rank(Severity.MEDIUM)
    assert severity_rank(Severity.MEDIUM) < severity_rank(Severity.HIGH)
    assert severity_rank(Severity.HIGH) < severity_rank(Severity.CRITICAL)


def test_is_at_least_works_correctly() -> None:
    """is_at_least helper must compare ranks deterministically."""
    assert is_at_least(severity=Severity.CRITICAL, threshold=Severity.HIGH)
    assert is_at_least(severity=Severity.HIGH, threshold=Severity.HIGH)
    assert not is_at_least(severity=Severity.LOW, threshold=Severity.HIGH)
    assert is_at_least(severity=Severity.MEDIUM, threshold=Severity.LOW)


def test_finding_classification_has_two_types() -> None:
    """Classification must distinguish DETERMINISTIC from AI_ASSISTED."""
    assert FindingClassification.DETERMINISTIC.value == "deterministic"
    assert FindingClassification.AI_ASSISTED.value == "ai_assisted"


def _finding(**overrides: object) -> ReviewFinding:
    payload: dict[str, object] = {
        "finding_id": uuid.uuid4(),
        "review_id": "r1",
        "category": ReviewCategory.CODE,
        "severity": Severity.HIGH,
        "title": "Test",
        "description": "Test",
        "classification": FindingClassification.DETERMINISTIC,
    }
    payload.update(overrides)
    return ReviewFinding(**payload)  # type: ignore[arg-type]


def test_finding_carries_severity() -> None:
    """Finding must carry severity + classification."""
    f = _finding()
    assert f.severity == Severity.HIGH
    assert f.classification == FindingClassification.DETERMINISTIC


def test_finding_severity_immutable() -> None:
    """Severity is part of the frozen finding — policy, not AI, owns it."""
    f = _finding()
    with pytest.raises(Exception):
        f.severity = Severity.LOW  # type: ignore[misc]
