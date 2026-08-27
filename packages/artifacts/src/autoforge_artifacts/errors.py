"""Artifact Platform error taxonomy — Phase 12.

Package-owned error hierarchy for the Artifact Platform. Each error class
represents a meaningful, distinct failure category. Retryability is explicit
where relevant.

Design rules
------------
- This is a PACKAGE-LOCAL hierarchy — not a global error system.
- Every error carries a human-readable ``message`` and optional ``details``.
- ``retryable`` is explicit so callers can decide retry policy deterministically.
- No AI is used to classify errors.
"""

from __future__ import annotations

from typing import Any


class ArtifactError(Exception):
    """Base exception for all Artifact Platform errors."""

    def __init__(
        self,
        message: str,
        *,
        details: dict[str, Any] | None = None,
        retryable: bool = False,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}
        self.retryable = retryable


class ArtifactValidationError(ArtifactError):
    """Raised when artifact input is malformed or violates constraints."""

    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message, details=details, retryable=False)


class ArtifactNotFoundError(ArtifactError):
    """Raised when a requested artifact or version does not exist."""

    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message, details=details, retryable=False)


class ArtifactConflictError(ArtifactError):
    """Raised on concurrent version conflict (lost update detection)."""

    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message, details=details, retryable=True)


class ArtifactIntegrityError(ArtifactError):
    """Raised when stored content hash does not match metadata."""

    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message, details=details, retryable=False)


class ArtifactAuthorizationError(ArtifactError):
    """Raised when an operation is not authorized by policy."""

    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message, details=details, retryable=False)


class ArtifactPublicationError(ArtifactError):
    """Raised when artifact publication fails."""

    def __init__(
        self,
        message: str,
        *,
        details: dict[str, Any] | None = None,
        retryable: bool = False,
    ) -> None:
        super().__init__(message, details=details, retryable=retryable)


class ArtifactRollbackError(ArtifactError):
    """Raised when rollback validation fails."""

    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message, details=details, retryable=False)


class ArtifactStorageError(ArtifactError):
    """Raised when the storage backend encounters an error."""

    def __init__(
        self,
        message: str,
        *,
        details: dict[str, Any] | None = None,
        retryable: bool = True,
    ) -> None:
        super().__init__(message, details=details, retryable=retryable)
