"""Tests for the Model Router (selection only)."""

from __future__ import annotations

import pytest

from autoforge_ai_infrastructure.errors import (
    MalformedRoutingRequestError,
    NoEligibleModelError,
    UnsupportedCapabilityError,
)
from autoforge_ai_infrastructure.metadata import (
    CapabilityIds,
    DeploymentMode,
    ProviderStatus,
    RoutingRequest,
)
from autoforge_ai_infrastructure.policies import (
    CapabilityFirstRoutingPolicy,
    CostOptimizingRoutingPolicy,
    LocalFirstRoutingPolicy,
)
from autoforge_ai_infrastructure.router import ModelRouterService


def _code_req() -> RoutingRequest:
    return RoutingRequest(
        required_capabilities=frozenset({CapabilityIds.CODE_GENERATION})
    )


def test_local_first_selects_local_model(router):
    decision = router.route(_code_req(), LocalFirstRoutingPolicy())
    assert decision.selected.model.model_id == "reference-local-mini-q4"
    assert decision.selected.model.is_locally_executable is True


def test_capability_first_selects_cloud_capable_model(router):
    # Cloud model exposes reasoning + long context that local lacks.
    decision = router.route(_code_req(), CapabilityFirstRoutingPolicy())
    assert decision.selected.model.model_id == "reference-cloud-large-v2"


def test_failover_order_in_alternatives(router):
    decision = router.route(_code_req(), LocalFirstRoutingPolicy())
    # Local is selected; cloud is the ranked fallback (failover order).
    selected = decision.selected.model.model_id
    alternatives = [c.model.model_id for c in decision.alternatives]
    assert selected == "reference-local-mini-q4"
    assert "reference-cloud-large-v2" in alternatives
    assert alternatives == ["reference-cloud-large-v2"]


def test_offline_mode_never_selects_cloud(router):
    request = RoutingRequest(
        required_capabilities=frozenset({CapabilityIds.CODE_GENERATION}),
        offline_only=True,
    )
    decision = router.route(request, LocalFirstRoutingPolicy())
    assert decision.selected.model.deployment_modes == frozenset(
        {DeploymentMode.LOCAL}
    )


def test_offline_mode_no_local_capable_model_raises(registry, router):
    # Only the cloud model supports reasoning; offline_only + reasoning must fail.
    request = RoutingRequest(
        required_capabilities=frozenset({CapabilityIds.REASONING}),
        offline_only=True,
    )
    with pytest.raises(NoEligibleModelError):
        router.route(request)


def test_unsupported_capability_raises(router):
    request = RoutingRequest(required_capabilities=frozenset({"image_generation"}))
    with pytest.raises(UnsupportedCapabilityError):
        router.route(request)


def test_unavailable_model_handling(registry, router):
    # Take the only candidate for a capability offline.
    registry.set_provider_status(
        "reference-local", ProviderStatus.UNAVAILABLE, reason="test outage"
    )
    # local-mini is the only code_generation local model; but cloud also has it.
    # offline: cloud is not eligible, so selection fails.
    request = RoutingRequest(
        required_capabilities=frozenset({CapabilityIds.CODE_GENERATION}),
        offline_only=True,
    )
    with pytest.raises(NoEligibleModelError):
        router.route(request)


def test_provider_switching_excludes_provider(router):
    # Local-first normally picks local-mini; excluding local forces cloud.
    decision = router.route_excluding_providers(
        _code_req(), frozenset({"reference-local"}), LocalFirstRoutingPolicy()
    )
    assert decision.selected.model.provider_id == "reference-cloud"
    assert decision.selected.model.model_id == "reference-cloud-large-v2"


def test_cost_optimizing_selects_free_local(router):
    decision = router.route(_code_req(), CostOptimizingRoutingPolicy())
    assert decision.selected.model.model_id == "reference-local-mini-q4"


def test_malformed_request_raises(router):
    # Neither capabilities nor context supplied → rejected at construction.
    with pytest.raises(ValueError):
        RoutingRequest(
            required_capabilities=frozenset(),
            min_context_window_tokens=None,
        )


def test_decision_log_records(router):
    router.route(_code_req())
    router.route(_code_req())
    log = router.decision_log()
    assert len(log) == 2
    assert all(decision.policy_name for decision in log)


def test_router_never_executes(router):
    """Routing returns a decision; it must not touch an executor."""
    decision = router.route(_code_req())
    assert decision.selected.model.model_id
    # No executor is bound anywhere; routing still works → pure selection.