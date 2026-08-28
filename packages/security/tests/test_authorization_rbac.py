"""
Unit tests for RBAC, permission inheritance, and authorization evaluation.
"""

from __future__ import annotations

import pytest

from autoforge_security.authorization import AuthorizationEngine
from autoforge_security.models import (
    AuthorizationRequest,
    DecisionType,
    Subject,
    SubjectType,
)
from autoforge_security.permissions import Permissions
from autoforge_security.roles import (
    CANONICAL_ROLES,
    Roles,
    resolve_role_permissions,
)


def test_canonical_roles_exist() -> None:
    assert Roles.ADMINISTRATOR in CANONICAL_ROLES
    assert Roles.OPERATOR in CANONICAL_ROLES
    assert Roles.ENGINEER in CANONICAL_ROLES
    assert Roles.REVIEWER in CANONICAL_ROLES
    assert Roles.RESEARCHER in CANONICAL_ROLES
    assert Roles.ANALYST in CANONICAL_ROLES
    assert Roles.MODERNIZATION_OPERATOR in CANONICAL_ROLES
    assert Roles.READ_ONLY_OBSERVER in CANONICAL_ROLES


def test_permission_inheritance() -> None:
    # Read-only observer has workspace.read
    observer_perms = resolve_role_permissions({Roles.READ_ONLY_OBSERVER})
    assert Permissions.WORKSPACE_READ in observer_perms
    assert Permissions.WORKSPACE_WRITE not in observer_perms

    # Engineer inherits read-only and adds write/execute
    engineer_perms = resolve_role_permissions({Roles.ENGINEER})
    assert Permissions.WORKSPACE_READ in engineer_perms
    assert Permissions.WORKSPACE_WRITE in engineer_perms
    assert Permissions.WORKSPACE_EXECUTE in engineer_perms
    assert Permissions.PROJECT_DELETE not in engineer_perms

    # Administrator has system.admin
    admin_perms = resolve_role_permissions({Roles.ADMINISTRATOR})
    assert Permissions.SYSTEM_ADMIN in admin_perms
    assert Permissions.PROJECT_DELETE in admin_perms


def test_authorization_engine_evaluation(
    authz_engine: AuthorizationEngine,
    sample_human_engineer: Subject,
    sample_human_admin: Subject,
) -> None:
    # Engineer writing to workspace -> ALLOW
    req = AuthorizationRequest(
        subject=sample_human_engineer,
        action=Permissions.WORKSPACE_WRITE,
        resource="workspace/src/app.py",
    )
    decision = authz_engine.evaluate(req)
    assert decision.is_allowed is True
    assert decision.decision == DecisionType.ALLOW

    # Engineer attempting project delete -> DENY
    req_del = AuthorizationRequest(
        subject=sample_human_engineer,
        action=Permissions.PROJECT_DELETE,
        resource="project_123",
    )
    decision_del = authz_engine.evaluate(req_del)
    assert decision_del.is_allowed is False
    assert decision_del.decision == DecisionType.DENY
    assert "lacks required permission" in decision_del.reason

    # Admin attempting project delete -> ALLOW
    req_admin = AuthorizationRequest(
        subject=sample_human_admin,
        action=Permissions.PROJECT_DELETE,
        resource="project_123",
    )
    decision_admin = authz_engine.evaluate(req_admin)
    assert decision_admin.is_allowed is True
    assert decision_admin.decision == DecisionType.ALLOW


def test_contextual_project_authorization(authz_engine: AuthorizationEngine) -> None:
    scoped_user = Subject(
        subject_id="user_scoped",
        display_name="Scoped User",
        subject_type=SubjectType.HUMAN,
        roles=frozenset({Roles.ENGINEER}),
        attributes={"allowed_projects": ["proj_alpha", "proj_beta"]},
    )

    # Allowed project
    req_ok = AuthorizationRequest(
        subject=scoped_user,
        action=Permissions.WORKSPACE_WRITE,
        resource="workspace",
        project_id="proj_alpha",
    )
    assert authz_engine.evaluate(req_ok).is_allowed is True

    # Disallowed project
    req_blocked = AuthorizationRequest(
        subject=scoped_user,
        action=Permissions.WORKSPACE_WRITE,
        resource="workspace",
        project_id="proj_gamma",
    )
    res = authz_engine.evaluate(req_blocked)
    assert res.is_allowed is False
    assert "not authorized for project" in res.reason
