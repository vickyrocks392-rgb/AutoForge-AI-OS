"""
Fine-grained Permission Taxonomy & Catalog for AutoForge Security (Phase 15).
"""

from __future__ import annotations
from autoforge_security.models import Permission


class Permissions:
    """Canonical permission identifiers."""

    # Project
    PROJECT_READ = "project.read"
    PROJECT_WRITE = "project.write"
    PROJECT_DELETE = "project.delete"

    # Workspace
    WORKSPACE_READ = "workspace.read"
    WORKSPACE_WRITE = "workspace.write"
    WORKSPACE_EXECUTE = "workspace.execute"

    # Research & Analysis
    RESEARCH_EXECUTE = "research.execute"
    RESEARCH_PROPOSE = "research.propose"

    # Architecture
    ARCHITECTURE_PROPOSE = "architecture.propose"
    ARCHITECTURE_FINALIZE = "architecture.finalize"  # Gated

    # Technology Stack
    TECHNOLOGY_PROPOSE = "technology.propose"
    TECHNOLOGY_FINALIZE = "technology.finalize"  # Gated

    # Workflows
    WORKFLOW_CREATE = "workflow.create"
    WORKFLOW_EXECUTE = "workflow.execute"
    WORKFLOW_CANCEL = "workflow.cancel"

    # Execution Engine
    EXECUTION_EXECUTE = "execution.execute"
    EXECUTION_CANCEL = "execution.cancel"

    # Artifacts
    ARTIFACT_READ = "artifact.read"
    ARTIFACT_WRITE = "artifact.write"
    ARTIFACT_PUBLISH = "artifact.publish"  # Gated
    ARTIFACT_ROLLBACK = "artifact.rollback"  # Gated

    # Deployment
    DEPLOYMENT_EXECUTE = "deployment.execute"  # Gated
    DEPLOYMENT_ROLLBACK = "deployment.rollback"  # Gated

    # Migration & Modernization
    MIGRATION_PLAN = "migration.plan"
    MIGRATION_EXECUTE = "migration.execute"  # Gated
    MIGRATION_CUTOVER = "migration.cutover"  # Gated

    # Credentials
    CREDENTIAL_READ = "credential.read"
    CREDENTIAL_USE = "credential.use"
    CREDENTIAL_MANAGE = "credential.manage"  # Gated

    # Secrets
    SECRET_READ = "secret.read"
    SECRET_MANAGE = "secret.manage"  # Gated

    # Governance & HITL
    GOVERNANCE_APPROVE = "governance.approve"  # Human only
    GOVERNANCE_CONFIGURE = "governance.configure"  # Gated

    # Audit & Observability
    AUDIT_READ = "audit.read"

    # System Administration
    SYSTEM_ADMIN = "system.admin"


