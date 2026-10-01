"""
AutoForge Security & Governance Platform (Phase 15).

Authoritative, deterministic security subsystem for AutoForge AI OS.
"""

from __future__ import annotations

from autoforge_security.audit import AuditEngine
from autoforge_security.ai_guardrails import (
    ACTION_CAPABILITIES,
    DATA_ONLY_TRUST,
    LEARNABLE_PROPOSAL_KINDS,
    LEARNING_FORBIDDEN_CAPABILITIES,
    NON_AUTHORITATIVE_TRUST,
    SECURITY_SENSITIVE_CLASSES,
    AIGuardrailsEngine,
    ActionClass,
    Capability,
    GuardrailDecision,
    GuardrailDecisionType,
    GuardrailRequest,
    LearningProposal,
    LearningProposalDecision,
    TrustLevel,
)
from autoforge_security.trust_boundary import (
    BoundarySegment,
    TrustBoundary,
    TrustBoundaryViolation,
    contains_instruction_injection,
    neutralize_instruction_injection,
)
from autoforge_security.authentication import AuthenticationService
from autoforge_security.authorization import AuthorizationEngine
from autoforge_security.credentials import (
    CredentialManager,
    CredentialStore,
    InMemoryCredentialStore,
    LocalEncryptedStore,
)
from autoforge_security.engine import SecurityPlatform
from autoforge_security.errors import (
    ApprovalGateExpiredError,
    ApprovalGateNotFoundError,
    AuthenticationError,
    AuthorizationError,
    ConsequentialActionBlockedError,
    ContextualAuthorizationError,
    CredentialNotFoundError,
    CredentialStoreError,
    DangerousCommandBlockedError,
    GovernanceError,
    IdentityNotFoundError,
    InsufficientPrivilegesError,
    InvalidTokenError,
    PathTraversalBlockedError,
    SandboxViolationError,
    SecretAccessError,
    SecurityError,
    SelfApprovalForbiddenError,
)
from autoforge_security.events import SecurityEventPublisher
from autoforge_security.governance import GovernancePolicyEngine
from autoforge_security.hitl import HITLManager
from autoforge_security.identity import IdentityProvider, LocalIdentityProvider
from autoforge_security.models import (
    ApprovalGateStatus,
    AuditRecord,
    AuthenticationResult,
    AuthorizationDecision,
    AuthorizationRequest,
    ConsequentialAction,
    CredentialMetadata,
    CredentialType,
    DecisionType,
    GovernancePolicy,
    HITLApprovalGate,
    HITLDecisionRecord,
    Permission,
    RoleDefinition,
    SandboxPolicy,
    SecretScope,
    Session,
    Subject,
    SubjectType,
)
from autoforge_security.permissions import ALL_PERMISSIONS, Permissions
from autoforge_security.roles import CANONICAL_ROLES, Roles, resolve_role_permissions
from autoforge_security.sandbox import SandboxPolicyEngine
from autoforge_security.secrets import SecretValue, SecretsManager
from autoforge_security.worker_guard import (
    WORKER_SECURITY_PROFILES,
    WorkerSecurityProfile,
    WorkforceSecurityGuard,
)

__all__ = [
    # AI Guardrails Layer
    "AIGuardrailsEngine",
    "ActionClass",
    "Capability",
    "GuardrailDecision",
    "GuardrailDecisionType",
    "GuardrailRequest",
    "LearningProposal",
    "LearningProposalDecision",
    "TrustLevel",
    "TrustBoundary",
    "BoundarySegment",
    "TrustBoundaryViolation",
    "ACTION_CAPABILITIES",
    "DATA_ONLY_TRUST",
    "LEARNABLE_PROPOSAL_KINDS",
    "LEARNING_FORBIDDEN_CAPABILITIES",
    "NON_AUTHORITATIVE_TRUST",
    "SECURITY_SENSITIVE_CLASSES",
    "contains_instruction_injection",
    "neutralize_instruction_injection",
    # Engine & Facade
    "SecurityPlatform",
    "AuthenticationService",
    "AuthorizationEngine",
    "GovernancePolicyEngine",
    "HITLManager",
    "SecretsManager",
    "CredentialManager",
    "SandboxPolicyEngine",
    "AuditEngine",
    "SecurityEventPublisher",
    "WorkforceSecurityGuard",
    # Providers & Stores
    "IdentityProvider",
    "LocalIdentityProvider",
    "CredentialStore",
    "InMemoryCredentialStore",
    "LocalEncryptedStore",
    "SecretValue",
    # Models
    "Subject",
    "SubjectType",
    "AuthenticationResult",
    "Session",
    "Permission",
    "RoleDefinition",
    "DecisionType",
    "AuthorizationRequest",
    "AuthorizationDecision",
    "ConsequentialAction",
    "GovernancePolicy",
    "ApprovalGateStatus",
    "HITLDecisionRecord",
    "HITLApprovalGate",
    "SecretScope",
    "CredentialType",
    "CredentialMetadata",
    "AuditRecord",
    "SandboxPolicy",
    "WorkerSecurityProfile",
    # Catalogs & Constants
    "Permissions",
    "ALL_PERMISSIONS",
    "Roles",
    "CANONICAL_ROLES",
    "WORKER_SECURITY_PROFILES",
    "resolve_role_permissions",
    # Errors
    "SecurityError",
    "AuthenticationError",
    "InvalidTokenError",
    "IdentityNotFoundError",
    "AuthorizationError",
    "InsufficientPrivilegesError",
    "ContextualAuthorizationError",
    "GovernanceError",
    "ConsequentialActionBlockedError",
    "SelfApprovalForbiddenError",
    "ApprovalGateExpiredError",
    "ApprovalGateNotFoundError",
    "SecretAccessError",
    "CredentialStoreError",
    "CredentialNotFoundError",
    "SandboxViolationError",
    "DangerousCommandBlockedError",
    "PathTraversalBlockedError",
]
