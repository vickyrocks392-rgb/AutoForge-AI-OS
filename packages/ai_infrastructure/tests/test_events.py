"""Tests for canonical event publishing and vocabulary preservation."""

from __future__ import annotations

import uuid

from autoforge_events.event_types import EventType
from autoforge_events.base import BaseEvent

from autoforge_ai_infrastructure.events import AIInfrastructureEvents
from autoforge_ai_infrastructure.metadata import AttemptRecord
from tests.helpers import RecordingEventSink


def _record() -> AttemptRecord:
    return AttemptRecord(
        execution_id=uuid.uuid4(),
        model_id="m1",
        provider_id="p1",
        attempt_number=1,
        error=ValueError("boom"),
        classification="retryable",
        succeeded=False,
        followed_by_failover=False,
    )


def test_events_disabled_without_sink():
    events = AIInfrastructureEvents(sink=None)
    assert events.enabled is False
    # Does not raise; just returns the event.
    event = events.failure_detected(_record())
    assert isinstance(event, BaseEvent)


def test_events_are_canonical_base_events():
    sink = RecordingEventSink()
    events = AIInfrastructureEvents(sink=sink)
    event = events.failure_detected(_record())
    assert isinstance(event, BaseEvent)


def test_failure_detected_uses_canonical_type():
    sink = RecordingEventSink()
    events = AIInfrastructureEvents(sink=sink)
    event = events.failure_detected(_record())
    assert event.event_type == EventType.FAILURE_DETECTED
    assert event.event_type.value == "failure.detected"


def test_checkpoint_restored_uses_canonical_type():
    sink = RecordingEventSink()
    events = AIInfrastructureEvents(sink=sink)
    event = events.checkpoint_restored(
        execution_id=uuid.uuid4(),
        checkpoint_id=uuid.uuid4(),
        project_id=uuid.uuid4(),
    )
    assert event.event_type == EventType.CHECKPOINT_RESTORED
    assert event.event_type.value == "checkpoint.restored"


def test_all_published_events_are_canonical():
    """Every event type emitted by the factory exists in the frozen
    ``autoforge_events`` vocabulary (nothing invented)."""
    sink = RecordingEventSink()
    events = AIInfrastructureEvents(sink=sink)
    exec_id = uuid.uuid4()
    events.failure_detected(_record())
    events.recovery_started(exec_id, "retry", "p1", "m1")
    events.service_degraded(exec_id, "p1", "failover")
    events.recovery_completed(exec_id, "m1", "p1", attempts=2, failovers=1)
    events.recovery_failed(exec_id, [], "exhausted")
    events.checkpoint_restored(exec_id, uuid.uuid4(), uuid.uuid4())

    canonical_types = set(EventType)
    for e in sink.events:
        assert isinstance(e, BaseEvent)
        assert e.event_type in canonical_types