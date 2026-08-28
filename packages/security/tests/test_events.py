"""
Unit tests for SecurityEventPublisher over CanonicalEventBus.
"""

from __future__ import annotations

from autoforge_event_platform.adapter import CanonicalEventBus
from autoforge_events.event_types import EventCategory, EventType
from autoforge_security.events import SecurityEventPublisher
from autoforge_security.models import (
    ApprovalGateStatus,
    AuditRecord,
    ConsequentialAction,
    DecisionType,
    HITLApprovalGate,
    SubjectType,
)


def test_security_events_publication(event_bus: CanonicalEventBus) -> None:
    published_events = []
    event_bus.subscribe(
        published_events.append,
        event_types=[EventType.TASK_UPDATED, EventType.APPROVAL_REQUIRED, EventType.APPROVAL_DECIDED],
    )

    publisher = SecurityEventPublisher(canonical_bus=event_bus)

    # 1. Audit event
    rec = AuditRecord(
        actor_id="user_alice",
        actor_type=SubjectType.HUMAN,
        action="project.read",
        resource="proj_01",
        decision=DecisionType.ALLOW,
        reason="Granted",
    )
    publisher.publish_audit_event(rec)

    # 2. HITL Gate Created event
    gate = HITLApprovalGate(
        gate_id="gate_dep_123",
        action=ConsequentialAction.DEPLOYMENT,
        description="Deploy staging",
        requested_by_subject_id="user_alice",
        project_id="proj_01",
    )
    publisher.publish_hitl_gate_created(gate)

    # 3. HITL Gate Decided event
    gate.status = ApprovalGateStatus.APPROVED
    publisher.publish_hitl_gate_decided(gate)

    assert len(published_events) == 3
    assert published_events[0].event_category == EventCategory.SYSTEM_EVENT
    assert published_events[1].event_type == EventType.APPROVAL_REQUIRED
    assert published_events[2].event_type == EventType.APPROVAL_DECIDED
