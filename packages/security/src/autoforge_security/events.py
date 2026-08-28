"""
Security Domain Event Definitions and Publisher for AutoForge Security (Phase 15).
"""

from __future__ import annotations

import uuid
from typing import Any

from autoforge_events.base import BaseEvent
from autoforge_events.event_types import EventCategory, EventType

from autoforge_security.models import (
    ApprovalGateStatus,
    AuditRecord,
    HITLApprovalGate,
    Subject,
)


def _to_uuid(val: str | None) -> uuid.UUID:
    """Deterministic UUID generation from string."""
    if not val:
        return uuid.uuid4()
    return uuid.uuid5(uuid.NAMESPACE_DNS, val)


class SecurityEventPublisher:
    """
    Publishes security and governance occurrences onto the CanonicalEventBus.
    """

    def __init__(self, canonical_bus: Any | None = None, source: str = "autoforge-security") -> None:
        self._bus = canonical_bus
        self._source = source

    def publish_audit_event(self, record: AuditRecord) -> None:
        """Publish a canonical audit event."""
        if not self._bus:
            return

        metadata: dict[str, Any] = {
            "source": self._source,
            "audit_id": record.audit_id,
            "actor_id": record.actor_id,
            "actor_type": record.actor_type.value,
            "action": record.action,
            "resource": record.resource,
            "decision": record.decision.value,
            "outcome": record.outcome,
            "reason": record.reason,
            "project_id": record.project_id,
            "workflow_id": record.workflow_id,
            "task_id": record.task_id,
            "worker_id": record.worker_id,
            "correlation_id": record.correlation_id,
            "trace_id": record.trace_id,
            "details": record.details,
        }

        corr_id = uuid.UUID(record.correlation_id) if record.correlation_id and len(record.correlation_id) == 36 else None

        event = BaseEvent(
            event_id=uuid.uuid4(),
            event_type=EventType.TASK_UPDATED,
            event_category=EventCategory.SYSTEM_EVENT,
            aggregate_id=_to_uuid(record.audit_id),
            aggregate_type="AuditRecord",
            correlation_id=corr_id,
            metadata=metadata,
        )
        self._bus.publish(event)

    def publish_hitl_gate_created(self, gate: HITLApprovalGate) -> None:
        """Publish HITL approval gate requested event."""
        if not self._bus:
            return

        metadata: dict[str, Any] = {
            "source": self._source,
            "gate_id": gate.gate_id,
            "action": gate.action.value,
            "description": gate.description,
            "requested_by": gate.requested_by_subject_id,
            "required_approvers": gate.required_approvers,
            "status": gate.status.value,
            "project_id": gate.project_id,
            "workflow_id": gate.workflow_id,
            "task_id": gate.task_id,
            "execution_id": gate.execution_id,
        }

        wf_uuid = uuid.UUID(gate.workflow_id) if gate.workflow_id and len(gate.workflow_id) == 36 else None

        event = BaseEvent(
            event_id=uuid.uuid4(),
            event_type=EventType.APPROVAL_REQUIRED,
            event_category=EventCategory.APPROVAL,
            aggregate_id=_to_uuid(gate.gate_id),
            aggregate_type="ApprovalGate",
            correlation_id=wf_uuid,
            metadata=metadata,
        )
        self._bus.publish(event)

    def publish_hitl_gate_decided(self, gate: HITLApprovalGate) -> None:
        """Publish HITL approval gate decided event."""
        if not self._bus:
            return

        metadata: dict[str, Any] = {
            "source": self._source,
            "gate_id": gate.gate_id,
            "action": gate.action.value,
            "status": gate.status.value,
            "decisions_count": len(gate.decisions),
            "project_id": gate.project_id,
            "workflow_id": gate.workflow_id,
            "task_id": gate.task_id,
            "execution_id": gate.execution_id,
        }

        wf_uuid = uuid.UUID(gate.workflow_id) if gate.workflow_id and len(gate.workflow_id) == 36 else None

        event = BaseEvent(
            event_id=uuid.uuid4(),
            event_type=EventType.APPROVAL_DECIDED,
            event_category=EventCategory.APPROVAL,
            aggregate_id=_to_uuid(gate.gate_id),
            aggregate_type="ApprovalGate",
            correlation_id=wf_uuid,
            metadata=metadata,
        )
        self._bus.publish(event)
