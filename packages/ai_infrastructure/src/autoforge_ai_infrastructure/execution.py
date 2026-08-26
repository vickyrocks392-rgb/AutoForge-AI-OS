"""Provider-neutral model execution boundary.

This module is the seam between the platform and real AI providers:

- :class:`ExecutionRequest` / :class:`ExecutionResult` — transport-agnostic
  execution contracts.
- :class:`ExecutionTarget` — immutable binding of a routed model + provider.
- :class:`ModelExecutor` (from ``interfaces``) — the protocol real provider
  adapters implement. **No concrete provider adapter exists in Phase 7**;
  deterministic test doubles are used behind the real protocol instead
  (FUTURE PROVIDER INTEGRATION).
- :class:`ExecutorRegistry` — binds providers to executors; injected into
  the Execution Continuity Manager.
- :class:`RoutedModelExecutor` — convenience facade that routes then executes
  once, with NO resilience behaviour (continuity owns that).
"""

from __future__ import annotations

import asyncio
import time
import uuid
from datetime import datetime, timezone
from typing import Any

from pydantic import Field

from autoforge_models.base import AutoForgeBaseModel

from autoforge_ai_infrastructure.errors import (
    ExecutionTimeoutError,
    ExecutorNotBoundError,
)
from autoforge_ai_infrastructure.interfaces import ModelExecutor
from autoforge_ai_infrastructure.metadata import RoutingRequest
from autoforge_ai_infrastructure.router import CandidateScore, ModelRouterService


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class ExecutionRequest(AutoForgeBaseModel):
    """A unit of model work, independent of any provider's wire format."""

    execution_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    #: Provider-agnostic payload: prompt/messages/tool definitions/etc.
    payload: dict[str, Any] = Field(default_factory=dict)
    #: Sampling/generation parameters (temperature, max_tokens...).
    parameters: dict[str, Any] = Field(default_factory=dict)
    #: Optional per-attempt wall-clock budget in seconds.
    timeout_seconds: float | None = Field(default=None, gt=0.0)


class ExecutionTarget(AutoForgeBaseModel):
    """Immutable binding of one routing candidate."""

    model_id: str = Field(..., min_length=1)
    provider_id: str = Field(..., min_length=1)

    @classmethod
    def from_candidate(cls, candidate: CandidateScore) -> "ExecutionTarget":
        return cls(
            model_id=candidate.model.model_id,
            provider_id=candidate.model.provider_id,
        )


class ExecutionResult(AutoForgeBaseModel):
    """Outcome of a successful model execution attempt chain."""

    execution_id: uuid.UUID = Field(...)
    output: dict[str, Any] = Field(default_factory=dict)
    model_id: str = Field(..., min_length=1)
    provider_id: str = Field(..., min_length=1)
    attempts: int = Field(..., ge=1)
    failovers: int = Field(..., ge=0)
    latency_ms: float | None = Field(default=None, ge=0.0)
    completed_at: datetime = Field(default_factory=_utc_now)


class ExecutorRegistry:
    """Binds provider ids to :class:`ModelExecutor` implementations.

    The registry is intentionally dumb plumbing: it knows nothing about
    routing or resilience. Binding an executor for a provider that is not
    registered in the Capability Registry is allowed (executors may exist
    ahead of metadata registration), but executing against an unbound
    provider raises :class:`ExecutorNotBoundError`, which continuity treats
    as *provider unavailable* and fails over.
    """

    def __init__(self) -> None:
        self._executors: dict[str, ModelExecutor] = {}

    def bind(self, provider_id: str, executor: ModelExecutor) -> None:
        if not callable(getattr(executor, "execute", None)):
            raise TypeError(
                f"executor for provider '{provider_id}' does not satisfy "
                "the ModelExecutor protocol"
            )
        self._executors[provider_id] = executor

    def unbind(self, provider_id: str) -> None:
        self._executors.pop(provider_id, None)

    def get(self, provider_id: str) -> ModelExecutor:
        executor = self._executors.get(provider_id)
        if executor is None:
            raise ExecutorNotBoundError(
                f"No executor bound for provider '{provider_id}'",
                details={"provider_id": provider_id},
            )
        return executor

    def bound_providers(self) -> list[str]:
        return sorted(self._executors)


async def execute_attempt(
    executors: ExecutorRegistry,
    request: ExecutionRequest,
    target: ExecutionTarget,
) -> ExecutionResult:
    """Run exactly ONE attempt against ``target``.

    Raises:
        ExecutorNotBoundError: provider has no bound executor.
        ExecutionTimeoutError: attempt exceeded its time budget.
        Exception: whatever the executor raised (wrapped by continuity).
    """
    executor = executors.get(target.provider_id)
    started = time.perf_counter()
    try:
        if request.timeout_seconds is not None:
            output = await asyncio.wait_for(
                executor.execute(request, target),
                timeout=request.timeout_seconds,
            )
        else:
            output = await executor.execute(request, target)
    except asyncio.TimeoutError as exc:
        raise ExecutionTimeoutError(
            f"Execution against '{target.model_id}' exceeded "
            f"{request.timeout_seconds}s budget",
            details={
                "model_id": target.model_id,
                "provider_id": target.provider_id,
                "timeout_seconds": request.timeout_seconds,
            },
        ) from exc
    latency_ms = (time.perf_counter() - started) * 1000.0
    return ExecutionResult(
        execution_id=request.execution_id,
        output=dict(output or {}),
        model_id=target.model_id,
        provider_id=target.provider_id,
        attempts=1,
        failovers=0,
        latency_ms=latency_ms,
    )


class RoutedModelExecutor:
    """Route-then-execute-once facade WITHOUT resilience behaviour.

    Continuity (retry/failover/checkpoints) lives in
    :mod:`autoforge_ai_infrastructure.continuity`; this class exists for
    callers that explicitly want a single, unguarded attempt.
    """

    def __init__(
        self,
        router: ModelRouterService,
        executors: ExecutorRegistry,
    ) -> None:
        self._router = router
        self._executors = executors

    async def execute(
        self,
        request: ExecutionRequest,
        routing_request: RoutingRequest,
        policy: Any = None,
    ) -> ExecutionResult:
        decision = self._router.route(routing_request, policy)
        candidate: CandidateScore = decision.selected
        target = ExecutionTarget.from_candidate(candidate)
        return await execute_attempt(self._executors, request, target)
