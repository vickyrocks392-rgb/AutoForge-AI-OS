"""Review Platform exception taxonomy — Phase 11."""

from __future__ import annotations

from typing import Any


class ReviewError(Exception):
    """Root for all Review Platform errors."""

    def __init__(
        self,
        message: str,
        *,
        code: str = "REVIEW_ERROR",
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.details: dict[str, Any] = details or {}

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(message={self.message!r}, code={self.code!r})"


class ReviewValidationError(ReviewError):
    """A review request or evidence bundle was malformed."""

    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message, code="REVIEW_VALIDATION_ERROR", details=details)


class ReviewPolicyRejectedError(ReviewError):
    """A review was rejected because the policy could not be applied."""

    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message, code="REVIEW_POLICY_REJECTED", details=details)


class ReviewNotRunError(ReviewError):
    """A review is referenced but has not been executed."""

    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message, code="REVIEW_NOT_RUN", details=details)


class ReviewAiUnavailableError(ReviewError):
    """AI-assisted review was requested but no AI provider is available."""

    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message, code="REVIEW_AI_UNAVAILABLE", details=details)


class ReviewLoopError(ReviewError):
    """Review loop control-flow error."""

    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message, code="REVIEW_LOOP_ERROR", details=details)