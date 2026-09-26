"""
Execution Platform exception taxonomy — Phase 10.

All errors raised by the Execution Platform inherit from ``ExecutionError``.
Machine-readable error codes and error context dictionaries are attached
to every error instance.
"""

from __future__ import annotations

from typing import Any


class ExecutionError(Exception):
    """Root error for all Execution Platform exceptions."""

    def __init__(
        self,
        message: str,
        *,
        code: str = "EXECUTION_ERROR",
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.details: dict[str, Any] = details or {}

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(message={self.message!r}, code={self.code!r}, details={self.details!r})"


class WorkerError(ExecutionError):
    """Errors during worker instantiation, lifecycle transition, or execution."""

    def __init__(
        self,
        message: str,
        *,
        code: str = "WORKER_ERROR",
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message, code=code, details=details)


class WorkerNotFoundError(WorkerError):
    """A worker ID was referenced but does not exist."""

    def __init__(
        self,
        message: str,
        *,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message, code="WORKER_NOT_FOUND", details=details)


class WorkerCancelledError(WorkerError):
    """Worker execution was cancelled before completion."""

    def __init__(
        self,
        message: str = "Worker execution was cancelled",
        *,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message, code="WORKER_CANCELLED", details=details)


class DispatchError(ExecutionError):
    """Errors during task dispatch or queue dequeue."""

    def __init__(
        self,
        message: str,
        *,
        code: str = "DISPATCH_ERROR",
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message, code=code, details=details)


class ConcurrencyLimitExceededError(DispatchError):
    """Dispatch rejected because concurrency limit has been reached."""

    def __init__(
        self,
        message: str,
        *,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message, code="CONCURRENCY_LIMIT_EXCEEDED", details=details)


class EnvironmentError(ExecutionError):
    """Errors in workspace environment or command execution."""

    def __init__(
        self,
        message: str,
        *,
        code: str = "ENVIRONMENT_ERROR",
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message, code=code, details=details)


class CommandTimeoutError(EnvironmentError):
    """Subprocess execution exceeded its allocated time limit."""

    def __init__(
        self,
        message: str,
        *,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message, code="COMMAND_TIMEOUT", details=details)


class SecurityViolationError(EnvironmentError):
    """A command or path violated security/confinement rules."""

    def __init__(
        self,
        message: str,
        *,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message, code="SECURITY_VIOLATION", details=details)


class EvaluationError(ExecutionError):
    """Errors during deterministic evaluation or verification."""

    def __init__(
        self,
        message: str,
        *,
        code: str = "EVALUATION_ERROR",
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message, code=code, details=details)


class LoopError(ExecutionError):
    """Errors in engineering loop control flow."""

    def __init__(
        self,
        message: str,
        *,
        code: str = "LOOP_ERROR",
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message, code=code, details=details)


class LoopIterationLimitExceededError(LoopError):
    """Loop exceeded max allowed iterations without passing evaluation."""

    def __init__(
        self,
        message: str,
        *,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message, code="LOOP_ITERATION_LIMIT_EXCEEDED", details=details)


class LoopTimeoutError(LoopError):
    """Loop exceeded its total wall-clock time budget."""

    def __init__(
        self,
        message: str,
        *,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message, code="LOOP_TIMEOUT", details=details)


class ArtifactError(ExecutionError):
    """Errors during artifact capture, storage, or provenance registration."""

    def __init__(
        self,
        message: str,
        *,
        code: str = "ARTIFACT_ERROR",
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message, code=code, details=details)


class GovernanceError(ExecutionError):
    """Errors during HITL governance evaluation or approval gating."""

    def __init__(
        self,
        message: str,
        *,
        code: str = "GOVERNANCE_ERROR",
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message, code=code, details=details)


class GovernanceApprovalRequired(GovernanceError):
    """Execution paused at an HITL governance gate before a consequential action."""

    def __init__(
        self,
        message: str,
        *,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message, code="GOVERNANCE_APPROVAL_REQUIRED", details=details)


# --- Context Engineering (ADR-003) ------------------------------------------
# Gate 2 §9. The design rule is "fatal iff correctness is at risk": optional
# context degrades, mandatory context fails loudly. These errors are the loud path.


class ContextEngineeringError(ExecutionError):
    """Root error for Context Engineering failures."""

    def __init__(
        self,
        message: str,
        *,
        code: str = "CONTEXT_ENGINEERING_ERROR",
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message, code=code, details=details)


class InvalidContextItemError(ContextEngineeringError):
    """A context item was malformed and could not be represented."""

    def __init__(
        self,
        message: str,
        *,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message, code="INVALID_CONTEXT_ITEM", details=details)


class MissingProvenanceError(ContextEngineeringError):
    """A mandatory context item lacked attributable provenance."""

    def __init__(
        self,
        message: str,
        *,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message, code="MISSING_PROVENANCE", details=details)


class UnresolvableDependencyError(ContextEngineeringError):
    """A mandatory item referenced a dependency that could not be resolved."""

    def __init__(
        self,
        message: str,
        *,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message, code="UNRESOLVABLE_DEPENDENCY", details=details)


class InvalidBudgetError(ContextEngineeringError):
    """A context budget was constructed with inconsistent or negative capacity."""

    def __init__(
        self,
        message: str,
        *,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message, code="INVALID_CONTEXT_BUDGET", details=details)


class MandatoryContextOverflowError(ContextEngineeringError):
    """Mandatory context does not fit the available window.

    Gate 2 §3.3 / §9: this is a HARD failure. Mandatory context is never
    truncated, never partially admitted, and never silently dropped. The caller
    must re-plan, request a larger window, or fail the task.
    """

    def __init__(
        self,
        message: str,
        *,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message, code="MANDATORY_CONTEXT_OVERFLOW", details=details)


class ContextSourceUnavailableError(ContextEngineeringError):
    """A mandatory context source was unavailable, so the operation cannot proceed."""

    def __init__(
        self,
        message: str,
        *,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message, code="CONTEXT_SOURCE_UNAVAILABLE", details=details)

