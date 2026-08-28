"""
Unit & Audit tests for all 23 Autonomous Engineering Workers.
"""

from __future__ import annotations

import pytest

from autoforge_security.errors import InsufficientPrivilegesError
from autoforge_security.permissions import Permissions
from autoforge_security.worker_guard import (
    WORKER_SECURITY_PROFILES,
    WorkforceSecurityGuard,
)


def test_all_23_workers_have_certified_security_profiles() -> None:
    # 14 Greenfield Workers
    greenfield_types = {
        "orchestrator",
        "specification_analyst",
        "research_analyst",
        "system_architect",
        "tech_lead",
        "frontend_engineer",
        "backend_engineer",
        "database_engineer",
        "qa_test_engineer",
        "security_engineer",
        "devops_engineer",
        "code_reviewer",
        "documentation_specialist",
        "performance_engineer",
    }

    # 9 Legacy Modernization Workers
    legacy_types = {
        "legacy_intake_specialist",
        "legacy_codebase_archaeologist",
        "legacy_dependency_analyst",
        "legacy_architecture_reconstructor",
        "business_logic_extractor",
        "modernization_strategy_planner",
        "incremental_migration_engineer",
        "parity_regression_tester",
        "cutover_deployment_specialist",
    }

    assert len(WORKER_SECURITY_PROFILES) == 23
    assert set(WORKER_SECURITY_PROFILES.keys()) == (greenfield_types | legacy_types)


def test_legacy_archaeology_workers_are_strictly_read_only() -> None:
    archaeologist_profile = WORKER_SECURITY_PROFILES["legacy_codebase_archaeologist"]
    assert archaeologist_profile.is_read_only is True
    assert Permissions.WORKSPACE_WRITE not in archaeologist_profile.allowed_permissions
    assert Permissions.WORKSPACE_EXECUTE not in archaeologist_profile.allowed_permissions

    # Attempting write action should be rejected by WorkforceSecurityGuard
    with pytest.raises(InsufficientPrivilegesError):
        WorkforceSecurityGuard.validate_worker_action("legacy_codebase_archaeologist", Permissions.WORKSPACE_WRITE)

    with pytest.raises(InsufficientPrivilegesError):
        WorkforceSecurityGuard.validate_worker_action("legacy_intake_specialist", Permissions.WORKSPACE_WRITE)

    with pytest.raises(InsufficientPrivilegesError):
        WorkforceSecurityGuard.validate_worker_action("legacy_dependency_analyst", Permissions.WORKSPACE_WRITE)


def test_architect_propose_versus_finalize_boundary() -> None:
    architect = WORKER_SECURITY_PROFILES["system_architect"]
    assert Permissions.ARCHITECTURE_PROPOSE in architect.allowed_permissions
    assert Permissions.ARCHITECTURE_FINALIZE not in architect.allowed_permissions

    tech_lead = WORKER_SECURITY_PROFILES["tech_lead"]
    assert Permissions.TECHNOLOGY_PROPOSE in tech_lead.allowed_permissions
    assert Permissions.TECHNOLOGY_FINALIZE not in tech_lead.allowed_permissions

    legacy_reconstructor = WORKER_SECURITY_PROFILES["legacy_architecture_reconstructor"]
    assert Permissions.ARCHITECTURE_PROPOSE in legacy_reconstructor.allowed_permissions
    assert Permissions.ARCHITECTURE_FINALIZE not in legacy_reconstructor.allowed_permissions

    # Finalization attempts must be rejected
    with pytest.raises(InsufficientPrivilegesError):
        WorkforceSecurityGuard.validate_worker_action("system_architect", Permissions.ARCHITECTURE_FINALIZE)

    with pytest.raises(InsufficientPrivilegesError):
        WorkforceSecurityGuard.validate_worker_action("tech_lead", Permissions.TECHNOLOGY_FINALIZE)
