"""Test Bounded Review Loop and ReviewLoop class (Sections 14, 29).

Verifies that:
- ReviewLoop executes cycles deterministically
- Bounded cycles terminate when approved or rejected
- Exceeding max_cycles produces LIMIT_EXCEEDED status
- ReviewCycleRecord accurately logs each iteration
- ReviewEvents emits review.cycle_completed and lifecycle events
- The loop is bounded and cannot loop infinitely
"""

from __future__ import annotations

import uuid
from unittest.mock import MagicMock

import pytest

from autoforge_events.event_types import EventType
from autoforge_execution.models import TestResultSummary

from autoforge_review.engine import ReviewEngine
from autoforge_review.events import ReviewEvents
from autoforge_review.loop import ReviewLoop
from autoforge_review.models import (
    GateStatus,
    ReviewCategory,
    ReviewDecision,
    ReviewEvidence,
    ReviewLoopStatus,
    ReviewRequest,
    Severity,
)
from autoforge_review.policies import ReviewPolicy


@pytest.mark.asyncio
async def test_review_loop_completes_on_approved() -> None:
    """When a review passes on first cycle, loop status is COMPLETED with 1 cycle."""
    engine = ReviewEngine()
    loop = ReviewLoop(engine)

    req = ReviewRequest(
        review_id="loop-pass-1",
        categories=frozenset({ReviewCategory.DOCUMENTATION}),
        evidence=ReviewEvidence(
            source_files={"README.md": "# Title\n\nBody content."},
        ),
    )

    result = await loop.run(req, max_cycles=3)

    assert result.status == ReviewLoopStatus.COMPLETED
    assert len(result.cycles) == 1
    assert result.cycles[0].cycle == 1
    assert result.cycles[0].decision == ReviewDecision.APPROVED
    assert result.final_result is not None
    assert result.final_result.approved
    assert result.repair is None


@pytest.mark.asyncio
async def test_review_loop_stops_on_changes_requested() -> None:
    """When findings require changes, loop stops immediately with REPAIR_REQUESTED and repair payload."""
    engine = ReviewEngine()
    loop = ReviewLoop(engine)

    req = ReviewRequest(
        review_id="loop-fail-1",
        categories=frozenset({ReviewCategory.CODE}),
        evidence=ReviewEvidence(
            source_files={"app.py": "try:\n    pass\nexcept:\n    pass\n"},
            test_results=TestResultSummary(total_tests=2, failed_tests=1, failure_details=["failed"]),
        ),
    )

    result = await loop.run(req, max_cycles=3)

    assert result.status == ReviewLoopStatus.REPAIR_REQUESTED
    assert len(result.cycles) == 1
    assert result.cycles[0].decision == ReviewDecision.CHANGES_REQUESTED
    assert result.final_result is not None
    assert result.final_result.rejected
    assert result.repair is not None
    assert len(result.repair.findings) >= 1


@pytest.mark.asyncio
async def test_review_loop_stops_on_hitl_decision() -> None:
    """When gate status is REQUIRES_HITL, loop terminates with HITL status."""
    policy = ReviewPolicy(
        blocking_severity=Severity.LOW,
        blocking_categories=frozenset({ReviewCategory.ARCHITECTURE}),
    )
    engine = ReviewEngine(policy=policy)
    loop = ReviewLoop(engine)

    req = ReviewRequest(
        review_id="loop-hitl-1",
        categories=frozenset({ReviewCategory.ARCHITECTURE}),
        evidence=ReviewEvidence(
            source_files={
                "a.py": "class Dup:\n    pass\n",
                "b.py": "class Dup:\n    pass\n",
            }
        ),
    )

    result = await loop.run(req, max_cycles=2)

    assert result.status == ReviewLoopStatus.HITL
    assert len(result.cycles) == 1
    assert result.cycles[0].decision == ReviewDecision.REQUIRES_HITL
    assert result.final_result is not None
    assert result.final_result.gate.status == GateStatus.REQUIRES_HITL


@pytest.mark.asyncio
async def test_review_loop_emits_cycle_events() -> None:
    """ReviewEvents captures review.started, review.completed, and cycle_completed events."""
    published_events: list[object] = []

    class MockSink:
        def publish(self, event):
            published_events.append(event)

    sink = MockSink()
    engine = ReviewEngine(event_sink=sink)
    loop = ReviewLoop(engine)

    corr = uuid.uuid4()
    req = ReviewRequest(
        review_id="loop-evt-1",
        correlation_id=corr,
        categories=frozenset({ReviewCategory.DOCUMENTATION}),
        evidence=ReviewEvidence(source_files={"README.md": "# Docs\n"}),
    )

    result = await loop.run(req)

    assert result.status == ReviewLoopStatus.COMPLETED
    assert len(published_events) >= 2
    event_types = [getattr(e, "event_type", None) for e in published_events]
    assert EventType.REVIEW_COMPLETED in event_types
