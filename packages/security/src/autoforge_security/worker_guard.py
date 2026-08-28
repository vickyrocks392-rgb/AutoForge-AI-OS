"""
Workforce Security Guardrails & Audit Rules for all 23 Workers (Phase 15).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from autoforge_security.errors import InsufficientPrivilegesError, SandboxViolationError
from autoforge_security.models import ConsequentialAction, Subject, SubjectType
from autoforge_security.permissions import Permissions
from autoforge_security.roles import Roles


@dataclass(frozen=True)
class WorkerSecurityProfile:
    """Authoritative security boundaries for an engineering worker."""
    worker_type: str
    is_legacy_worker: bool
    is_read_only: bool
    allowed_permissions: frozenset[str]
    consequential_actions_allowed: frozenset[ConsequentialAction]
    description: str


# ── Authoritative Security Profiles for All 23 Workers ───────────────────

WORKER_SECURITY_PROFILES: dict[str, WorkerSecurityProfile] = {
    # ── 14 Greenfield Workers ──
    "orchestrator": WorkerSecurityProfile(
        worker_type="orchestrator",
        is_legacy_worker=False,
        is_read_only=False,
        allowed_permissions=frozenset({
            Permissions.PROJECT_READ,
            Permissions.PROJECT_WRITE,
            Permissions.WORKSPACE_READ,
            Permissions.WORKFLOW_CREATE,
            Permissions.WORKFLOW_EXECUTE,
            Permissions.WORKFLOW_CANCEL,
            Permissions.EXECUTION_EXECUTE,
            Permissions.ARTIFACT_READ,
            Permissions.ARTIFACT_WRITE,
        }),
        consequential_actions_allowed=frozenset(),
        description="Coordinates workflow execution without direct system mutation.",
    ),
    "specification_analyst": WorkerSecurityProfile(
        worker_type="specification_analyst",
        is_legacy_worker=False,
        is_read_only=False,
        allowed_permissions=frozenset({
            Permissions.PROJECT_READ,
            Permissions.WORKSPACE_READ,
            Permissions.RESEARCH_PROPOSE,
            Permissions.ARTIFACT_READ,
            Permissions.ARTIFACT_WRITE,
        }),
        consequential_actions_allowed=frozenset(),
        description="Analyzes and drafts technical specifications.",
    ),
    "research_analyst": WorkerSecurityProfile(
        worker_type="research_analyst",
        is_legacy_worker=False,
        is_read_only=True,
        allowed_permissions=frozenset({
            Permissions.PROJECT_READ,
            Permissions.WORKSPACE_READ,
            Permissions.RESEARCH_EXECUTE,
            Permissions.RESEARCH_PROPOSE,
            Permissions.ARTIFACT_READ,
            Permissions.ARTIFACT_WRITE,
        }),
        consequential_actions_allowed=frozenset(),
        description="Performs read-only research and drafts findings.",
    ),
    "system_architect": WorkerSecurityProfile(
        worker_type="system_architect",
        is_legacy_worker=False,
        is_read_only=False,
        allowed_permissions=frozenset({
            Permissions.PROJECT_READ,
            Permissions.WORKSPACE_READ,
            Permissions.ARCHITECTURE_PROPOSE,  # Propose only, cannot finalize
            Permissions.ARTIFACT_READ,
            Permissions.ARTIFACT_WRITE,
        }),
        consequential_actions_allowed=frozenset(),
        description="Proposes system architectures; cannot finalize without human approval.",
    ),
    "tech_lead": WorkerSecurityProfile(
        worker_type="tech_lead",
        is_legacy_worker=False,
        is_read_only=False,
        allowed_permissions=frozenset({
            Permissions.PROJECT_READ,
            Permissions.WORKSPACE_READ,
            Permissions.WORKSPACE_WRITE,
            Permissions.TECHNOLOGY_PROPOSE,  # Propose only
            Permissions.ARCHITECTURE_PROPOSE,
            Permissions.ARTIFACT_READ,
            Permissions.ARTIFACT_WRITE,
        }),
        consequential_actions_allowed=frozenset(),
        description="Proposes technology stacks; cannot finalize without human approval.",
    ),
    "frontend_engineer": WorkerSecurityProfile(
        worker_type="frontend_engineer",
        is_legacy_worker=False,
        is_read_only=False,
        allowed_permissions=frozenset({
            Permissions.PROJECT_READ,
            Permissions.WORKSPACE_READ,
            Permissions.WORKSPACE_WRITE,
            Permissions.WORKSPACE_EXECUTE,
            Permissions.EXECUTION_EXECUTE,
            Permissions.ARTIFACT_READ,
            Permissions.ARTIFACT_WRITE,
        }),
        consequential_actions_allowed=frozenset(),
        description="Modifies frontend code and executes local tests.",
    ),
    "backend_engineer": WorkerSecurityProfile(
        worker_type="backend_engineer",
        is_legacy_worker=False,
        is_read_only=False,
        allowed_permissions=frozenset({
            Permissions.PROJECT_READ,
            Permissions.WORKSPACE_READ,
            Permissions.WORKSPACE_WRITE,
            Permissions.WORKSPACE_EXECUTE,
            Permissions.EXECUTION_EXECUTE,
            Permissions.ARTIFACT_READ,
            Permissions.ARTIFACT_WRITE,
        }),
        consequential_actions_allowed=frozenset(),
        description="Modifies backend code and executes local tests.",
    ),
    "database_engineer": WorkerSecurityProfile(
        worker_type="database_engineer",
        is_legacy_worker=False,
        is_read_only=False,
        allowed_permissions=frozenset({
            Permissions.PROJECT_READ,
            Permissions.WORKSPACE_READ,
            Permissions.WORKSPACE_WRITE,
            Permissions.WORKSPACE_EXECUTE,
            Permissions.EXECUTION_EXECUTE,
            Permissions.ARTIFACT_READ,
            Permissions.ARTIFACT_WRITE,
        }),
        consequential_actions_allowed=frozenset(),
        description="Designs schema migrations and queries.",
    ),
    "qa_test_engineer": WorkerSecurityProfile(
        worker_type="qa_test_engineer",
        is_legacy_worker=False,
        is_read_only=False,
        allowed_permissions=frozenset({
            Permissions.PROJECT_READ,
            Permissions.WORKSPACE_READ,
            Permissions.WORKSPACE_WRITE,
            Permissions.WORKSPACE_EXECUTE,
            Permissions.EXECUTION_EXECUTE,
            Permissions.ARTIFACT_READ,
            Permissions.ARTIFACT_WRITE,
        }),
        consequential_actions_allowed=frozenset(),
        description="Executes test suites and writes regression tests.",
    ),
    "security_engineer": WorkerSecurityProfile(
        worker_type="security_engineer",
        is_legacy_worker=False,
        is_read_only=True,
        allowed_permissions=frozenset({
            Permissions.PROJECT_READ,
            Permissions.WORKSPACE_READ,
            Permissions.RESEARCH_EXECUTE,
            Permissions.AUDIT_READ,
            Permissions.ARTIFACT_READ,
            Permissions.ARTIFACT_WRITE,
        }),
        consequential_actions_allowed=frozenset(),
        description="Inspects vulnerabilities, audit logs, and reports findings.",
    ),
    "devops_engineer": WorkerSecurityProfile(
        worker_type="devops_engineer",
        is_legacy_worker=False,
        is_read_only=False,
        allowed_permissions=frozenset({
            Permissions.PROJECT_READ,
            Permissions.WORKSPACE_READ,
            Permissions.WORKSPACE_WRITE,
            Permissions.WORKSPACE_EXECUTE,
            Permissions.ARTIFACT_READ,
            Permissions.ARTIFACT_WRITE,
        }),
        consequential_actions_allowed=frozenset(),
        description="Manages build configurations and container manifests.",
    ),
    "code_reviewer": WorkerSecurityProfile(
        worker_type="code_reviewer",
        is_legacy_worker=False,
        is_read_only=True,
        allowed_permissions=frozenset({
            Permissions.PROJECT_READ,
            Permissions.WORKSPACE_READ,
            Permissions.ARTIFACT_READ,
            Permissions.ARTIFACT_WRITE,
        }),
        consequential_actions_allowed=frozenset(),
        description="Reviews diffs and evaluates candidate artifacts.",
    ),
    "documentation_specialist": WorkerSecurityProfile(
        worker_type="documentation_specialist",
        is_legacy_worker=False,
        is_read_only=False,
        allowed_permissions=frozenset({
            Permissions.PROJECT_READ,
            Permissions.WORKSPACE_READ,
            Permissions.WORKSPACE_WRITE,
            Permissions.ARTIFACT_READ,
            Permissions.ARTIFACT_WRITE,
        }),
        consequential_actions_allowed=frozenset(),
        description="Writes markdown documentation and guides.",
    ),
    "performance_engineer": WorkerSecurityProfile(
        worker_type="performance_engineer",
        is_legacy_worker=False,
        is_read_only=False,
        allowed_permissions=frozenset({
            Permissions.PROJECT_READ,
            Permissions.WORKSPACE_READ,
            Permissions.WORKSPACE_EXECUTE,
            Permissions.ARTIFACT_READ,
            Permissions.ARTIFACT_WRITE,
        }),
        consequential_actions_allowed=frozenset(),
        description="Runs benchmark harnesses and analyzes profiling data.",
    ),

    # ── 9 Legacy Modernization Workers ──
    "legacy_intake_specialist": WorkerSecurityProfile(
        worker_type="legacy_intake_specialist",
        is_legacy_worker=True,
        is_read_only=True,
        allowed_permissions=frozenset({
            Permissions.PROJECT_READ,
            Permissions.WORKSPACE_READ,
            Permissions.ARTIFACT_READ,
            Permissions.ARTIFACT_WRITE,
        }),
        consequential_actions_allowed=frozenset(),
        description="Intakes legacy assets and verifies repository inventory (Strictly Read-Only).",
    ),
    "legacy_codebase_archaeologist": WorkerSecurityProfile(
        worker_type="legacy_codebase_archaeologist",
        is_legacy_worker=True,
        is_read_only=True,
        allowed_permissions=frozenset({
            Permissions.PROJECT_READ,
            Permissions.WORKSPACE_READ,
            Permissions.RESEARCH_EXECUTE,
            Permissions.ARTIFACT_READ,
            Permissions.ARTIFACT_WRITE,
        }),
        consequential_actions_allowed=frozenset(),
        description="Extracts factual archaeology evidence from legacy code (Strictly Read-Only).",
    ),
    "legacy_dependency_analyst": WorkerSecurityProfile(
        worker_type="legacy_dependency_analyst",
        is_legacy_worker=True,
        is_read_only=True,
        allowed_permissions=frozenset({
            Permissions.PROJECT_READ,
            Permissions.WORKSPACE_READ,
            Permissions.RESEARCH_EXECUTE,
            Permissions.ARTIFACT_READ,
            Permissions.ARTIFACT_WRITE,
        }),
        consequential_actions_allowed=frozenset(),
        description="Analyzes legacy dependencies and library versions (Strictly Read-Only).",
    ),
    "legacy_architecture_reconstructor": WorkerSecurityProfile(
        worker_type="legacy_architecture_reconstructor",
        is_legacy_worker=True,
        is_read_only=True,
        allowed_permissions=frozenset({
            Permissions.PROJECT_READ,
            Permissions.WORKSPACE_READ,
            Permissions.ARCHITECTURE_PROPOSE,
            Permissions.ARTIFACT_READ,
            Permissions.ARTIFACT_WRITE,
        }),
        consequential_actions_allowed=frozenset(),
        description="Reconstructs conceptual legacy architecture models (Propose Only).",
    ),
    "business_logic_extractor": WorkerSecurityProfile(
        worker_type="business_logic_extractor",
        is_legacy_worker=True,
        is_read_only=True,
        allowed_permissions=frozenset({
            Permissions.PROJECT_READ,
            Permissions.WORKSPACE_READ,
            Permissions.RESEARCH_PROPOSE,
            Permissions.ARTIFACT_READ,
            Permissions.ARTIFACT_WRITE,
        }),
        consequential_actions_allowed=frozenset(),
        description="Extracts implicit domain business rules from legacy source code (Propose Only).",
    ),
    "modernization_strategy_planner": WorkerSecurityProfile(
        worker_type="modernization_strategy_planner",
        is_legacy_worker=True,
        is_read_only=True,
        allowed_permissions=frozenset({
            Permissions.PROJECT_READ,
            Permissions.WORKSPACE_READ,
            Permissions.MIGRATION_PLAN,
            Permissions.ARTIFACT_READ,
            Permissions.ARTIFACT_WRITE,
        }),
        consequential_actions_allowed=frozenset(),
        description="Drafts target modernization and migration roadmap strategies (Propose Only).",
    ),
    "incremental_migration_engineer": WorkerSecurityProfile(
        worker_type="incremental_migration_engineer",
        is_legacy_worker=True,
        is_read_only=False,
        allowed_permissions=frozenset({
            Permissions.PROJECT_READ,
            Permissions.WORKSPACE_READ,
            Permissions.WORKSPACE_WRITE,
            Permissions.WORKSPACE_EXECUTE,
            Permissions.EXECUTION_EXECUTE,
            Permissions.ARTIFACT_READ,
            Permissions.ARTIFACT_WRITE,
        }),
        consequential_actions_allowed=frozenset(),
        description="Implements code transforms and adapters; migration execution requires HITL gate.",
    ),
    "parity_regression_tester": WorkerSecurityProfile(
        worker_type="parity_regression_tester",
        is_legacy_worker=True,
        is_read_only=False,
        allowed_permissions=frozenset({
            Permissions.PROJECT_READ,
            Permissions.WORKSPACE_READ,
            Permissions.WORKSPACE_WRITE,
            Permissions.WORKSPACE_EXECUTE,
            Permissions.EXECUTION_EXECUTE,
            Permissions.ARTIFACT_READ,
            Permissions.ARTIFACT_WRITE,
        }),
        consequential_actions_allowed=frozenset(),
        description="Validates behavioral parity between legacy and modernized systems.",
    ),
    "cutover_deployment_specialist": WorkerSecurityProfile(
        worker_type="cutover_deployment_specialist",
        is_legacy_worker=True,
        is_read_only=False,
        allowed_permissions=frozenset({
            Permissions.PROJECT_READ,
            Permissions.WORKSPACE_READ,
            Permissions.ARTIFACT_READ,
            Permissions.ARTIFACT_WRITE,
        }),
        consequential_actions_allowed=frozenset(),
        description="Prepares cutover manifests; cutover execution strictly requires HITL gate.",
    ),
}


class WorkforceSecurityGuard:
    """
    Enforces security invariants and privilege boundaries on autonomous workers.
    """

    @staticmethod
    def get_profile(worker_type: str) -> WorkerSecurityProfile | None:
        return WORKER_SECURITY_PROFILES.get(worker_type)

    @staticmethod
    def validate_worker_action(worker_type: str, action: str) -> None:
        """
        Assert that the given worker type is permitted to request or execute the specified action.
        """
        profile = WORKER_SECURITY_PROFILES.get(worker_type)
        if not profile:
            raise InsufficientPrivilegesError(f"Unknown or uncertified worker type '{worker_type}'.")

        if action not in profile.allowed_permissions:
            raise InsufficientPrivilegesError(
                f"Worker '{worker_type}' is prohibited from performing action '{action}'.",
                details={
                    "worker_type": worker_type,
                    "action": action,
                    "is_read_only": profile.is_read_only,
                },
            )
