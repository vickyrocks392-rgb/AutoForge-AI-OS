"""
Centralized Human-In-The-Loop (HITL) Approval Gatekeeper for AutoForge Security (Phase 15).
"""

from __future__ import annotations

import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from autoforge_security.errors import (
    ApprovalGateExpiredError,
    ApprovalGateNotFoundError,
    GovernanceError,
    InsufficientPrivilegesError,
    SelfApprovalForbiddenError,
)
from autoforge_security.governance import GovernancePolicyEngine
from autoforge_security.models import (
    ApprovalGateStatus,
    ConsequentialAction,
    HITLApprovalGate,
    HITLDecisionRecord,
    Subject,
    SubjectType,
)
from autoforge_security.permissions import Permissions


class HITLManager:
    """
    Centralized gatekeeper for consequential action approvals.
    Maintains active and historical approval gates with cryptographic resume tokens.
    """

    def __init__(
        self,
        governance_engine: GovernancePolicyEngine | None = None,
        default_gate_ttl_seconds: int = 86400,
    ) -> None:
        self._governance = governance_engine or GovernancePolicyEngine()
        self._default_ttl = default_gate_ttl_seconds
        self._gates: dict[str, HITLApprovalGate] = {}

    def create_gate(
        self,
        action: ConsequentialAction | str,
        requested_by: Subject,
        description: str,
        *,
        requested_by_worker_id: str | None = None,
        project_id: str | None = None,
        workflow_id: str | None = None,
        task_id: str | None = None,
        execution_id: str | None = None,
        required_approvers: int = 1,
        ttl_seconds: int | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> HITLApprovalGate:
        """Create and register a new pending approval gate."""
        act = ConsequentialAction(action)
        now = datetime.now(timezone.utc)
        ttl = ttl_seconds or self._default_ttl
        expires_at = now + timedelta(seconds=ttl)

        gate_id = f"hitl_gate_{act.value}_{uuid.uuid4().hex[:8]}"
        gate = HITLApprovalGate(
            gate_id=gate_id,
            action=act,
            description=description,
            requested_by_subject_id=requested_by.subject_id,
            requested_by_worker_id=requested_by_worker_id,
            project_id=project_id,
            workflow_id=workflow_id,
            task_id=task_id,
            execution_id=execution_id,
            status=ApprovalGateStatus.PENDING,
            required_approvers=required_approvers,
            created_at=now,
            expires_at=expires_at,
            metadata=metadata or {},
        )
        self._gates[gate_id] = gate
        return gate

    def get_gate(self, gate_id: str) -> HITLApprovalGate:
        """Retrieve approval gate by ID, updating expiry status if needed."""
        gate = self._gates.get(gate_id)
        if not gate:
            raise ApprovalGateNotFoundError(f"Approval gate '{gate_id}' not found.")

        now = datetime.now(timezone.utc)
        if gate.status == ApprovalGateStatus.PENDING and gate.expires_at and now >= gate.expires_at:
            gate.status = ApprovalGateStatus.EXPIRED

        return gate

    def submit_decision(
        self,
        gate_id: str,
        approver: Subject,
        status: ApprovalGateStatus,
        reason: str = "",
    ) -> HITLApprovalGate:
        """
        Record an approval or rejection decision from an authorized human subject.
        """
        gate = self.get_gate(gate_id)

        # 1. Status checks
        if gate.status == ApprovalGateStatus.EXPIRED:
            raise ApprovalGateExpiredError(f"Approval gate '{gate_id}' has expired.")
        if gate.status != ApprovalGateStatus.PENDING:
            raise GovernanceError(f"Approval gate '{gate_id}' is already resolved with status '{gate.status.value}'.")

        # 2. Actor validation
        if approver.subject_type != SubjectType.HUMAN:
            raise SelfApprovalForbiddenError(
                f"Subject '{approver.subject_id}' of type '{approver.subject_type.value}' cannot decide HITL gates. AI models and workers are prohibited from approving actions."
            )

        self._governance.validate_human_approver(approver, gate.requested_by_subject_id)

        # 3. Create decision record
        signature = f"sig_{secrets.token_hex(16)}"
        rec = HITLDecisionRecord(
            approver_id=approver.subject_id,
            approver_name=approver.display_name,
            status=status,
            reason=reason,
            signature=signature,
        )
        gate.decisions.append(rec)

        if status == ApprovalGateStatus.REJECTED:
            gate.status = ApprovalGateStatus.REJECTED
        elif status == ApprovalGateStatus.APPROVED:
            # Check if required approvals threshold is met
            approved_count = sum(1 for d in gate.decisions if d.status == ApprovalGateStatus.APPROVED)
            if approved_count >= gate.required_approvers:
                gate.status = ApprovalGateStatus.APPROVED
                gate.resume_token = f"rst_{secrets.token_urlsafe(32)}"

        return gate

    def verify_resume_token(self, gate_id: str, resume_token: str) -> bool:
        """Verify that a resume token matches an approved gate."""
        gate = self.get_gate(gate_id)
        if gate.status != ApprovalGateStatus.APPROVED:
            return False
        if not gate.resume_token or not resume_token:
            return False
        return secrets.compare_digest(gate.resume_token, resume_token)

    def list_pending_gates(self, project_id: str | None = None) -> list[HITLApprovalGate]:
        """List all pending approval gates, filtering out expired ones."""
        pending: list[HITLApprovalGate] = []
        for gate_id in list(self._gates.keys()):
            gate = self.get_gate(gate_id)
            if gate.status == ApprovalGateStatus.PENDING:
                if project_id is None or gate.project_id == project_id:
                    pending.append(gate)
        return pending

    def list_all_gates(self) -> list[HITLApprovalGate]:
        """List all approval gates (pending and resolved)."""
        return [self.get_gate(gid) for gid in self._gates]
