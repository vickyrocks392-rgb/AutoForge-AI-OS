"""
Canonical RBAC Roles & Permission Mappings for AutoForge Security (Phase 15).
"""

from __future__ import annotations
from autoforge_security.models import RoleDefinition
from autoforge_security.permissions import Permissions


class Roles:
    """Canonical role identifiers."""
    ADMINISTRATOR = "administrator"
    OPERATOR = "operator"
    ENGINEER = "engineer"
    REVIEWER = "reviewer"
    RESEARCHER = "researcher"
    ANALYST = "analyst"
    MODERNIZATION_OPERATOR = "modernization_operator"
    READ_ONLY_OBSERVER = "read_only_observer"


# ── Canonical Role Definitions ───────────────────────────────────────────

READ_ONLY_OBSERVER_PERMISSIONS = frozenset({
    Permissions.PROJECT_READ,
    Permissions.WORKSPACE_READ,
    Permissions.ARTIFACT_READ,
    Permissions.AUDIT_READ,
})

RESEARCHER_PERMISSIONS = READ_ONLY_OBSERVER_PERMISSIONS | frozenset({
    Permissions.RESEARCH_EXECUTE,
    Permissions.RESEARCH_PROPOSE,
})

ANALYST_PERMISSIONS = READ_ONLY_OBSERVER_PERMISSIONS | frozenset({
    Permissions.RESEARCH_EXECUTE,
})

REVIEWER_PERMISSIONS = READ_ONLY_OBSERVER_PERMISSIONS | frozenset({
    Permissions.RESEARCH_PROPOSE,
    Permissions.ARCHITECTURE_PROPOSE,
    Permissions.TECHNOLOGY_PROPOSE,
    Permissions.GOVERNANCE_APPROVE,  # Reviewer can approve HITL gates
})

ENGINEER_PERMISSIONS = READ_ONLY_OBSERVER_PERMISSIONS | frozenset({
    Permissions.PROJECT_WRITE,
    Permissions.WORKSPACE_WRITE,
    Permissions.WORKSPACE_EXECUTE,
    Permissions.RESEARCH_EXECUTE,
    Permissions.RESEARCH_PROPOSE,
    Permissions.ARCHITECTURE_PROPOSE,
    Permissions.TECHNOLOGY_PROPOSE,
    Permissions.WORKFLOW_CREATE,
    Permissions.WORKFLOW_EXECUTE,
    Permissions.WORKFLOW_CANCEL,
    Permissions.EXECUTION_EXECUTE,
    Permissions.EXECUTION_CANCEL,
    Permissions.ARTIFACT_WRITE,
    Permissions.MIGRATION_PLAN,
    Permissions.CREDENTIAL_READ,
    Permissions.CREDENTIAL_USE,
    Permissions.SECRET_READ,
})

MODERNIZATION_OPERATOR_PERMISSIONS = ENGINEER_PERMISSIONS | frozenset({
    Permissions.MIGRATION_EXECUTE,  # Requires HITL gate at runtime
    Permissions.MIGRATION_CUTOVER,  # Requires HITL gate at runtime
})

OPERATOR_PERMISSIONS = MODERNIZATION_OPERATOR_PERMISSIONS | frozenset({
    Permissions.DEPLOYMENT_EXECUTE,   # Requires HITL gate at runtime
    Permissions.DEPLOYMENT_ROLLBACK,
    Permissions.ARTIFACT_PUBLISH,     # Requires HITL gate at runtime
    Permissions.ARTIFACT_ROLLBACK,
    Permissions.CREDENTIAL_MANAGE,
    Permissions.GOVERNANCE_APPROVE,
})

ADMINISTRATOR_PERMISSIONS = OPERATOR_PERMISSIONS | frozenset({
    Permissions.PROJECT_DELETE,
    Permissions.ARCHITECTURE_FINALIZE,
    Permissions.TECHNOLOGY_FINALIZE,
    Permissions.SECRET_MANAGE,
    Permissions.GOVERNANCE_CONFIGURE,
    Permissions.SYSTEM_ADMIN,
})


CANONICAL_ROLES: dict[str, RoleDefinition] = {
    Roles.READ_ONLY_OBSERVER: RoleDefinition(
        role_id=Roles.READ_ONLY_OBSERVER,
        display_name="Read-Only Observer",
        description="Can inspect projects, workspaces, artifacts, and audit trails without modifying anything.",
        permissions=READ_ONLY_OBSERVER_PERMISSIONS,
    ),
    Roles.RESEARCHER: RoleDefinition(
        role_id=Roles.RESEARCHER,
        display_name="Researcher",
        description="Can perform research queries, analyze repositories, and propose findings.",
        permissions=RESEARCHER_PERMISSIONS,
        inherits_from=frozenset({Roles.READ_ONLY_OBSERVER}),
    ),
    Roles.ANALYST: RoleDefinition(
        role_id=Roles.ANALYST,
        display_name="Analyst",
        description="Can inspect system telemetry, audit trails, and execution metrics.",
        permissions=ANALYST_PERMISSIONS,
        inherits_from=frozenset({Roles.READ_ONLY_OBSERVER}),
    ),
    Roles.REVIEWER: RoleDefinition(
        role_id=Roles.REVIEWER,
        display_name="Reviewer",
        description="Can review proposals and make HITL approval / rejection decisions.",
        permissions=REVIEWER_PERMISSIONS,
        inherits_from=frozenset({Roles.READ_ONLY_OBSERVER}),
    ),
    Roles.ENGINEER: RoleDefinition(
        role_id=Roles.ENGINEER,
        display_name="Engineer",
        description="Can modify workspaces, trigger execution loops, propose architectures and create workflows.",
        permissions=ENGINEER_PERMISSIONS,
        inherits_from=frozenset({Roles.READ_ONLY_OBSERVER}),
    ),
    Roles.MODERNIZATION_OPERATOR: RoleDefinition(
        role_id=Roles.MODERNIZATION_OPERATOR,
        display_name="Modernization Operator",
        description="Can intake legacy systems, run modernization pipelines, and request migration cutovers.",
        permissions=MODERNIZATION_OPERATOR_PERMISSIONS,
        inherits_from=frozenset({Roles.ENGINEER}),
    ),
    Roles.OPERATOR: RoleDefinition(
        role_id=Roles.OPERATOR,
        display_name="Operator",
        description="Can execute workflows, deployments, artifact publishing, and approve operations.",
        permissions=OPERATOR_PERMISSIONS,
        inherits_from=frozenset({Roles.MODERNIZATION_OPERATOR}),
    ),
    Roles.ADMINISTRATOR: RoleDefinition(
        role_id=Roles.ADMINISTRATOR,
        display_name="Administrator",
        description="Full superuser platform permissions including governance configuration.",
        permissions=ADMINISTRATOR_PERMISSIONS,
        inherits_from=frozenset({Roles.OPERATOR}),
    ),
}


def resolve_role_permissions(roles: set[str] | frozenset[str], custom_roles: dict[str, RoleDefinition] | None = None) -> frozenset[str]:
    """
    Resolve full set of permissions for given roles, including inheritance.
    """
    all_roles = dict(CANONICAL_ROLES)
    if custom_roles:
        all_roles.update(custom_roles)

    resolved: set[str] = set()
    visited: set[str] = set()

    def _collect(role_id: str) -> None:
        if role_id in visited or role_id not in all_roles:
            return
        visited.add(role_id)
        role = all_roles[role_id]
        resolved.update(role.permissions)
        for parent in role.inherits_from:
            _collect(parent)

    for r in roles:
        _collect(r)

    return frozenset(resolved)
