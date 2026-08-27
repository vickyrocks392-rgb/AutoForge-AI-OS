"""Test Canonical Event integration for Review Platform (Section 21).

Verifies that:
- ReviewEvents publishes canonical AutoForge events without modifying vocabulary
- Safe publishing prevents event sink exceptions from crashing review execution
- Aggregate ID and Correlation ID are correctly attached
- emit_approved, emit_rejected, emit_changes_requested, and emit_completed work accurately
"""

from __future__ import annotations

import uuid

import pytest

from autoforge_events.base import BaseEvent
from autoforge_events.event_types import EventCategory, EventType

from autoforge_review.events import ReviewEvents


def test_review_events_emit_completed() -> None:
    """emit_completed constructs and publishes a valid REVIEW_COMPLETED event."""
    published: list[BaseEvent] = []

    class Sink:
        def publish(self, event: BaseEvent) -> None:
            published.append(event)

    sink = Sink()
    events = ReviewEvents(sink)

    corr_id = uuid.uuid4()
    events.emit_completed(
        "r-100",
        gate="pass",
        decision="approved",
        correlation_id=corr_id,
        metadata={"extra": "data"},
    )

    assert len(published) == 1
    evt = published[0]
    assert evt.event_type == EventType.REVIEW_COMPLETED
    assert evt.event_category == EventCategory.REVIEW
    assert evt.correlation_id == corr_id
    assert evt.metadata["gate"] == "pass"
    assert evt.metadata["decision"] == "approved"
    assert evt.metadata["extra"] == "data"


def test_review_events_emit_approved_rejected_changes() -> None:
    """Specific event emitters create corresponding canonical event types."""
    published: list[BaseEvent] = []

    class Sink:
        def publish(self, event: BaseEvent) -> None:
            published.append(event)

    sink = Sink()
    events = ReviewEvents(sink)

    events.emit_approved("r-app", metadata={"status": "approved"})
    events.emit_rejected("r-rej", metadata={"status": "rejected"})
    events.emit_changes_requested("r-chg", metadata={"status": "changes"})

    assert len(published) == 3
    assert published[0].event_type == EventType.REVIEW_APPROVED
    assert published[1].event_type == EventType.REVIEW_REJECTED
    assert published[2].event_type == EventType.REVIEW_CHANGES_REQUESTED


@pytest.mark.asyncio
async def test_review_events_generic_async_emit() -> None:
    """Generic emit maps event names to canonical event payloads."""
    published: list[BaseEvent] = []

    class Sink:
        def publish(self, event: BaseEvent) -> None:
            published.append(event)

    events = ReviewEvents(Sink())

    class Payload:
        review_id = "r-200"
        correlation_id = uuid.uuid4()
        metadata = {"version": "1.0"}

    await events.emit("review.started", Payload())
    await events.emit("review.completed", Payload(), gate="pass", decision="approved")
    await events.emit("review.cycle_completed", Payload())

    assert len(published) == 3
    for evt in published:
        assert evt.event_category == EventCategory.REVIEW


def test_review_events_safe_publish_absorbs_sink_errors() -> None:
    """Sink exceptions must never escape or interrupt review execution."""
    class FailingSink:
        def publish(self, event: BaseEvent) -> None:
            raise RuntimeError("Database connection lost")

    events = ReviewEvents(FailingSink())
    # Should not raise
    events.emit_completed("r-fail", gate="fail", decision="rejected")
