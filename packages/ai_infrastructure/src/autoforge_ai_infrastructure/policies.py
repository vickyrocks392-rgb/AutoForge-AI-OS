"""Explicit routing policies for the Model Router.

Every policy is a small, deterministic, injectable strategy implementing
:class:`autoforge_ai_infrastructure.interfaces.RoutingPolicy`. No universal
strategy is hardcoded: callers choose, compose or subclass.

All scores are pure functions of ``(model, provider, request)`` — identical
inputs always yield identical outputs, which keeps routing reproducible and
unit-testable. The router breaks score ties deterministically by estimated
cost then model id.
"""

from __future__ import annotations

from typing import Any

from autoforge_ai_infrastructure.metadata import (
    DeploymentMode,
    LOCAL_EXECUTABLE_MODES,
    ModelMetadata,
    ProviderMetadata,
    ProviderStatus,
)

#: Penalty applied when latency metadata is missing under latency-sensitive
#: selection. Large enough that unknown-latency candidates lose against any
#: candidate with declared latency, but finite so ordering stays total.
_UNKNOWN_LATENCY_PENALTY = 1_000_000.0

#: Bonus per additional matched capability beyond the required minimum.
_CAPABILITY_BREADTH_BONUS = 10.0


def _estimated_cost(model: ModelMetadata, request: Any) -> float:
    """Reference-workload cost estimate; unknown cost ranks as free."""
    estimate = model.cost.estimate(
        input_tokens=request.reference_input_tokens,
        output_tokens=request.reference_output_tokens,
    )
    return 0.0 if estimate is None else estimate


class LocalFirstRoutingPolicy:
    """Prefer local execution whenever capabilities permit.

    This encodes the platform's local-first philosophy (ARCHITECTURE.md
    §AI Execution Philosophy) and the 8 GB hardware constraint posture:
    locally executable models are strongly preferred, hybrid next, remote
    last. Cost and reliability act only as fine-grained tie-breakers within
    the same deployment class.
    """

    def __init__(self, local_bonus: float = 1000.0, hybrid_bonus: float = 500.0):
        self._local_bonus = local_bonus
        self._hybrid_bonus = hybrid_bonus

    @property
    def name(self) -> str:
        return "local_first"

    def describe(self) -> str:
        return (
            "Prefers DeploymentMode.LOCAL candidates, then HYBRID, "
            "then everything else; cheaper and more reliable candidates "
            "win ties."
        )

    def score(
        self,
        model: ModelMetadata,
        provider: ProviderMetadata | None,
        request: Any,
    ) -> float:
        if model.deployment_modes & LOCAL_EXECUTABLE_MODES:
            base = self._local_bonus
        elif DeploymentMode.HYBRID in model.deployment_modes:
            base = self._hybrid_bonus
        else:
            base = 0.0
        # Tie-breakers inside the same deployment class.
        cost_term = -_estimated_cost(model, request)
        reliability_term = model.reliability
        return base + cost_term + reliability_term


class CapabilityFirstRoutingPolicy:
    """Maximise capability coverage before anything else."""

    @property
    def name(self) -> str:
        return "capability_first"

    def describe(self) -> str:
        return "Ranks by number of matched required capabilities, then breadth."

    def score(
        self,
        model: ModelMetadata,
        provider: ProviderMetadata | None,
        request: Any,
    ) -> float:
        required = getattr(request, "required_capabilities", frozenset())
        matched_required = len(required & model.capabilities)
        breadth = len(model.capabilities)
        return (
            matched_required * 1000.0
            + breadth * _CAPABILITY_BREADTH_BONUS
            + model.quality_tier
        )


class LatencySensitiveRoutingPolicy:
    """Minimise expected latency for interactive workloads."""

    def __init__(self, unknown_penalty: float = _UNKNOWN_LATENCY_PENALTY):
        self._unknown_penalty = unknown_penalty

    @property
    def name(self) -> str:
        return "latency_sensitive"

    def describe(self) -> str:
        return "Ranks by typical latency ascending; unknown latency loses."

    def score(
        self,
        model: ModelMetadata,
        provider: ProviderMetadata | None,
        request: Any,
    ) -> float:
        latency = model.latency.typical_latency_ms
        latency_term = (
            -float(latency) if latency is not None else -self._unknown_penalty
        )
        # Reliability nudges ties; a fast-but-flaky candidate should not
        # automatically beat a marginally slower dependable one.
        return latency_term + model.reliability * 5.0


class CostOptimizingRoutingPolicy:
    """Minimise estimated monetary cost for a reference workload.

    Provider-neutral: cost comes from :class:`CostSpec` metadata only — no
    billing infrastructure is required at this stage. Unknown cost is treated
    as free, so unpriced local models naturally win.
    """

    @property
    def name(self) -> str:
        return "cost_optimizing"

    def describe(self) -> str:
        return (
            "Ranks by estimated cost for the request's reference workload "
            "ascending; unknown (unpriced) cost ranks as free."
        )

    def score(
        self,
        model: ModelMetadata,
        provider: ProviderMetadata | None,
        request: Any,
    ) -> float:
        return -_estimated_cost(model, request) + model.reliability * 0.001


class AvailabilityFirstRoutingPolicy:
    """Prefer candidates most likely to be executable right now."""

    #: Status weight table; degraded providers are usable but penalised.
    _STATUS_WEIGHT = {
        ProviderStatus.AVAILABLE: 1000.0,
        ProviderStatus.DEGRADED: 100.0,
        ProviderStatus.UNAVAILABLE: -1000.0,
    }

    @property
    def name(self) -> str:
        return "availability_first"

    def describe(self) -> str:
        return (
            "Ranks by provider status weight and model reliability; "
            "unavailable providers are filtered out before scoring."
        )

    def score(
        self,
        model: ModelMetadata,
        provider: ProviderMetadata | None,
        request: Any,
    ) -> float:
        if provider is not None:
            status_weight = self._STATUS_WEIGHT.get(provider.status, 0.0)
            rate_headroom = 1.0 if provider.is_available else 0.0
        else:
            status_weight = 0.0
            rate_headroom = 0.0
        return status_weight + model.reliability * 100.0 + rate_headroom


class QualityFirstRoutingPolicy:
    """Maximise expected output quality regardless of cost or latency."""

    @property
    def name(self) -> str:
        return "quality_first"

    def describe(self) -> str:
        return "Ranks by quality tier descending, then reliability."

    def score(
        self,
        model: ModelMetadata,
        provider: ProviderMetadata | None,
        request: Any,
    ) -> float:
        return model.quality_tier * 100.0 + model.reliability * 10.0


#: Convenience registry of the built-in policies (open set — custom policies
#: are plain ``RoutingPolicy`` implementations and need no registration).
BUILTIN_POLICIES: dict[str, type] = {
    LocalFirstRoutingPolicy().name: LocalFirstRoutingPolicy,
    CapabilityFirstRoutingPolicy().name: CapabilityFirstRoutingPolicy,
    LatencySensitiveRoutingPolicy().name: LatencySensitiveRoutingPolicy,
    CostOptimizingRoutingPolicy().name: CostOptimizingRoutingPolicy,
    AvailabilityFirstRoutingPolicy().name: AvailabilityFirstRoutingPolicy,
    QualityFirstRoutingPolicy().name: QualityFirstRoutingPolicy,
}
