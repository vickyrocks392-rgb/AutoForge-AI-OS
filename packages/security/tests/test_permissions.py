"""
Unit tests for Permission definitions and taxonomy.
"""

from __future__ import annotations

from autoforge_security.permissions import ALL_PERMISSIONS, Permissions


def test_permission_taxonomy_integrity() -> None:
    # Verify all permission constants exist in catalog
    assert Permissions.PROJECT_READ in ALL_PERMISSIONS
    assert Permissions.PROJECT_WRITE in ALL_PERMISSIONS
    assert Permissions.PROJECT_DELETE in ALL_PERMISSIONS

    assert Permissions.WORKSPACE_READ in ALL_PERMISSIONS
    assert Permissions.WORKSPACE_WRITE in ALL_PERMISSIONS
    assert Permissions.WORKSPACE_EXECUTE in ALL_PERMISSIONS

    assert Permissions.ARCHITECTURE_PROPOSE in ALL_PERMISSIONS
    assert Permissions.ARCHITECTURE_FINALIZE in ALL_PERMISSIONS

    assert Permissions.TECHNOLOGY_PROPOSE in ALL_PERMISSIONS
    assert Permissions.TECHNOLOGY_FINALIZE in ALL_PERMISSIONS

    assert Permissions.DEPLOYMENT_EXECUTE in ALL_PERMISSIONS
    assert Permissions.MIGRATION_EXECUTE in ALL_PERMISSIONS
    assert Permissions.MIGRATION_CUTOVER in ALL_PERMISSIONS

    assert Permissions.CREDENTIAL_MANAGE in ALL_PERMISSIONS
    assert Permissions.SECRET_MANAGE in ALL_PERMISSIONS
    assert Permissions.GOVERNANCE_APPROVE in ALL_PERMISSIONS
    assert Permissions.SYSTEM_ADMIN in ALL_PERMISSIONS


def test_consequential_permission_flags() -> None:
    # Safe actions should not be marked consequential
    assert ALL_PERMISSIONS[Permissions.WORKSPACE_READ].is_consequential is False
    assert ALL_PERMISSIONS[Permissions.RESEARCH_PROPOSE].is_consequential is False
    assert ALL_PERMISSIONS[Permissions.ARCHITECTURE_PROPOSE].is_consequential is False

    # Consequential actions MUST be marked consequential
    assert ALL_PERMISSIONS[Permissions.ARCHITECTURE_FINALIZE].is_consequential is True
    assert ALL_PERMISSIONS[Permissions.TECHNOLOGY_FINALIZE].is_consequential is True
    assert ALL_PERMISSIONS[Permissions.DEPLOYMENT_EXECUTE].is_consequential is True
    assert ALL_PERMISSIONS[Permissions.MIGRATION_EXECUTE].is_consequential is True
    assert ALL_PERMISSIONS[Permissions.MIGRATION_CUTOVER].is_consequential is True
    assert ALL_PERMISSIONS[Permissions.GOVERNANCE_APPROVE].is_consequential is True
