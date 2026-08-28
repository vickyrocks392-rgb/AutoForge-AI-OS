"""
Unified Security & Governance Platform Facade for AutoForge AI OS (Phase 15).
"""

from __future__ import annotations

import contextvars
from pathlib import Path
from typing import Any, Mapping

from autoforge_security.audit import AuditEngine
from autoforge_security.authentication import AuthenticationService
from autoforge_security.authorization import AuthorizationEngine
from autoforge_security.credentials import CredentialManager, CredentialStore, InMemoryCredentialStore
from autoforge_security.errors import (
    ApprovalGateNotFoundError,
    AuthenticationError,
    AuthorizationError,
    ConsequentialActionBlockedError,
    InsufficientPrivilegesError,
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
    SandboxPolicy,
    SecretScope,
    Subject,
    SubjectType,
)
from autoforge_security.permissions import ALL_PERMISSIONS, Permissions
from autoforge_security.roles import Roles
from autoforge_security.sandbox import SandboxPolicyEngine
from autoforge_security.secrets import SecretValue, SecretsManager
from autoforge_security.worker_guard import WorkforceSecurityGuard

# Context variable for thread-local / task-local current subject
_CURRENT_SUBJECT: contextvars.ContextVar[Subject | None] = contextvars.ContextVar(
    "autoforge_current_subject", default=None
)


