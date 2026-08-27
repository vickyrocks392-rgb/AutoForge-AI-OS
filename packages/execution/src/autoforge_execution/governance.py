"""
Execution Governance & HITL Integration — Phase 10.

Enforces:
- Proposal → Deterministic Validation → AI Evaluation → HITL Approval → Consequential Action.
- Routine execution steps (reading files, editing candidate files, running local tests)
  proceed autonomously.
- Consequential actions (tech stack finalization, git push, deployment, publication)
  must pause for human approval when configured.
"""

from __future__ import annotations

import uuid
from typing import Any

from autoforge_workflows.approval import ApprovalDecision, ApprovalGate, ApprovalOutcome, ApprovalStatus

from autoforge_execution.errors import GovernanceApprovalRequired
from autoforge_execution.models import ConsequentialActionType, GovernancePolicy


class ExecutionGovernance:
    """
    Evaluates actions against governance policies and manages HITL gating.
    """

    def __init__(self, policy: GovernancePolicy | None = None) -> None:
        self._policy = policy or GovernancePolicy()
        self._active_gates: dict[str, ApprovalGate] = {}

    @property
    def policy(self) -> GovernancePolicy:
        return self._policy

    def requires_approval(self, action_type: ConsequentialActionType) -> bool:
        """
        Determine if an action requires HITL approval under current policy.
        """
        return action_type in self._policy.consequential_actions_requiring_approval

    def request_approval_gate(
        self,
        action_type: ConsequentialActionType,
        task_id: str,
        *,
        workflow_id: uuid.UUID | None = None,
        description: str = "",
        required_approvers: int = 1,
    ) -> ApprovalGate:
        """
        Create and record an ApprovalGate for a consequential action.
        """
        gate_id = f"gov_gate_{action_type.value}_{task_id}_{uuid.uuid4().hex[:8]}"
        gate = ApprovalGate(
            gate_id=gate_id,
            task_id=task_id,
            workflow_id=workflow_id or uuid.uuid4(),
            description=description or f"Approval required for consequential action: {action_type.value}",
            required_approvers=required_approvers,
        )
        self._active_gates[gate_id] = gate
        return gate

    def check_and_gate_action(
        self,
        action_type: ConsequentialActionType,
        task_id: str,
        *,
        workflow_id: uuid.UUID | None = None,
        description: str = "",
        gate_id: str | None = None,
    ) -> bool:
        """
        Check if an action is allowed. If approval is required and not yet granted,
        raises GovernanceApprovalRequired or returns False.
        """
        if not self.requires_approval(action_type):
            return True

        if gate_id and gate_id in self._active_gates:
            gate = self._active_gates[gate_id]
            if gate.status == ApprovalStatus.APPROVED:
                return True
            if gate.status == ApprovalStatus.REJECTED:
                return False

        # Gate needs to be created or is currently pending
        new_gate = self.request_approval_gate(
            action_type=action_type,
            task_id=task_id,
            workflow_id=workflow_id,
            description=description,
        )
        raise GovernanceApprovalRequired(
            f"Action '{action_type.value}' requires HITL approval (gate ID: {new_gate.gate_id})",
            details={
                "gate_id": new_gate.gate_id,
                "action_type": action_type.value,
                "task_id": task_id,
            },
        )

    def submit_decision(
        self,
        gate_id: str,
        decision: ApprovalDecision,
    ) -> ApprovalStatus:
        """
        Submit a human decision to an active approval gate.
        """
        if gate_id not in self._active_gates:
            raise KeyError(f"Approval gate '{gate_id}' not found")
        return self._active_gates[gate_id].decide(decision)

    def get_gate(self, gate_id: str) -> ApprovalGate | None:
        return self._active_gates.get(gate_id)

    def list_pending_gates(self) -> list[ApprovalGate]:
        return [g for g in self._active_gates.values() if g.status == ApprovalStatus.PENDING_APPROVAL]
