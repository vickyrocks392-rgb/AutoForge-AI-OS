"""Error taxonomy for the AI Infrastructure Platform.

Every failure mode required by the Phase 7 specification has an explicit,
observable exception type. Nothing is silently swallowed: callers always
receive either a result or a typed error carrying structured ``details``.

Classification contract (:class:`autoforge_ai_infrastructure.continuity.DefaultFailureClassifier`):

    Retryable       — transient infrastructure problems (provider/model
                      unavailable, timeout, transport errors).
    Non-retryable   — deterministic problems (malformed requests,
                      unsupported capabilities) that cannot succeed on retry.
"""

from __future__ import annotations

from typing import Any


class AIInfrastructureError(Exception):
    """Base class for every AI Infrastructure Platform failure."""

    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.details: dict[str, Any] = dict(details or {})


# ---------------------------------------------------------------------------
# Registry failures
# ---------------------------------------------------------------------------


class DuplicateRegistrationError(AIInfrastructureError):
    """An entity with the same identity is already registered."""


class UnknownEntityError(AIInfrastructureError):
    """A referenced provider, model or capability is not registered."""


# ---------------------------------------------------------------------------
# Routing failures
# ---------------------------------------------------------------------------


class MalformedRoutingRequestError(AIInfrastructureError):
    """The routing request violates its own contract (non-retryable)."""


class UnsupportedCapabilityError(AIInfrastructureError):
    """No registered model provides a requested capability (non-retryable)."""


class NoEligibleModelError(AIInfrastructureError):
    """Models exist for the requested capabilities but none satisfies the
    hard constraints of the request (availability, deployment, cost...)."""


# ---------------------------------------------------------------------------
# Execution failures
# ---------------------------------------------------------------------------


class ProviderUnavailableError(AIInfrastructureError):
    """A provider cannot currently accept work (retryable)."""


class ModelUnavailableError(AIInfrastructureError):
    """A specific model cannot currently execute (retryable)."""


class ExecutorNotBoundError(ProviderUnavailableError):
    """No executor is bound to the selected provider.

    Treated as *provider unavailable* so continuity can transparently fail
    over to another candidate instead of aborting the execution.
    """


class ExecutionFailedError(AIInfrastructureError):
    """A model execution attempt failed. The original error is preserved
    as ``__cause__`` and summarised in ``details``."""


class ExecutionTimeoutError(ExecutionFailedError):
    """A model execution attempt exceeded its time budget (retryable)."""


# ---------------------------------------------------------------------------
# Continuity failures
# ---------------------------------------------------------------------------


class RetryExhaustedError(AIInfrastructureError):
    """All retry attempts for one candidate failed. Failover may still
    be possible; this error records the candidate-level exhaustion."""


class FailoverExhaustedError(AIInfrastructureError):
    """Every routed candidate (including all fallbacks) was exhausted.
    The full attempt history is attached for observability."""

    def __init__(
        self,
        message: str,
        *,
        history: list[dict[str, Any]] | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message, details=details)
        self.history: list[dict[str, Any]] = list(history or [])


class CheckpointRecoveryError(AIInfrastructureError):
    """Checkpoint recovery through the Runtime boundary failed."""
