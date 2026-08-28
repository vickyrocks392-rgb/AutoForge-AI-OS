"""
Typed exception hierarchy for AutoForge Security & Governance Platform (Phase 15).
"""

from __future__ import annotations
from typing import Any


class SecurityError(Exception):
    """Base exception for all security and governance violations."""

    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}

    def __str__(self) -> str:
        if self.details:
            return f"{self.message} (details={self.details})"
        return self.message


class AuthenticationError(SecurityError):
    """Raised when authentication fails (invalid credentials, expired token, etc.)."""
    pass


class InvalidTokenError(AuthenticationError):
    """Raised when an authentication token is malformed, expired, or invalid."""
    pass


class IdentityNotFoundError(AuthenticationError):
    """Raised when the requested subject or identity does not exist."""
    pass


class AuthorizationError(SecurityError):
    """Raised when an actor lacks permission to perform an action on a resource."""
    pass


class InsufficientPrivilegesError(AuthorizationError):
    """Raised when an actor's role lacks the required permission."""
    pass


class ContextualAuthorizationError(AuthorizationError):
    """Raised when contextual conditions (e.g. project mismatch, time window) fail."""
    pass


class GovernanceError(SecurityError):
    """Base exception for governance and policy violations."""
    pass


class ConsequentialActionBlockedError(GovernanceError):
    """Raised when a consequential action is attempted without required approval."""
    pass


class SelfApprovalForbiddenError(GovernanceError):
    """Raised when an AI worker or unauthorized subject attempts self-approval."""
    pass


class ApprovalGateExpiredError(GovernanceError):
    """Raised when an approval gate has expired and can no longer be decided."""
    pass


class ApprovalGateNotFoundError(GovernanceError):
    """Raised when an approval gate is not found."""
    pass


class SecretAccessError(SecurityError):
    """Raised when secret access is unauthorized or malformed."""
    pass


class CredentialStoreError(SecurityError):
    """Raised when credential storage or retrieval fails."""
    pass


class CredentialNotFoundError(CredentialStoreError):
    """Raised when a requested credential does not exist."""
    pass


class SandboxViolationError(SecurityError):
    """Raised when an execution or filesystem operation violates sandbox boundaries."""
    pass


class DangerousCommandBlockedError(SandboxViolationError):
    """Raised when a destructive or forbidden command is detected."""
    pass


class PathTraversalBlockedError(SandboxViolationError):
    """Raised when a path escapes the confined workspace root."""
    pass