ALL_PERMISSIONS: dict[str, Permission] = {
    Permissions.PROJECT_READ: Permission(
        permission_id=Permissions.PROJECT_READ,
        category="project",
        description="Read project metadata and specifications.",
    ),
    Permissions.PROJECT_WRITE: Permission(
        permission_id=Permissions.PROJECT_WRITE,
        category="project",
        description="Create and update projects.",
    ),
    Permissions.PROJECT_DELETE: Permission(
        permission_id=Permissions.PROJECT_DELETE,
        category="project",
        description="Delete projects.",
        is_consequential=True,
    ),
    Permissions.WORKSPACE_READ: Permission(
        permission_id=Permissions.WORKSPACE_READ,
        category="workspace",
        description="Read files and state within workspace.",
    ),
    Permissions.WORKSPACE_WRITE: Permission(
        permission_id=Permissions.WORKSPACE_WRITE,
        category="workspace",
        description="Write and modify files within workspace.",
    ),
    Permissions.WORKSPACE_EXECUTE: Permission(
        permission_id=Permissions.WORKSPACE_EXECUTE,
        category="workspace",
        description="Execute commands/tests within sandboxed workspace.",
    ),
    Permissions.RESEARCH_EXECUTE: Permission(
        permission_id=Permissions.RESEARCH_EXECUTE,
        category="research",
        description="Execute research and information extraction tasks.",
    ),
    Permissions.RESEARCH_PROPOSE: Permission(
        permission_id=Permissions.RESEARCH_PROPOSE,
        category="research",
        description="Propose research findings and hypotheses.",
    ),
    Permissions.ARCHITECTURE_PROPOSE: Permission(
        permission_id=Permissions.ARCHITECTURE_PROPOSE,
        category="architecture",
        description="Propose architectural blueprints and system designs.",
    ),
    Permissions.ARCHITECTURE_FINALIZE: Permission(
        permission_id=Permissions.ARCHITECTURE_FINALIZE,
        category="architecture",
        description="Finalize system architecture decisions (Consequential).",
        is_consequential=True,
    ),
    Permissions.TECHNOLOGY_PROPOSE: Permission(
        permission_id=Permissions.TECHNOLOGY_PROPOSE,
        category="technology",
        description="Propose technology stack choices.",
    ),
    Permissions.TECHNOLOGY_FINALIZE: Permission(
        permission_id=Permissions.TECHNOLOGY_FINALIZE,
        category="technology",
        description="Finalize technology stack choices (Consequential).",
        is_consequential=True,
    ),
    Permissions.WORKFLOW_CREATE: Permission(
        permission_id=Permissions.WORKFLOW_CREATE,
        category="workflow",
        description="Create workflow DAGs.",
    ),
    Permissions.WORKFLOW_EXECUTE: Permission(
        permission_id=Permissions.WORKFLOW_EXECUTE,
        category="workflow",
        description="Execute workflows.",
    ),
    Permissions.WORKFLOW_CANCEL: Permission(
        permission_id=Permissions.WORKFLOW_CANCEL,
        category="workflow",
        description="Cancel executing workflows.",
    ),
    Permissions.EXECUTION_EXECUTE: Permission(
        permission_id=Permissions.EXECUTION_EXECUTE,
        category="execution",
        description="Trigger engineering worker execution loops.",
    ),
    Permissions.EXECUTION_CANCEL: Permission(
        permission_id=Permissions.EXECUTION_CANCEL,
        category="execution",
        description="Cancel active worker execution loops.",
    ),
    Permissions.ARTIFACT_READ: Permission(
        permission_id=Permissions.ARTIFACT_READ,
        category="artifact",
        description="Read registered platform artifacts.",
    ),
    Permissions.ARTIFACT_WRITE: Permission(
        permission_id=Permissions.ARTIFACT_WRITE,
        category="artifact",
        description="Draft and update artifacts.",
    ),
    Permissions.ARTIFACT_PUBLISH: Permission(
        permission_id=Permissions.ARTIFACT_PUBLISH,
        category="artifact",
        description="Publish canonical versioned artifacts (Consequential).",
        is_consequential=True,
    ),
    Permissions.ARTIFACT_ROLLBACK: Permission(
        permission_id=Permissions.ARTIFACT_ROLLBACK,
        category="artifact",
        description="Rollback artifacts to prior versions (Consequential).",
        is_consequential=True,
    ),
    Permissions.DEPLOYMENT_EXECUTE: Permission(
        permission_id=Permissions.DEPLOYMENT_EXECUTE,
        category="deployment",
        description="Execute deployments to staging/production (Consequential).",
        is_consequential=True,
    ),
    Permissions.DEPLOYMENT_ROLLBACK: Permission(
        permission_id=Permissions.DEPLOYMENT_ROLLBACK,
        category="deployment",
        description="Rollback deployments (Consequential).",
        is_consequential=True,
    ),
    Permissions.MIGRATION_PLAN: Permission(
        permission_id=Permissions.MIGRATION_PLAN,
        category="migration",
        description="Plan modernization and migration tasks.",
    ),
    Permissions.MIGRATION_EXECUTE: Permission(
        permission_id=Permissions.MIGRATION_EXECUTE,
        category="migration",
        description="Execute database/code migrations (Consequential).",
        is_consequential=True,
    ),
    Permissions.MIGRATION_CUTOVER: Permission(
        permission_id=Permissions.MIGRATION_CUTOVER,
        category="migration",
        description="Perform live system cutover (Consequential).",
        is_consequential=True,
    ),
    Permissions.CREDENTIAL_READ: Permission(
        permission_id=Permissions.CREDENTIAL_READ,
        category="credential",
        description="Read credential metadata.",
    ),
    Permissions.CREDENTIAL_USE: Permission(
        permission_id=Permissions.CREDENTIAL_USE,
        category="credential",
        description="Use scoped credentials for outbound connector calls.",
    ),
    Permissions.CREDENTIAL_MANAGE: Permission(
        permission_id=Permissions.CREDENTIAL_MANAGE,
        category="credential",
        description="Store, rotate, and revoke credentials (Consequential).",
        is_consequential=True,
    ),
    Permissions.SECRET_READ: Permission(
        permission_id=Permissions.SECRET_READ,
        category="secret",
        description="Read secrets within authorized scope.",
    ),
    Permissions.SECRET_MANAGE: Permission(
        permission_id=Permissions.SECRET_MANAGE,
        category="secret",
        description="Manage secrets (Consequential).",
        is_consequential=True,
    ),
    Permissions.GOVERNANCE_APPROVE: Permission(
        permission_id=Permissions.GOVERNANCE_APPROVE,
        category="governance",
        description="Authorize or reject HITL approval gates (Human Only).",
        is_consequential=True,
    ),
    Permissions.GOVERNANCE_CONFIGURE: Permission(
        permission_id=Permissions.GOVERNANCE_CONFIGURE,
        category="governance",
        description="Modify governance and security policies (Consequential).",
        is_consequential=True,
    ),
    Permissions.AUDIT_READ: Permission(
        permission_id=Permissions.AUDIT_READ,
        category="audit",
        description="Read audit trail logs and security event records.",
    ),
    Permissions.SYSTEM_ADMIN: Permission(
        permission_id=Permissions.SYSTEM_ADMIN,
        category="system",
        description="Superuser administrator permissions across the platform.",
        is_consequential=True,
    ),
}

ACTION_TO_PERMISSION_MAP: dict[str, str] = {
    "tech_stack_finalization": Permissions.TECHNOLOGY_FINALIZE,
    "technology.finalize": Permissions.TECHNOLOGY_FINALIZE,
    "architecture_finalization": Permissions.ARCHITECTURE_FINALIZE,
    "architecture.finalize": Permissions.ARCHITECTURE_FINALIZE,
    "migration_execution": Permissions.MIGRATION_EXECUTE,
    "migration.execute": Permissions.MIGRATION_EXECUTE,
    "migration_cutover": Permissions.MIGRATION_CUTOVER,
    "migration.cutover": Permissions.MIGRATION_CUTOVER,
    "deployment": Permissions.DEPLOYMENT_EXECUTE,
    "deployment.execute": Permissions.DEPLOYMENT_EXECUTE,
    "destructive_cleanup": Permissions.PROJECT_DELETE,
    "credential_access": Permissions.CREDENTIAL_USE,
    "security_configuration_change": Permissions.GOVERNANCE_CONFIGURE,
    "artifact_publication": Permissions.ARTIFACT_PUBLISH,
    "artifact.publish": Permissions.ARTIFACT_PUBLISH,
    "artifact_rollback": Permissions.ARTIFACT_ROLLBACK,
    "artifact.rollback": Permissions.ARTIFACT_ROLLBACK,
}
