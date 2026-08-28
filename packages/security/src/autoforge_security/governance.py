"""
Governance Policy Engine for AutoForge Security (Phase 15).
"""

from __future__ import annotations

import uuid
from typing import Any

from autoforge_security.errors import (
    ConsequentialActionBlockedError,
    SelfApprovalForbiddenError,
)
from autoforge_security.models import (
    AuthorizationDecision,
    AuthorizationRequest,
    ConsequentialAction,
    DecisionType,
    GovernancePolicy,
    Subject,
    SubjectType,
)
from autoforge_security.permissions import Permissions


class GovernancePolicyEngine:
    """
    Deterministic governance policy engine.
    Ensures high-impact / consequential actions are gated and that AI/workers
    never bypass authorization or approve their own actions.
    """

    def __init__(self, policy: GovernancePolicy | None = None) -> None:
        self._policy = policy or GovernancePolicy()

    @property
    def policy(self) -> GovernancePolicy:
        return self._policy

    def is_action_gated(self, action: ConsequentialAction | str) -> bool:
        """Check if an action is gated by policy."""
        try:
            ca = ConsequentialAction(action)
            return ca in self._policy.gated_actions
        except ValueError:
            return False

    def evaluate_consequential_action(
        self,
        action: ConsequentialAction,
        subject: Subject,
        *,
        has_approved_gate: bool = False,
        gate_id: str | None = None,
        context: dict[str, Any] | None = None,
    ) -> AuthorizationDecision:
        """
        Evaluate a consequential action against governance policies.
        """
        ctx = context or {}

        # AI and Worker subjects can NEVER self-approve or bypass gates
        if subject.subject_type == SubjectType.WORKER and not has_approved_gate:
            return AuthorizationDecision(
                decision=DecisionType.REQUIRE_HITL,
                is_allowed=False,
                reason=f"Action '{action.value}' is a consequential action and requires human approval. Worker '{subject.subject_id}' cannot execute autonomously.",
                required_permissions=frozenset({Permissions.GOVERNANCE_APPROVE}),
                policy_version=self._policy.policy_version,
                gate_id=gate_id,
                details={"action": action.value, "subject_id": subject.subject_id},
            )

        # If the action is gated and no approved gate exists
        if self.is_action_gated(action) and not has_approved_gate:
            return AuthorizationDecision(
                decision=DecisionType.REQUIRE_HITL,
                is_allowed=False,
                reason=f"Action '{action.value}' is gated by governance policy '{self._policy.policy_id}'. Human approval required.",
                required_permissions=frozenset({Permissions.GOVERNANCE_APPROVE}),
                policy_version=self._policy.policy_version,
                gate_id=gate_id,
                details={"action": action.value},
            )

        # If approval gate is verified or action is safe
        return AuthorizationDecision(
            decision=DecisionType.ALLOW,
            is_allowed=True,
            reason=f"Consequential action '{action.value}' permitted (approval gate verified={has_approved_gate}).",
            policy_version=self._policy.policy_version,
            gate_id=gate_id,
            details={"action": action.value, "has_approved_gate": has_approved_gate},
        )

    def validate_human_approver(self, approver: Subject, gate_requestor_id: str) -> None:
        """
        Verify that an approver is an authorized human and not the worker/requestor attempting self-approval.
        """
        if approver.subject_type != SubjectType.HUMAN:
            raise SelfApprovalForbiddenError(
                f"Subject '{approver.subject_id}' of type '{approver.subject_type.value}' cannot approve HITL gates. Approvals must be signed by authorized human subjects."
            )

        if approver.subject_id == gate_requestor_id:
            # If the requestor was an individual, check self-approval rules
            if not approver.attributes.get("is_root", False):
                raise SelfApprovalForbiddenError(
                    f"Subject '{approver.subject_id}' cannot approve their own requested consequential action."
                )
