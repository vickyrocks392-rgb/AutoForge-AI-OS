"""
Domain models for AutoForge Security & Governance Platform (Phase 15).
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Mapping

from pydantic import BaseModel, ConfigDict, Field


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _new_uuid() -> uuid.UUID:
    return uuid.uuid4()


# ── Subject & Identity ───────────────────────────────────────────────────


class SubjectType(str, Enum):
    """Classification of an active actor in the system."""
    HUMAN = "human"
    SERVICE = "service"
    WORKER = "worker"
    ANONYMOUS = "anonymous"


class Subject(BaseModel):
    """
    Immutable representation of an authenticated or recognized identity.
    """
    model_config = ConfigDict(frozen=True, extra="forbid")

    subject_id: str
    display_name: str
    subject_type: SubjectType
    roles: frozenset[str] = Field(default_factory=frozenset)
    attributes: dict[str, Any] = Field(default_factory=dict)
    is_active: bool = True
    created_at: datetime = Field(default_factory=_utc_now)

    @property
    def is_human(self) -> bool:
        return self.subject_type == SubjectType.HUMAN

    @property
    def is_worker(self) -> bool:
        return self.subject_type == SubjectType.WORKER

    @property
    def is_service(self) -> bool:
        return self.subject_type == SubjectType.SERVICE


class AuthenticationResult(BaseModel):
    """Result of an authentication attempt."""
    model_config = ConfigDict(frozen=True, extra="forbid")

    authenticated: bool
    subject: Subject | None = None
    token: str | None = None
    error_message: str | None = None
    authenticated_at: datetime = Field(default_factory=_utc_now)
    metadata: dict[str, Any] = Field(default_factory=dict)


class Session(BaseModel):
    """Represents an active authenticated session."""
    model_config = ConfigDict(frozen=True, extra="forbid")

    session_id: str
    subject_id: str
    token_hash: str
    created_at: datetime = Field(default_factory=_utc_now)
    expires_at: datetime
    is_revoked: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)

    @property
    def is_expired(self) -> bool:
        return _utc_now() >= self.expires_at


# ── Permissions & RBAC ───────────────────────────────────────────────────


class Permission(BaseModel):
    """
    Fine-grained permission identifier and definition.
    """
    model_config = ConfigDict(frozen=True, extra="forbid")

    permission_id: str
    category: str
    description: str = ""
    is_consequential: bool = False


class RoleDefinition(BaseModel):
    """
    Canonical Role mapping to an explicit set of permissions.
    """
    model_config = ConfigDict(frozen=True, extra="forbid")

    role_id: str
    display_name: str
    description: str = ""
    permissions: frozenset[str] = Field(default_factory=frozenset)
    inherits_from: frozenset[str] = Field(default_factory=frozenset)


# ── Authorization Decisions ──────────────────────────────────────────────


class DecisionType(str, Enum):
    """Explainable authorization outcomes."""
    ALLOW = "allow"
    DENY = "deny"
    REQUIRE_HITL = "require_hitl"
    REQUIRE_ELEVATED_ROLE = "require_elevated_role"
    REQUIRE_ADDITIONAL_CONTEXT = "require_additional_context"


class AuthorizationRequest(BaseModel):
    """Input payload to evaluate an authorization check."""
    model_config = ConfigDict(frozen=True, extra="forbid")

    subject: Subject
    action: str
    resource: str
    context: dict[str, Any] = Field(default_factory=dict)
    project_id: str | None = None
    workflow_id: str | None = None
    task_id: str | None = None
    worker_id: str | None = None
    execution_id: str | None = None
    correlation_id: str | None = None
    trace_id: str | None = None


class AuthorizationDecision(BaseModel):
    """Deterministic, auditable decision from the authorization engine."""
    model_config = ConfigDict(frozen=True, extra="forbid")

    decision: DecisionType
    is_allowed: bool
    reason: str
    required_permissions: frozenset[str] = Field(default_factory=frozenset)
    policy_version: str = "1.0.0"
    evaluated_at: datetime = Field(default_factory=_utc_now)
    gate_id: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)


# ── Consequential Actions & Governance ───────────────────────────────────


class ConsequentialAction(str, Enum):
    """High-impact actions that must be governed and potentially gated."""
    TECH_STACK_FINALIZATION = "tech_stack_finalization"
    ARCHITECTURE_FINALIZATION = "architecture_finalization"
    MIGRATION_EXECUTION = "migration_execution"
    MIGRATION_CUTOVER = "migration_cutover"
    DEPLOYMENT = "deployment"
    DESTRUCTIVE_CLEANUP = "destructive_cleanup"
    CREDENTIAL_ACCESS = "credential_access"
    SECURITY_CONFIGURATION_CHANGE = "security_configuration_change"
    ARTIFACT_PUBLICATION = "artifact_publication"
    ARTIFACT_ROLLBACK = "artifact_rollback"


class GovernancePolicy(BaseModel):
    """
    Deterministic rules configuring action authorization and HITL gating.
    """
    model_config = ConfigDict(frozen=True, extra="forbid")

    policy_id: str = "default_governance_policy"
    policy_version: str = "1.0.0"
    gated_actions: frozenset[ConsequentialAction] = Field(
        default_factory=lambda: frozenset({
            ConsequentialAction.TECH_STACK_FINALIZATION,
            ConsequentialAction.ARCHITECTURE_FINALIZATION,
            ConsequentialAction.MIGRATION_EXECUTION,
            ConsequentialAction.MIGRATION_CUTOVER,
            ConsequentialAction.DEPLOYMENT,
            ConsequentialAction.DESTRUCTIVE_CLEANUP,
            ConsequentialAction.SECURITY_CONFIGURATION_CHANGE,
            ConsequentialAction.ARTIFACT_PUBLICATION,
        })
    )
    auto_approve_safe_actions: bool = True
    require_multi_approver: bool = False
    default_gate_timeout_seconds: int = 86400  # 24 hours


# ── Human Approval / HITL ────────────────────────────────────────────────


class ApprovalGateStatus(str, Enum):
    """Lifecycle status of a human approval gate."""
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"
    CANCELLED = "cancelled"


class HITLDecisionRecord(BaseModel):
    """Record of a human approval or rejection decision."""
    model_config = ConfigDict(frozen=True, extra="forbid")

    approver_id: str
    approver_name: str
    status: ApprovalGateStatus
    reason: str = ""
    decided_at: datetime = Field(default_factory=_utc_now)
    signature: str = ""


class HITLApprovalGate(BaseModel):
    """
    Centralized gate requiring human approval before action can proceed.
    """
    model_config = ConfigDict(extra="forbid")

    gate_id: str
    action: ConsequentialAction
    description: str
    requested_by_subject_id: str
    requested_by_worker_id: str | None = None
    project_id: str | None = None
    workflow_id: str | None = None
    task_id: str | None = None
    execution_id: str | None = None
    status: ApprovalGateStatus = ApprovalGateStatus.PENDING
    required_approvers: int = 1
    created_at: datetime = Field(default_factory=_utc_now)
    expires_at: datetime | None = None
    decisions: list[HITLDecisionRecord] = Field(default_factory=list)
    resume_token: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @property
    def is_resolved(self) -> bool:
        return self.status in {
            ApprovalGateStatus.APPROVED,
            ApprovalGateStatus.REJECTED,
            ApprovalGateStatus.EXPIRED,
            ApprovalGateStatus.CANCELLED,
        }


# ── Secrets & Credentials ────────────────────────────────────────────────


class SecretScope(str, Enum):
    """Scope of access granted for a secret."""
    SYSTEM = "system"
    CONNECTOR = "connector"
    WORKFLOW = "workflow"
    PROJECT = "project"
    DEPLOYMENT = "deployment"


class CredentialType(str, Enum):
    """Types of credentials managed in the platform."""
    API_KEY = "api_key"
    BEARER_TOKEN = "bearer_token"
    SSH_KEY = "ssh_key"
    BASIC_AUTH = "basic_auth"
    CERTIFICATE = "certificate"
    OAUTH_TOKEN = "oauth_token"


class CredentialMetadata(BaseModel):
    """Non-sensitive metadata describing a stored credential."""
    model_config = ConfigDict(frozen=True, extra="forbid")

    credential_id: str
    name: str
    credential_type: CredentialType
    provider: str
    scope: SecretScope = SecretScope.SYSTEM
    created_at: datetime = Field(default_factory=_utc_now)
    expires_at: datetime | None = None
    last_rotated_at: datetime | None = None
    is_revoked: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)


# ── Audit Trail ──────────────────────────────────────────────────────────


class AuditRecord(BaseModel):
    """
    Immutable audit log entry capturing every security and governance event.
    """
    model_config = ConfigDict(frozen=True, extra="forbid")

    audit_id: str = Field(default_factory=lambda: f"audit_{uuid.uuid4().hex[:12]}")
    timestamp: datetime = Field(default_factory=_utc_now)
    actor_id: str
    actor_type: SubjectType
    actor_roles: frozenset[str] = Field(default_factory=frozenset)
    action: str
    resource: str
    decision: DecisionType
    reason: str
    outcome: str = "success"  # "success", "blocked", "failed", "pending_hitl"
    project_id: str | None = None
    workflow_id: str | None = None
    task_id: str | None = None
    worker_id: str | None = None
    execution_id: str | None = None
    correlation_id: str | None = None
    trace_id: str | None = None
    policy_version: str = "1.0.0"
    details: dict[str, Any] = Field(default_factory=dict)


# ── Sandbox Policy ───────────────────────────────────────────────────────


class SandboxPolicy(BaseModel):
    """Deterministic configuration for workspace sandboxing."""
    model_config = ConfigDict(frozen=True, extra="forbid")

    enforce_workspace_confinement: bool = True
    allow_symlinks_outside_root: bool = False
    disallowed_commands: frozenset[str] = Field(
        default_factory=lambda: frozenset({
            "rm -rf /",
            "mkfs",
            "dd",
            "shutdown",
            "reboot",
            ":(){ :|:& };:",
            "chmod -R 777 /",
            "wget",
            "curl | bash",
        })
    )
    max_execution_timeout_seconds: int = 600
