"""Tests for routing policies (deterministic scoring)."""

from __future__ import annotations

from autoforge_ai_infrastructure.metadata import (
    CostSpec,
    DeploymentMode,
    LatencyProfile,
    ModelMetadata,
    ProviderMetadata,
    ProviderStatus,
    ProviderType,
    RoutingRequest,
)
from autoforge_ai_infrastructure.policies import (
    AvailabilityFirstRoutingPolicy,
    CapabilityFirstRoutingPolicy,
    CostOptimizingRoutingPolicy,
    LatencySensitiveRoutingPolicy,
    LocalFirstRoutingPolicy,
    QualityFirstRoutingPolicy,
)


def _model(
    mid: str,
    *,
    deployment: DeploymentMode,
    cost: CostSpec | None = None,
    latency: LatencyProfile | None = None,
    tier: int = 2,
    reliability: float = 1.0,
    capabilities: set[str] | None = None,
) -> ModelMetadata:
    return ModelMetadata(
        model_id=mid,
        display_name=mid,
        provider_id=mid,
        context_window_tokens=8192,
        capabilities=frozenset(capabilities or {"text_generation"}),
        deployment_modes=frozenset({deployment}),
        cost=cost or CostSpec(),
        latency=latency or LatencyProfile(),
        quality_tier=tier,
        reliability=reliability,
    )


def _provider(pid: str, status: ProviderStatus = ProviderStatus.AVAILABLE) -> ProviderMetadata:
    return ProviderMetadata(
        provider_id=pid,
        display_name=pid,
        provider_type=ProviderType.CLOUD,
        status=status,
        deployment_modes=frozenset({DeploymentMode.CLOUD}),
    )


def _req() -> RoutingRequest:
    return RoutingRequest(required_capabilities=frozenset({"text_generation"}))


def test_local_first_prefers_local_over_cloud():
    local = _model("m", deployment=DeploymentMode.LOCAL)
    cloud = _model("c", deployment=DeploymentMode.CLOUD)
    policy = LocalFirstRoutingPolicy()
    req = _req()
    assert policy.score(local, None, req) > policy.score(cloud, None, req)


def test_local_first_hybrid_beats_pure_cloud():
    hybrid = _model("h", deployment=DeploymentMode.HYBRID)
    cloud = _model("c", deployment=DeploymentMode.CLOUD)
    req = _req()
    policy = LocalFirstRoutingPolicy()
    assert policy.score(hybrid, None, req) > policy.score(cloud, None, req)


def test_cost_optimizing_prefers_free():
    free = _model("free", deployment=DeploymentMode.CLOUD, cost=CostSpec())
    priced = _model(
        "priced",
        deployment=DeploymentMode.CLOUD,
        cost=CostSpec(
            cost_per_million_input_tokens=1.0,
            cost_per_million_output_tokens=2.0,
        ),
    )
    req = _req()
    policy = CostOptimizingRoutingPolicy()
    assert policy.score(free, None, req) > policy.score(priced, None, req)


def test_quality_first_prefers_higher_tier():
    high = _model("high", deployment=DeploymentMode.CLOUD, tier=4)
    low = _model("low", deployment=DeploymentMode.CLOUD, tier=1)
    req = _req()
    policy = QualityFirstRoutingPolicy()
    assert policy.score(high, None, req) > policy.score(low, None, req)


def test_latency_sensitive_prefers_lower_latency():
    fast = _model(
        "fast",
        deployment=DeploymentMode.LOCAL,
        latency=LatencyProfile(typical_latency_ms=100),
    )
    slow = _model(
        "slow",
        deployment=DeploymentMode.CLOUD,
        latency=LatencyProfile(typical_latency_ms=2000),
    )
    req = _req()
    policy = LatencySensitiveRoutingPolicy()
    assert policy.score(fast, None, req) > policy.score(slow, None, req)


def test_latency_sensitive_unknown_latency_loses():
    known = _model(
        "known",
        deployment=DeploymentMode.CLOUD,
        latency=LatencyProfile(typical_latency_ms=100),
    )
    unknown = _model("unknown", deployment=DeploymentMode.CLOUD, latency=LatencyProfile())
    req = _req()
    policy = LatencySensitiveRoutingPolicy()
    assert policy.score(known, None, req) > policy.score(unknown, None, req)


def test_availability_first_prefers_available_provider():
    available_model = _model("a", deployment=DeploymentMode.CLOUD)
    degraded_model = _model("d", deployment=DeploymentMode.CLOUD)
    req = _req()
    policy = AvailabilityFirstRoutingPolicy()
    available_score = policy.score(
        available_model, _provider("a", ProviderStatus.AVAILABLE), req
    )
    degraded_score = policy.score(
        degraded_model, _provider("d", ProviderStatus.DEGRADED), req
    )
    assert available_score > degraded_score


def test_capability_first_counts_matched():
    narrow = _model("narrow", deployment=DeploymentMode.CLOUD, capabilities={"text_generation"})
    broad = _model(
        "broad",
        deployment=DeploymentMode.CLOUD,
        capabilities={"text_generation", "code_generation", "reasoning"},
    )
    policy = CapabilityFirstRoutingPolicy()
    # Both satisfy the requirement; broader capability profile ranks higher.
    assert policy.score(broad, None, _req()) > policy.score(narrow, None, _req())


def test_all_policies_have_names():
    policies = [
        LocalFirstRoutingPolicy(),
        CapabilityFirstRoutingPolicy(),
        LatencySensitiveRoutingPolicy(),
        CostOptimizingRoutingPolicy(),
        AvailabilityFirstRoutingPolicy(),
        QualityFirstRoutingPolicy(),
    ]
    names = {p.name for p in policies}
    assert names == {
        "local_first",
        "capability_first",
        "latency_sensitive",
        "cost_optimizing",
        "availability_first",
        "quality_first",
    }