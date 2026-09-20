"""Human-in-the-Loop Approval & Intervention Subsystem (18-COMMERCIAL-C)."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from autoforge_power_engines.automation.spec import ActionRiskLevel, HumanApprovalSpec

logger = logging.getLogger("autoforge.power_engines.automation.approval")


class ApprovalStatus(str, Enum):
    """Status of an approval request."""
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


class ApprovalDecision(BaseModel):
    """Record of an approval decision made by a human reviewer."""
    request_id: str
    decision: ApprovalStatus  # APPROVED or REJECTED
    reviewer_id: str
    comment: Optional[str] = None
    decided_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class ApprovalRequest(BaseModel):
    """Active approval request awaiting human sign-off."""
    request_id: str = Field(default_factory=lambda: f"apr-{uuid.uuid4().hex[:8]}")
    workflow_id: str
    execution_id: str
    step_id: str
    reason: str
    prompt: str
    risk_level: ActionRiskLevel
    approver_roles: List[str]
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    status: ApprovalStatus = ApprovalStatus.PENDING
    context_summary: Dict[str, Any] = Field(default_factory=dict)
    decision: Optional[ApprovalDecision] = None


class ApprovalManager:
    """Manages pending and resolved human approvals."""

    def __init__(self):
        self._requests: Dict[str, ApprovalRequest] = {}

    def create_request(
        self,
        workflow_id: str,
        execution_id: str,
        step_id: str,
        spec: HumanApprovalSpec,
        context_summary: Optional[Dict[str, Any]] = None,
    ) -> ApprovalRequest:
        req = ApprovalRequest(
            workflow_id=workflow_id,
            execution_id=execution_id,
            step_id=step_id,
            reason=spec.reason,
            prompt=spec.approval_prompt,
            risk_level=spec.risk_level,
            approver_roles=spec.approver_roles,
            context_summary=context_summary or {},
        )
        self._requests[req.request_id] = req
        logger.info(f"Created ApprovalRequest '{req.request_id}' for step '{step_id}' in execution '{execution_id}'.")
        return req

    def get_request(self, request_id: str) -> Optional[ApprovalRequest]:
        return self._requests.get(request_id)

    def list_pending(self, execution_id: Optional[str] = None) -> List[ApprovalRequest]:
        return [
            r for r in self._requests.values()
            if r.status == ApprovalStatus.PENDING and (execution_id is None or r.execution_id == execution_id)
        ]

    def record_decision(
        self,
        request_id: str,
        approved: bool,
        reviewer_id: str,
        comment: Optional[str] = None,
    ) -> ApprovalRequest:
        req = self._requests.get(request_id)
        if not req:
            raise KeyError(f"Approval request '{request_id}' not found.")
        if req.status != ApprovalStatus.PENDING:
            raise ValueError(f"Approval request '{request_id}' is already {req.status.value}.")

        decision_status = ApprovalStatus.APPROVED if approved else ApprovalStatus.REJECTED
        decision = ApprovalDecision(
            request_id=request_id,
            decision=decision_status,
            reviewer_id=reviewer_id,
            comment=comment,
        )
        req.decision = decision
        req.status = decision_status

        logger.info(f"ApprovalRequest '{request_id}' resolved: {decision_status.value} by {reviewer_id}.")
        return req
