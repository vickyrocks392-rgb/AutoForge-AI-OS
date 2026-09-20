"""Human-in-the-Loop Approval Manager (18-COMMERCIAL-D).

Coordinates governance and human sign-off gates (WAITING_FOR_HUMAN_APPROVAL).
Strictly prevents AI self-approval and model mutations of approval state.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from autoforge_power_engines.migration.risk import MigrationRiskAssessment, MigrationRiskLevel


class ApprovalStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    BYPASSED = "bypassed"


class ApprovalRequest(BaseModel):
    """An explicit human approval request for a high-risk migration unit or plan."""
    request_id: str = Field(default_factory=lambda: f"appr-{uuid.uuid4().hex[:8]}")
    migration_id: str
    unit_id: Optional[str] = None
    target_path: str
    risk_assessment: MigrationRiskAssessment
    reason: str
    status: ApprovalStatus = ApprovalStatus.PENDING
    requested_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    resolved_at: Optional[datetime] = None
    decision_by: Optional[str] = None
    decision_notes: Optional[str] = None


class ApprovalManager:
    """
    Manages approval requests and enforces strict human authorization gates.
    """

    def __init__(self, migration_id: str):
        self.migration_id = migration_id
        self._requests: Dict[str, ApprovalRequest] = {}

    def create_request(
        self,
        target_path: str,
        risk_assessment: MigrationRiskAssessment,
        reason: str,
        unit_id: Optional[str] = None,
    ) -> ApprovalRequest:
        req = ApprovalRequest(
            migration_id=self.migration_id,
            unit_id=unit_id,
            target_path=target_path,
            risk_assessment=risk_assessment,
            reason=reason,
        )
        self._requests[req.request_id] = req
        return req

    def get_request(self, request_id: str) -> Optional[ApprovalRequest]:
        return self._requests.get(request_id)

    def list_pending_requests(self) -> List[ApprovalRequest]:
        return [r for r in self._requests.values() if r.status == ApprovalStatus.PENDING]

    def record_decision(
        self,
        request_id: str,
        approved: bool,
        decision_by: str,
        notes: str = "",
    ) -> ApprovalRequest:
        """
        Records human decision.
        Guards: decision_by must NOT be an AI agent, model, or system identifier.
        """
        req = self._requests.get(request_id)
        if not req:
            raise KeyError(f"Approval request '{request_id}' not found.")

        # Guard against AI self-approval
        forbidden_actors = {"ai", "model", "llm", "agent", "system", "autoforge_agent", "ollama"}
        if decision_by.lower().strip() in forbidden_actors or "model" in decision_by.lower() or "agent" in decision_by.lower():
            raise PermissionError(
                f"Unauthorized decision actor '{decision_by}'. AI models and automated agents are strictly forbidden from self-approving."
            )

        req.status = ApprovalStatus.APPROVED if approved else ApprovalStatus.REJECTED
        req.decision_by = decision_by
        req.decision_notes = notes
        req.resolved_at = datetime.now(timezone.utc)
        return req
