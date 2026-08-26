"""Model Router — model/provider selection only.

Implements ARCHITECTURE.md §Intelligent Model Router: the router is
responsible ONLY for selection (provider, model, capability, latency, cost,
availability, policy evaluation). It does NOT own retries or failover —
execution resilience belongs to the Execution Continuity Manager.

Selection pipeline:

1. Validate the :class:`RoutingRequest` (malformed requests fail loudly).
2. Hard-filter candidates through the Capability Registry
   (:meth:`query_models`) — availability, status, capabilities, context,
   deployment, cost ceilings, exclusions.
3. Rank survivors with the active (injectable) :class:`RoutingPolicy`.
4. Return a :class:`RoutingDecision` carrying the selected candidate, ALL
   ranked alternatives (the failover order) and a human-readable rationale.

Decisions are recorded in a bounded, thread-safe decision log for
observability. Routing never executes anything.
"""

from __future__ import annotations

import threading
import uuid
from collections import deque
from datetime import datetime, timezone
from typing import Any

from pydantic import Field

from autoforge_models.base import AutoForgeBaseModel

from autoforge_ai_infrastructure.errors import (
    MalformedRoutingRequestError,
    NoEligibleModelError,
    UnsupportedCapabilityError,
)
from autoforge_ai_infrastructure.interfaces import CapabilityRegistryPort, RoutingPolicy
from autoforge_ai_infrastructure.metadata import (
    LOCAL_EXECUTABLE_MODES,
    ModelMetadata,
    ModelQuery,
    ProviderMetadata,
    RoutingRequest,
)
from autoforge_ai_infrastructure.policies import LocalFirstRoutingPolicy


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class CandidateScore(AutoForgeBaseModel):
    """One ranked routing candidate."""

    rank: int = Field(..., ge=1)
    score: float = Field(...)
    model: ModelMetadata = Field(...)
    provider: ProviderMetadata | None = Field(default=None)

    @property
    def estimated_cost(self) -> float:
        """Reference-workload cost; unknown cost counts as free."""
        estimate = self.model.cost.estimate()
        return 0.0 if estimate is None else estimate


class RoutingDecision(AutoForgeBaseModel):
    """Outcome of one routing decision."""

    decision_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    policy_name: str = Field(...)
    selected: CandidateScore = Field(...)
    #: Ranked fallback candidates (excludes ``selected``). This IS the
    #: failover order consumed by the Execution Continuity Manager.
    alternatives: list[CandidateScore] = Field(default_factory=list)
    rationale: str = Field(...)
    decided_at: datetime = Field(default_factory=_utc_now)

    @property
    def all_candidates(self) -> list[CandidateScore]:
        """Selected candidate followed by alternatives, in failover order."""
        return [self.selected, *self.alternatives]


def _validate_request(request: RoutingRequest) -> None:
    """Fail loudly on contract violations (never guess an intent)."""
    problems: list[str] = []
    if not request.required_capabilities and request.min_context_window_tokens is None:
        # Defensive: the pydantic validator should already catch this.
        problems.append("request requires neither capabilities nor context size")
    if problems:
        raise MalformedRoutingRequestError(
            "Malformed routing request: " + "; ".join(problems),
            details={"problems": problems},
        )