class SecurityPlatform:
    """
    Authoritative, deterministic Security & Governance Platform.
    Coordinates authentication, authorization, RBAC, secrets, credentials,
    sandboxing, audit trail, and HITL consequential action gating.
    """

    def __init__(
        self,
        *,
        identity_provider: IdentityProvider | None = None,
        governance_policy: GovernancePolicy | None = None,
        sandbox_policy: SandboxPolicy | None = None,
        credential_store: CredentialStore | None = None,
        canonical_bus: Any | None = None,
    ) -> None:
        self._idp = identity_provider or LocalIdentityProvider()
        self._auth = AuthenticationService(identity_provider=self._idp)
        self._authz = AuthorizationEngine()
        self._governance = GovernancePolicyEngine(policy=governance_policy)
        self._hitl = HITLManager(governance_engine=self._governance)
        self._secrets = SecretsManager()
        self._credentials = CredentialManager(store=credential_store or InMemoryCredentialStore())
        self._sandbox = SandboxPolicyEngine(policy=sandbox_policy)
        self._events = SecurityEventPublisher(canonical_bus=canonical_bus)
        self._audit = AuditEngine(
            secrets_manager=self._secrets,
            event_sink=self._events.publish_audit_event,
        )
        self._worker_guard = WorkforceSecurityGuard()

    # ── Subsystem Accessors ──────────────────────────────────────────────────

    @property
    def authentication(self) -> AuthenticationService:
        return self._auth

    @property
    def authorization(self) -> AuthorizationEngine:
        return self._authz

    @property
    def governance(self) -> GovernancePolicyEngine:
        return self._governance

    @property
    def hitl(self) -> HITLManager:
        return self._hitl

    @property
    def secrets(self) -> SecretsManager:
        return self._secrets

    @property
    def credentials(self) -> CredentialManager:
        return self._credentials

    @property
    def sandbox(self) -> SandboxPolicyEngine:
        return self._sandbox

    @property
    def audit(self) -> AuditEngine:
        return self._audit

    @property
    def events(self) -> SecurityEventPublisher:
        return self._events

    @property
    def worker_guard(self) -> WorkforceSecurityGuard:
        return self._worker_guard

    # ── Context Management ───────────────────────────────────────────────────

    def set_current_subject(self, subject: Subject | None) -> None:
        """Set the active subject for the current async task context."""
        _CURRENT_SUBJECT.set(subject)

    def get_current_subject(self) -> Subject:
        """Get the active subject in context, falling back to anonymous."""
        subj = _CURRENT_SUBJECT.get()
        if subj:
            return subj
        anon = self._idp.get_subject("subject_anonymous")
        if anon:
            return anon
        return Subject(
            subject_id="subject_anonymous",
            display_name="Anonymous Observer",
            subject_type=SubjectType.ANONYMOUS,
            roles=frozenset({Roles.READ_ONLY_OBSERVER}),
        )

    # ── Authentication Operations ────────────────────────────────────────────

    def login_password(self, subject_id: str, password: str) -> AuthenticationResult:
        res = self._auth.authenticate_password(subject_id, password)
        if res.authenticated and res.subject:
            self._audit.record_security_event(
                actor=res.subject,
                action="authentication.login_password",
                resource=subject_id,
                decision=DecisionType.ALLOW,
                reason="Password authentication successful.",
            )
            self.set_current_subject(res.subject)
        else:
            anon = self.get_current_subject()
            self._audit.record_security_event(
                actor=anon,
                action="authentication.login_password",
                resource=subject_id,
                decision=DecisionType.DENY,
                reason=res.error_message or "Password authentication failed.",
                outcome="failed",
            )
        return res

    def login_api_key(self, api_key: str) -> AuthenticationResult:
        res = self._auth.authenticate_api_key(api_key)
        if res.authenticated and res.subject:
            self._audit.record_security_event(
                actor=res.subject,
                action="authentication.login_api_key",
                resource="api_key",
                decision=DecisionType.ALLOW,
                reason="API key authentication successful.",
            )
            self.set_current_subject(res.subject)
        else:
            anon = self.get_current_subject()
            self._audit.record_security_event(
                actor=anon,
                action="authentication.login_api_key",
                resource="api_key",
                decision=DecisionType.DENY,
                reason=res.error_message or "API key authentication failed.",
                outcome="failed",
            )
        return res

    def login_token(self, token: str) -> AuthenticationResult:
        res = self._auth.authenticate_token(token)
        if res.authenticated and res.subject:
            self.set_current_subject(res.subject)
        return res

    # ── Authorization & Evaluation ───────────────────────────────────────────

    def authorize(
        self,
        action: str,
        resource: str,
        *,
        subject: Subject | None = None,
        context: dict[str, Any] | None = None,
        project_id: str | None = None,
        workflow_id: str | None = None,
        task_id: str | None = None,
        worker_id: str | None = None,
        execution_id: str | None = None,
        correlation_id: str | None = None,
        trace_id: str | None = None,
        gate_id: str | None = None,
        resume_token: str | None = None,
    ) -> AuthorizationDecision:
        """
        Authoritatively evaluate if an action is permitted.
        Checks RBAC, contextual rules, governance policy, and approval gates.
        """
        actor = subject or self.get_current_subject()
        req = AuthorizationRequest(
            subject=actor,
            action=action,
            resource=resource,
            context=context or {},
            project_id=project_id,
            workflow_id=workflow_id,
            task_id=task_id,
            worker_id=worker_id,
            execution_id=execution_id,
            correlation_id=correlation_id,
            trace_id=trace_id,
        )

        # 1. Base RBAC check
        rbac_decision = self._authz.evaluate(req)
        if not rbac_decision.is_allowed:
            self._audit.record_decision(req, rbac_decision)
            return rbac_decision

        # 2. Consequential governance evaluation if action is consequential
        is_consequential = False
        consequential_action = None
        try:
            consequential_action = ConsequentialAction(action)
            is_consequential = True
        except ValueError:
            perm_def = ALL_PERMISSIONS.get(action)
            if perm_def and perm_def.is_consequential:
                is_consequential = True

        if is_consequential and consequential_action:
            # Check if an approved gate was supplied and verified
            has_approved_gate = False
            if gate_id and resume_token:
                has_approved_gate = self._hitl.verify_resume_token(gate_id, resume_token)

            gov_decision = self._governance.evaluate_consequential_action(
                action=consequential_action,
                subject=actor,
                has_approved_gate=has_approved_gate,
                gate_id=gate_id,
                context=context,
            )
            self._audit.record_decision(req, gov_decision)
            return gov_decision

        self._audit.record_decision(req, rbac_decision)
        return rbac_decision

    # ── HITL Operations ──────────────────────────────────────────────────────

    def request_approval(
        self,
        action: ConsequentialAction | str,
        description: str,
        *,
        requested_by: Subject | None = None,
        requested_by_worker_id: str | None = None,
        project_id: str | None = None,
        workflow_id: str | None = None,
        task_id: str | None = None,
        execution_id: str | None = None,
        required_approvers: int = 1,
        ttl_seconds: int | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> HITLApprovalGate:
        """Create a new human approval gate and broadcast notification."""
        actor = requested_by or self.get_current_subject()
        gate = self._hitl.create_gate(
            action=action,
            requested_by=actor,
            description=description,
            requested_by_worker_id=requested_by_worker_id,
            project_id=project_id,
            workflow_id=workflow_id,
            task_id=task_id,
            execution_id=execution_id,
            required_approvers=required_approvers,
            ttl_seconds=ttl_seconds,
            metadata=metadata,
        )
        self._events.publish_hitl_gate_created(gate)
        return gate

    def submit_approval_decision(
        self,
        gate_id: str,
        approver: Subject,
        status: ApprovalGateStatus,
        reason: str = "",
    ) -> HITLApprovalGate:
        """Record human approval or rejection decision."""
        # Ensure approver has GOVERNANCE_APPROVE permission
        if not self._authz.has_permission(approver, Permissions.GOVERNANCE_APPROVE):
            raise InsufficientPrivilegesError(
                f"Subject '{approver.subject_id}' lacks permission '{Permissions.GOVERNANCE_APPROVE}' to approve HITL gates."
            )

        gate = self._hitl.submit_decision(
            gate_id=gate_id,
            approver=approver,
            status=status,
            reason=reason,
        )
        self._events.publish_hitl_gate_decided(gate)

        self._audit.record_security_event(
            actor=approver,
            action=f"governance.hitl.{status.value}",
            resource=gate_id,
            decision=DecisionType.ALLOW if status == ApprovalGateStatus.APPROVED else DecisionType.DENY,
            reason=reason or f"HITL decision {status.value}",
            project_id=gate.project_id,
            workflow_id=gate.workflow_id,
            task_id=gate.task_id,
            execution_id=gate.execution_id,
            details={"gate_id": gate_id, "action": gate.action.value},
        )
        return gate

    # ── Secrets & Redaction ──────────────────────────────────────────────────

    def register_secret(self, name: str, value: str | SecretValue, scope: SecretScope = SecretScope.SYSTEM) -> None:
        self._secrets.register_secret(name, value, scope=scope)

    def get_secret(self, name: str, scope: SecretScope = SecretScope.SYSTEM, subject: Subject | None = None) -> SecretValue:
        actor = subject or self.get_current_subject()
        # Check secret read permission
        if not self._authz.has_permission(actor, Permissions.SECRET_READ):
            raise InsufficientPrivilegesError(f"Subject '{actor.subject_id}' lacks '{Permissions.SECRET_READ}' permission.")
        return self._secrets.get_secret(name, subject=actor, scope=scope)

    def redact(self, text: str) -> str:
        return self._secrets.redact_text(text)

    def redact_data(self, data: Any) -> Any:
        return self._secrets.redact_structure(data)

    # ── Credentials ──────────────────────────────────────────────────────────

    def store_credential(
        self,
        name: str,
        credential_type: CredentialType,
        provider: str,
        secret_value: str | SecretValue,
        *,
        scope: SecretScope = SecretScope.SYSTEM,
        subject: Subject | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> CredentialMetadata:
        actor = subject or self.get_current_subject()
        if not self._authz.has_permission(actor, Permissions.CREDENTIAL_MANAGE):
            raise InsufficientPrivilegesError(f"Subject '{actor.subject_id}' lacks '{Permissions.CREDENTIAL_MANAGE}' permission.")
        return self._credentials.register_credential(
            name=name,
            credential_type=credential_type,
            provider=provider,
            secret_value=secret_value,
            scope=scope,
            metadata=metadata,
        )

    def retrieve_credential(
        self,
        credential_id: str,
        subject: Subject | None = None,
    ) -> tuple[CredentialMetadata, SecretValue]:
        actor = subject or self.get_current_subject()
        if not self._authz.has_permission(actor, Permissions.CREDENTIAL_USE) and not self._authz.has_permission(actor, Permissions.CREDENTIAL_READ):
            raise InsufficientPrivilegesError(f"Subject '{actor.subject_id}' lacks credential access permissions.")
        return self._credentials.get_credential(credential_id)

    # ── Sandboxing ───────────────────────────────────────────────────────────

    def validate_workspace_path(self, workspace_root: str | Path, path: str) -> Path:
        return self._sandbox.validate_workspace_path(workspace_root, path)

    def validate_command(self, command: str) -> None:
        self._sandbox.validate_command(command)

    # ── Product Experience Read API (For Phase 16) ───────────────────────────

    def get_security_status(self) -> dict[str, Any]:
        """Expose current security posture, active sessions, and pending gates."""
        current = self.get_current_subject()
        perms = self._authz.get_subject_permissions(current)
        pending = self._hitl.list_pending_gates()
        return {
            "current_subject": {
                "id": current.subject_id,
                "display_name": current.display_name,
                "type": current.subject_type.value,
                "roles": sorted(list(current.roles)),
                "permissions_count": len(perms),
            },
            "pending_approvals_count": len(pending),
            "pending_approvals": [
                {
                    "gate_id": g.gate_id,
                    "action": g.action.value,
                    "description": g.description,
                    "requested_by": g.requested_by_subject_id,
                    "created_at": g.created_at.isoformat(),
                    "expires_at": g.expires_at.isoformat() if g.expires_at else None,
                }
                for g in pending
            ],
            "credentials_count": len(self._credentials.list_credentials()),
            "audit_records_count": len(self._audit.list_all()),
        }
