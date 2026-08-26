"""Execution Continuity Manager — execution resilience.

Responsibilities (ARCHITECTURE.md §Execution Continuity Manager):

- **Retry** — configurable attempts per candidate with failure
  classification and deterministic exponential backoff.
- **Failover** — walk the router's ranked candidate chain when a candidate
  is exhausted; preserve the execution request/context across transitions;
  record every transition; never silently swallow failures.
- **Context preservation** — a :class:`PreservedExecutionContext` carries
  exactly the state needed to RESUME an execution (payload, routing intent,
  attempt history, last failure). It does NOT assemble model context — that
  remains the Context Engineering contract's responsibility (ADR-003); this
  is execution-state preservation only.
- **Checkpoint recovery** — delegated to the injected
  :class:`RuntimeCheckpointPort` (the Runtime State Manager boundary).
  No second checkpoint system exists here.

Events use canonical vocabulary via :class:`AIInfrastructureEvents`.
Backoff sleeps go through an injectable async ``sleeper`` so tests stay
deterministic and fast.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any, AsyncIterable, Awaitable, Callable

from pydantic import Field

from autoforge_models.base import AutoForgeBaseModel

from autoforge_ai_infrastructure.errors import (
    AIInfrastructureError,
    CheckpointRecoveryError,
    ExecutionFailedError,
    ExecutionTimeoutError,
    FailoverExhaustedError,
    MalformedRoutingRequestError,
    ModelUnavailableError,
    ProviderUnavailableError,
    RetryExhaustedError,
    UnsupportedCapabilityError,
)
from autoforge_ai_infrastructure.events import AIInfrastructureEvents
from autoforge_ai_infrastructure.execution import (
    ExecutionRequest,
    ExecutionResult,
    ExecutionTarget,
    ExecutorRegistry,
    execute_attempt,
)
from autoforge_ai_infrastructure.interfaces import (
    CanonicalEventSink,
    FailureClassification,
    FailureClassifier,
    RoutingPolicy,
)
from autoforge_ai_infrastructure.metadata import AttemptRecord, RoutingRequest
from autoforge_ai_infrastructure.router import CandidateScore, ModelRouterService


class RetryPolicy(AutoForgeBaseModel):
    """Deterministic retry configuration (per candidate)."""

    max_attempts: int = Field(default=3, ge=1, le=100)
    backoff_base_seconds: float = Field(default=0.05, ge=0.0)
    backoff_multiplier: float = Field(default=2.0, ge=1.0)
    max_backoff_seconds: float = Field(default=1.0, ge=0.0)

    def backoff_for(self, failed_attempt: int) -> float:
        """Exponential backoff after ``failed_attempt`` (1-based), clamped."""
        raw = self.backoff_base_seconds * (
            self.backoff_multiplier ** max(0, failed_attempt - 1)
        )
        return min(raw, self.max_backoff_seconds)


class DefaultFailureClassifier(FailureClassifier):
    """Explicit retryable/non-retryable taxonomy.

    Retryable (transient): provider/model unavailable, unbound executor
    (treated as provider unavailable), timeouts, wrapped execution failures,
    transport-level OSError/ConnectionError, unknown exceptions (assumed
    transient but still capped by ``max_attempts``).

    Non-retryable (deterministic): malformed routing requests and
    unsupported capabilities — retrying can never succeed. ``BaseException``
    subclasses that are not ``Exception`` (e.g. ``KeyboardInterrupt``) are
    never classified for retry.
    """

    def classify(self, error: BaseException) -> FailureClassification:
        if not isinstance(error, Exception):
            return FailureClassification.NON_RETRYABLE
        if isinstance(
            error,
            (MalformedRoutingRequestError, UnsupportedCapabilityError),
        ):
            return FailureClassification.NON_RETRYABLE
        if isinstance(
            error,
            (
                ProviderUnavailableError,
                ModelUnavailableError,
                ExecutionTimeoutError,
                ExecutionFailedError,
                RetryExhaustedError,
                OSError,
                ConnectionError,
                TimeoutError,
                asyncio.TimeoutError,
            ),
        ):
            return FailureClassification.RETRYABLE
        # Unknown exceptions are assumed transient but attempts stay capped.
        return FailureClassification.RETRYABLE


class PreservedExecutionContext(AutoForgeBaseModel):
    """Execution state preserved across retries and failovers.

    NOT a competing context engine: this carries only what resuming an
    execution requires. Model-facing context assembly stays with Context
    Engineering (ADR-003).
    """

    execution_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    payload: dict[str, Any] = Field(default_factory=dict)
    parameters: dict[str, Any] = Field(default_factory=dict)
    timeout_seconds: float | None = Field(default=None, gt=0.0)
    routing_request: RoutingRequest = Field(...)
    policy_name: str | None = Field(default=None)
    project_id: uuid.UUID | None = Field(default=None)
    checkpoint_id: uuid.UUID | None = Field(default=None)
    candidates_model_ids: list[str] = Field(default_factory=list)
    next_candidate_index: int = Field(default=0, ge=0)
    attempts_so_far: int = Field(default=0, ge=0)
    failovers_so_far: int = Field(default=0, ge=0)
    history: list[dict[str, Any]] = Field(default_factory=list)

    #: Mutable by design: continuity progressively preserves state here.
    model_config = {"extra": "forbid", "populate_by_name": True, "frozen": False}

    def record(self, entry: dict[str, Any]) -> None:
        """Append an audit entry to the preserved history."""
        self.history.append(entry)


class ContinuityOutcome(AutoForgeBaseModel):
    """Summary of one completed (successful) continuity-managed execution."""

    result_model_id: str = Field(..., min_length=1)
    result_provider_id: str = Field(..., min_length=1)
    output: dict[str, Any] = Field(default_factory=dict)
    attempts: int = Field(..., ge=1)
    failovers: int = Field(..., ge=0)
    execution_id: uuid.UUID = Field(...)
    checkpoint_id: uuid.UUID | None = Field(default=None)
    provider_switches: list[dict[str, Any]] = Field(default_factory=list)


class ExecutionContinuityService:
    """The Execution Continuity Manager.

    Executes a payload against the best routed candidate; retries transient
    failures per :class:`RetryPolicy`; fails over along the router's ranked
    candidates when retries are exhausted; preserves execution context
    throughout; recovers through the Runtime checkpoint port when configured.
    """

    def __init__(
        self,
        router: ModelRouterService,
        executors: ExecutorRegistry,
        *,
        retry_policy: RetryPolicy | None = None,
        classifier: FailureClassifier | None = None,
        checkpoints: Any | None = None,
        events: AIInfrastructureEvents | None = None,
        sleeper: Callable[[float], Awaitable[None]] | None = None,
    ) -> None:
        self._router = router
        self._executors = executors
        self._retry_policy = retry_policy or RetryPolicy()
        self._classifier = classifier or DefaultFailureClassifier()
        self._checkpoints = checkpoints
        self._events = events or AIInfrastructureEvents(sink=None)
        self._sleep = sleeper or asyncio.sleep
        self._contexts: dict[uuid.UUID, PreservedExecutionContext] = {}

    # -- public API ----------------------------------------------------------

    async def execute(
        self,
        payload: dict[str, Any],
        routing_request: RoutingRequest,
        *,
        parameters: dict[str, Any] | None = None,
        timeout_seconds: float | None = None,
        policy: RoutingPolicy | None = None,
        project_id: uuid.UUID | None = None,
    ) -> ExecutionResult:
        """Execute with full retry/failover resilience."""
        request = ExecutionRequest(
            payload=dict(payload),
            parameters=dict(parameters or {}),
            timeout_seconds=timeout_seconds,
        )
        decision = self._router.route(routing_request, policy)
        context = PreservedExecutionContext(
            payload=request.payload,
            parameters=request.parameters,
            timeout_seconds=request.timeout_seconds,
            routing_request=routing_request,
            policy_name=policy.name if policy else self._router.default_policy_name,
            project_id=project_id,
            candidates_model_ids=[c.model.model_id for c in decision.all_candidates],
        )

        # Checkpoint BEFORE execution through the Runtime boundary when a
        # project scope is known (durable state stays owned by the Runtime).
        if self._checkpoints is not None and project_id is not None:
            context.checkpoint_id = self._checkpoints.create_checkpoint(
                project_id,
                "automatic",
                label="ai-execution-pre",
                description="Checkpoint before continuity-managed AI execution",
                metadata={"execution_id": str(context.execution_id)},
            )

        self._contexts[context.execution_id] = context
        return await self._run_candidates(request, context, decision.all_candidates)

    async def resume(self, execution_id: uuid.UUID) -> ExecutionResult:
        """Resume a previously preserved execution from its stored context."""
        context = self.get_preserved_context(execution_id)
        if context is None:
            raise AIInfrastructureError(
                f"No preserved execution context for '{execution_id}'",
                details={"execution_id": str(execution_id)},
            )
        request = ExecutionRequest(
            execution_id=context.execution_id,
            payload=dict(context.payload),
            parameters=dict(context.parameters),
            timeout_seconds=context.timeout_seconds,
        )
        return await self._run_candidates(
            request, context, self._remaining_candidates(context)
        )

    def recover_from_checkpoint(self, project_id: uuid.UUID) -> dict[str, Any]:
        """Restore the latest Runtime checkpoint for ``project_id``.

        Uses ONLY the injected Runtime checkpoint port — never a second
        checkpoint system. Failures raise :class:`CheckpointRecoveryError`.
        """
        if self._checkpoints is None:
            raise CheckpointRecoveryError(
                "No runtime checkpoint port configured",
                details={"project_id": str(project_id)},
            )
        try:
            history = self._checkpoints.get_checkpoint_history(project_id)
            if not history:
                raise CheckpointRecoveryError(
                    "No checkpoints exist for project",
                    details={"project_id": str(project_id)},
                )
            latest = history[-1]
            checkpoint_id = (
                getattr(latest, "checkpoint_id", None)
                or (latest["checkpoint_id"] if isinstance(latest, dict) else None)
            )
            result = self._checkpoints.restore_checkpoint(checkpoint_id, "full")
            self._events.checkpoint_restored(
                execution_id=uuid.uuid4(),
                checkpoint_id=checkpoint_id,
                project_id=project_id,
            )
            return {
                "restored": True,
                "checkpoint_id": str(checkpoint_id),
                "runtime_result": result,
            }
        except CheckpointRecoveryError:
            raise
        except Exception as exc:
            raise CheckpointRecoveryError(
                f"Checkpoint recovery failed: {exc}",
                details={
                    "project_id": str(project_id),
                    "error_type": type(exc).__name__,
                },
            ) from exc

    # -- observability -------------------------------------------------------

    def get_preserved_context(
        self, execution_id: uuid.UUID
    ) -> PreservedExecutionContext | None:
        return self._contexts.get(execution_id)

    @property
    def retry_policy(self) -> RetryPolicy:
        return self._retry_policy

    @property
    def classifier(self) -> FailureClassifier:
        return self._classifier

    # -- internals -----------------------------------------------------------

    def _remaining_candidates(
        self, context: PreservedExecutionContext
    ) -> list[CandidateScore]:
        """Rebuild the remaining candidate chain from preserved context."""
        candidates: list[CandidateScore] = []
        for index, model_id in enumerate(context.candidates_model_ids):
            if index < context.next_candidate_index:
                continue
            model = self._router._registry.get_model(model_id)
            provider = (
                self._router._registry.get_provider(model.provider_id)
                if model is not None
                else None
            )
            if model is None:
                continue
            candidates.append(
                CandidateScore(rank=index + 1, score=0.0, model=model, provider=provider)
            )
        return candidates

    async def _run_candidates(
        self,
        request: ExecutionRequest,
        context: PreservedExecutionContext,
        candidates: list[CandidateScore],
    ) -> ExecutionResult:
        """Attempt candidates in order with per-candidate retry budgets.

        Failure semantics (never silently swallowed):

        - Non-retryable failure → stop retrying THIS candidate immediately;
          fail over to the next candidate.
        - Retryable failure → backoff + retry up to
          ``RetryPolicy.max_attempts``; exhaustion raises internally as
          :class:`RetryExhaustedError`, recorded, then triggers FAILOVER.
        - All candidates exhausted → :class:`FailoverExhaustedError` carrying
          the full attempt history.
        """
        provider_switches: list[dict[str, Any]] = []
        previous_provider: str | None = None

        for candidate_index, candidate in enumerate(candidates):
            target_provider = candidate.model.provider_id
            if previous_provider is not None and previous_provider != target_provider:
                switch = {
                    "from_provider": previous_provider,
                    "to_provider": target_provider,
                    "to_model": candidate.model.model_id,
                }
                provider_switches.append(switch)
                context.failovers_so_far += 1
                self._events.service_degraded(
                    execution_id=context.execution_id,
                    provider_id=previous_provider,
                    reason=f"failover to {target_provider}",
                )
                self._events.recovery_started(
                    execution_id=context.execution_id,
                    phase="failover",
                    from_provider=previous_provider,
                    to_model=candidate.model.model_id,
                )
            previous_provider = target_provider

            attempt_number = 0
            while True:
                attempt_number += 1
                context.attempts_so_far += 1
                context.next_candidate_index = candidate_index
                try:
                    target = ExecutionTarget.from_candidate(candidate)
                    result = await execute_attempt(self._executors, request, target)
                    return await self._handle_success(
                        request, context, candidate, result,
                        attempt_number, bool(provider_switches),
                    )
                except Exception as exc:
                    decision = await self._classify_failure(
                        context, candidate, exc, attempt_number
                    )
                    if decision == "retry":
                        continue
                    break  # fail over to next candidate

        # Every candidate is exhausted: surface everything, swallow nothing.
        error_message = (
            f"All {len(candidates)} routed candidate(s) exhausted for "
            f"execution '{context.execution_id}'"
        )
        self._events.recovery_failed(
            execution_id=context.execution_id,
            history_summary=list(context.history),
            error_message=error_message,
        )
        raise FailoverExhaustedError(
            error_message,
            history=list(context.history),
            details={
                "execution_id": str(context.execution_id),
                "candidates": list(context.candidates_model_ids),
                "attempts": context.attempts_so_far,
                "failovers": context.failovers_so_far,
            },
        )

    async def _handle_success(
        self,
        request: ExecutionRequest,
        context: PreservedExecutionContext,
        candidate: CandidateScore,
        result: ExecutionResult,
        attempt_number: int,
        followed_failover: bool,
    ) -> ExecutionResult:
        record = AttemptRecord(
            execution_id=context.execution_id,
            model_id=candidate.model.model_id,
            provider_id=candidate.model.provider_id,
            attempt_number=attempt_number,
            succeeded=True,
            classification="not_attempted",
            followed_by_failover=followed_failover,
        )
        context.record(record.summary())
        if context.failovers_so_far > 0 or context.attempts_so_far > 1:
            self._events.recovery_completed(
                execution_id=context.execution_id,
                model_id=result.model_id,
                provider_id=result.provider_id,
                attempts=context.attempts_so_far,
                failovers=context.failovers_so_far,
            )
        return ExecutionResult(
            execution_id=context.execution_id,
            output=result.output,
            model_id=result.model_id,
            provider_id=result.provider_id,
            attempts=context.attempts_so_far,
            failovers=context.failovers_so_far,
            latency_ms=result.latency_ms,
        )

    async def _classify_failure(
        self,
        context: PreservedExecutionContext,
        candidate: CandidateScore,
        exc: Exception,
        attempt_number: int,
    ) -> str:
        """Record a failed attempt; return ``"retry"`` or ``"failover"``."""
        classification = self._classifier.classify(exc)
        record = AttemptRecord(
            execution_id=context.execution_id,
            model_id=candidate.model.model_id,
            provider_id=candidate.model.provider_id,
            attempt_number=attempt_number,
            error=exc,
            classification=classification.value,
            followed_by_failover=False,
        )
        context.record(record.summary())
        self._events.failure_detected(record)

        retryable = classification == FailureClassification.RETRYABLE
        will_retry = retryable and attempt_number < self._retry_policy.max_attempts

        if will_retry:
            self._events.recovery_started(
                execution_id=context.execution_id,
                phase="retry",
                from_provider=candidate.model.provider_id,
                to_model=candidate.model.model_id,
            )
            await self._sleep(self._retry_policy.backoff_for(attempt_number))
            return "retry"

        # Retry exhausted (or non-retryable): record and fail over.
        exhaustion_error = (
            exc
            if not retryable
            else RetryExhaustedError(
                f"Candidate '{candidate.model.model_id}' exhausted "
                f"{self._retry_policy.max_attempts} attempt(s)",
                details={
                    "model_id": candidate.model.model_id,
                    "provider_id": candidate.model.provider_id,
                    "last_error_type": type(exc).__name__,
                    "last_error_message": str(exc)[:512],
                },
            )
        )
        followup = AttemptRecord(
            execution_id=context.execution_id,
            model_id=candidate.model.model_id,
            provider_id=candidate.model.provider_id,
            attempt_number=attempt_number,
            error=exhaustion_error,
            classification="retryable" if retryable else "non_retryable",
            followed_by_failover=True,
        )
        context.record(followup.summary())
        return "failover"

