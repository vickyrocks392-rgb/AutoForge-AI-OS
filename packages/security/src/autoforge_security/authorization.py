"""
Deterministic Authorization Engine & Policy Evaluator for AutoForge Security (Phase 15).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from autoforge_security.models import (
    AuthorizationDecision,
    AuthorizationRequest,
    DecisionType,
    Subject,
    SubjectType,
)
from autoforge_security.permissions import ACTION_TO_PERMISSION_MAP, ALL_PERMISSIONS, Permissions
from autoforge_security.roles import CANONICAL_ROLES, resolve_role_permissions


class AuthorizationEngine:
    """
    Deterministic authorization engine.
    Evaluates Subject + Action + Resource + Context against RBAC and security policies.
    """

    def __init__(
        self,
        policy_version: str = "1.0.0",
        custom_roles: dict[str, Any] | None = None,
    ) -> None:
        self._policy_version = policy_version
        self._custom_roles = custom_roles or {}

    def get_subject_permissions(self, subject: Subject) -> frozenset[str]:
        """Resolve all permissions granted to the subject across its roles."""
        return resolve_role_permissions(subject.roles, custom_roles=self._custom_roles)

    def has_permission(self, subject: Subject, permission: str) -> bool:
        """Check if subject holds a specific permission (or system.admin superuser)."""
        perms = self.get_subject_permissions(subject)
        return Permissions.SYSTEM_ADMIN in perms or permission in perms

    def evaluate(self, request: AuthorizationRequest) -> AuthorizationDecision:
        """
        Deterministically evaluate an authorization request.
        Produces explainable decision with explicit reason and required permissions.
        """
        subject = request.subject
        action = request.action
        resource = request.resource

        # 1. Inactive account check
        if not subject.is_active:
            return AuthorizationDecision(
                decision=DecisionType.DENY,
                is_allowed=False,
                reason=f"Subject '{subject.subject_id}' is inactive or disabled.",
                policy_version=self._policy_version,
            )

        # 2. Anonymous subject check for non-public actions
        if subject.subject_type == SubjectType.ANONYMOUS and action not in {
            Permissions.PROJECT_READ,
            Permissions.ARTIFACT_READ,
        }:
            return AuthorizationDecision(
                decision=DecisionType.DENY,
                is_allowed=False,
                reason="Anonymous access is restricted to read-only public artifacts and projects.",
                policy_version=self._policy_version,
            )

        # 3. Superuser check
        perms = self.get_subject_permissions(subject)
        if Permissions.SYSTEM_ADMIN in perms:
            return AuthorizationDecision(
                decision=DecisionType.ALLOW,
                is_allowed=True,
                reason="Granted via administrator superuser privilege (system.admin).",
                required_permissions=frozenset({action}),
                policy_version=self._policy_version,
            )

        # 4. Direct permission check
        mapped_perm = ACTION_TO_PERMISSION_MAP.get(action, action)
        if mapped_perm not in perms and action not in perms:
            return AuthorizationDecision(
                decision=DecisionType.DENY,
                is_allowed=False,
                reason=f"Subject '{subject.subject_id}' with roles {list(subject.roles)} lacks required permission '{mapped_perm}'.",
                required_permissions=frozenset({mapped_perm}),
                policy_version=self._policy_version,
            )

        # 5. Worker-specific constraints
        if subject.subject_type == SubjectType.WORKER:
            worker_type = subject.attributes.get("worker_type", "")

            # Consequential actions can NEVER be directly authorized by a worker alone
            perm_def = ALL_PERMISSIONS.get(mapped_perm) or ALL_PERMISSIONS.get(action)
            if perm_def and perm_def.is_consequential:
                return AuthorizationDecision(
                    decision=DecisionType.REQUIRE_HITL,
                    is_allowed=False,
                    reason=f"Action '{action}' is consequential and cannot be executed autonomously by worker '{subject.subject_id}'. Human approval required.",
                    required_permissions=frozenset({mapped_perm}),
                    policy_version=self._policy_version,
                    details={"worker_type": worker_type, "consequential": True},
                )

            # Archaeology / Discovery workers must remain strictly read-only
            if "archaeology" in worker_type or "discovery" in worker_type:
                if "write" in action or "delete" in action or "execute" in action:
                    if action != Permissions.RESEARCH_EXECUTE:
                        return AuthorizationDecision(
                            decision=DecisionType.DENY,
                            is_allowed=False,
                            reason=f"Legacy archaeology worker '{worker_type}' is strictly read-only and cannot perform '{action}'.",
                            required_permissions=frozenset({action}),
                            policy_version=self._policy_version,
                        )

        # 6. Contextual validation (e.g. project scoping)
        if request.project_id and "allowed_projects" in subject.attributes:
            allowed_projects = set(subject.attributes.get("allowed_projects", []))
            if request.project_id not in allowed_projects:
                return AuthorizationDecision(
                    decision=DecisionType.DENY,
                    is_allowed=False,
                    reason=f"Subject '{subject.subject_id}' is not authorized for project '{request.project_id}'.",
                    required_permissions=frozenset({action}),
                    policy_version=self._policy_version,
                )

        return AuthorizationDecision(
            decision=DecisionType.ALLOW,
            is_allowed=True,
            reason=f"Authorized under role permissions {list(subject.roles)}.",
            required_permissions=frozenset({action}),
            policy_version=self._policy_version,
        )
