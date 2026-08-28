"""
Immutable Audit Trail Engine for AutoForge Security (Phase 15).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from autoforge_security.models import (
    AuditRecord,
    AuthorizationDecision,
    AuthorizationRequest,
    DecisionType,
    Subject,
    SubjectType,
)
from autoforge_security.secrets import SecretsManager


class AuditEngine:
    """
    Centralized audit logging engine.
    Records every security-relevant evaluation, decision, and credential access.
    """

    def __init__(
        self,
        secrets_manager: SecretsManager | None = None,
        event_sink: Callable[[AuditRecord], None] | None = None,
    ) -> None:
        self._secrets = secrets_manager or SecretsManager()
        self._event_sink = event_sink
        self._records: list[AuditRecord] = []

    def record_decision(
        self,
        request: AuthorizationRequest,
        decision: AuthorizationDecision,
        outcome: str = "success",
    ) -> AuditRecord:
        """Record an authorization or governance evaluation."""
        if not decision.is_allowed:
            if decision.decision == DecisionType.REQUIRE_HITL:
                outcome = "pending_hitl"
            else:
                outcome = "denied"

        sanitized_details = self._secrets.redact_structure(decision.details)
        record = AuditRecord(
            actor_id=request.subject.subject_id,
            actor_type=request.subject.subject_type,
            actor_roles=request.subject.roles,
            action=request.action,
            resource=request.resource,
            decision=decision.decision,
            reason=decision.reason,
            outcome=outcome,
            project_id=request.project_id,
            workflow_id=request.workflow_id,
            task_id=request.task_id,
            worker_id=request.worker_id,
            execution_id=request.execution_id,
            correlation_id=request.correlation_id,
            trace_id=request.trace_id,
            policy_version=decision.policy_version,
            details=sanitized_details,
        )
        self._records.append(record)

        if self._event_sink:
            self._event_sink(record)

        return record

    def record_security_event(
        self,
        actor: Subject,
        action: str,
        resource: str,
        decision: DecisionType,
        reason: str,
        outcome: str = "success",
        *,
        project_id: str | None = None,
        workflow_id: str | None = None,
        task_id: str | None = None,
        worker_id: str | None = None,
        execution_id: str | None = None,
        correlation_id: str | None = None,
        trace_id: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> AuditRecord:
        """Record an arbitrary security event (e.g. login attempt, credential access)."""
        sanitized_details = self._secrets.redact_structure(details or {})
        record = AuditRecord(
            actor_id=actor.subject_id,
            actor_type=actor.subject_type,
            actor_roles=actor.roles,
            action=action,
            resource=resource,
            decision=decision,
            reason=reason,
            outcome=outcome,
            project_id=project_id,
            workflow_id=workflow_id,
            task_id=task_id,
            worker_id=worker_id,
            execution_id=execution_id,
            correlation_id=correlation_id,
            trace_id=trace_id,
            details=sanitized_details,
        )
        self._records.append(record)

        if self._event_sink:
            self._event_sink(record)

        return record

    def query_records(
        self,
        *,
        actor_id: str | None = None,
        action: str | None = None,
        outcome: str | None = None,
        project_id: str | None = None,
        limit: int = 100,
    ) -> list[AuditRecord]:
        """Query and filter audit records."""
        results: list[AuditRecord] = []
        for r in reversed(self._records):
            if actor_id and r.actor_id != actor_id:
                continue
            if action and r.action != action:
                continue
            if outcome and r.outcome != outcome:
                continue
            if project_id and r.project_id != project_id:
                continue
            results.append(r)
            if len(results) >= limit:
                break
        return results

    def list_all(self) -> list[AuditRecord]:
        """Return full audit log."""
        return list(self._records)
