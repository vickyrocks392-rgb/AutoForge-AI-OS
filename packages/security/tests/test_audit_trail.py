"""
Unit tests for AuditEngine and structured immutable audit records.
"""

from __future__ import annotations

from autoforge_security.audit import AuditEngine
from autoforge_security.models import (
    AuthorizationDecision,
    AuthorizationRequest,
    DecisionType,
    Subject,
    SubjectType,
)
from autoforge_security.permissions import Permissions
from autoforge_security.roles import Roles


def test_audit_logging_and_query(
    sample_human_engineer: Subject,
) -> None:
    audit = AuditEngine()

    req = AuthorizationRequest(
        subject=sample_human_engineer,
        action=Permissions.WORKSPACE_WRITE,
        resource="src/api.py",
        project_id="proj_100",
        task_id="task_200",
        correlation_id="corr_300",
    )
    dec = AuthorizationDecision(
        decision=DecisionType.ALLOW,
        is_allowed=True,
        reason="Granted under engineer role",
    )

    rec = audit.record_decision(req, dec)
    assert rec.actor_id == sample_human_engineer.subject_id
    assert rec.action == Permissions.WORKSPACE_WRITE
    assert rec.decision == DecisionType.ALLOW
    assert rec.outcome == "success"
    assert rec.project_id == "proj_100"
    assert rec.correlation_id == "corr_300"

    # Query
    results = audit.query_records(actor_id=sample_human_engineer.subject_id)
    assert len(results) == 1
    assert results[0].audit_id == rec.audit_id

    # Query filtered by non-existent project
    assert len(audit.query_records(project_id="other_proj")) == 0