class ModelRouterService:
    """Selects provider/model candidates from registry metadata.

    Selection only — never executes, never retries, never fails over.
    """

    def __init__(
        self,
        registry: CapabilityRegistryPort,
        default_policy: RoutingPolicy | None = None,
        *,
        decision_log_size: int = 256,
        clock: Any = None,
    ) -> None:
        self._registry = registry
        self._default_policy = default_policy or LocalFirstRoutingPolicy()
        self._decision_log: deque[RoutingDecision] = deque(
            maxlen=max(1, decision_log_size)
        )
        self._lock = threading.RLock()
        self._clock = clock or _utc_now

    # -- routing -------------------------------------------------------------

    def route(
        self,
        request: RoutingRequest,
        policy: RoutingPolicy | None = None,
    ) -> RoutingDecision:
        """Select the best candidate for ``request`` under ``policy``.

        Raises:
            MalformedRoutingRequestError: contract violation.
            UnsupportedCapabilityError: no registered model at all declares a
                requested capability.
            NoEligibleModelError: capable models exist but none satisfies the
                hard constraints (availability, deployment, cost, context).
        """
        _validate_request(request)
        active_policy = policy or self._default_policy

        query_fields = {
            "required_capabilities",
            "min_context_window_tokens",
            "excluded_provider_ids",
            "excluded_model_ids",
            "max_input_cost_per_million_tokens",
            "max_output_cost_per_million_tokens",
        }
        query = ModelQuery(
            **{
                **request.model_dump(include=query_fields),
                "allowed_deployment_modes": request.effective_allowed_deployment_modes(),
            }
        )
        eligible_models = self._registry.query_models(query)

        if not eligible_models:
            self._raise_selection_failure(request)

        ranked = self._rank(eligible_models, request, active_policy)

        selected = ranked[0]
        alternatives = ranked[1:]
        rationale = (
            f"policy={active_policy.name}; "
            f"capabilities={sorted(request.required_capabilities)}; "
            f"selected={selected.model.model_id} "
            f"(provider={selected.model.provider_id}, "
            f"deployments={sorted(m.value for m in selected.model.deployment_modes)}, "
            f"score={selected.score:.4f}); "
            f"candidates_considered={len(ranked)}"
        )
        decision = RoutingDecision(
            policy_name=active_policy.name,
            selected=selected,
            alternatives=alternatives,
            rationale=rationale,
        )
        with self._lock:
            self._decision_log.append(decision)
        return decision

    def route_excluding_providers(
        self,
        request: RoutingRequest,
        excluded_provider_ids: frozenset[str] | set[str],
        policy: RoutingPolicy | None = None,
    ) -> RoutingDecision:
        """Provider switching: re-route away from excluded providers."""
        merged = RoutingRequest(
            **{
                **request.model_dump(),
                "excluded_provider_ids": (
                    frozenset(request.excluded_provider_ids)
                    | frozenset(excluded_provider_ids)
                ),
            }
        )
        return self.route(merged, policy)

    # -- internals -----------------------------------------------------------

    def _rank(
        self,
        models: list[ModelMetadata],
        request: RoutingRequest,
        policy: RoutingPolicy,
    ) -> list[CandidateScore]:
        scored: list[CandidateScore] = []
        for model in models:
            provider = self._registry.get_provider(model.provider_id)
            score = policy.score(model, provider, request)
            scored.append(
                CandidateScore(rank=1, score=score, model=model, provider=provider)
            )
        # Deterministic total order: score desc, cost asc, id asc.
        scored.sort(key=lambda c: (-c.score, c.estimated_cost, c.model.model_id))
        return [
            CandidateScore(
                rank=index + 1,
                score=candidate.score,
                model=candidate.model,
                provider=candidate.provider,
            )
            for index, candidate in enumerate(scored)
        ]

    def _raise_selection_failure(self, request: RoutingRequest) -> None:
        """Distinguish 'capability nobody has' from 'capable but ineligible'."""
        for capability in sorted(request.required_capabilities):
            if not self._registry.models_with_capability(capability):
                raise UnsupportedCapabilityError(
                    f"No registered model provides capability '{capability}'",
                    details={"capability": capability},
                )
        raise NoEligibleModelError(
            "Registered models match the requested capabilities but none "
            "satisfies the hard constraints",
            details={
                "required_capabilities": sorted(request.required_capabilities),
                "min_context_window_tokens": request.min_context_window_tokens,
                "allowed_deployment_modes": (
                    sorted(m.value for m in request.allowed_deployment_modes)
                    if request.allowed_deployment_modes is not None
                    else None
                ),
                "offline_only": request.offline_only,
                "excluded_providers": sorted(request.excluded_provider_ids),
            },
        )

    # -- observability -------------------------------------------------------

    def decision_log(self) -> list[RoutingDecision]:
        """Recent decisions, oldest first (bounded)."""
        with self._lock:
            return list(self._decision_log)

    @property
    def default_policy_name(self) -> str:
        return self._default_policy.name
