"""Tests for AI infrastructure metadata value objects."""

from __future__ import annotations

import pytest

from autoforge_ai_infrastructure.metadata import (
    CostSpec,
    DeploymentMode,
    ModelMetadata,
    ModelQuery,
    ModelStatus,
    Modality,
    ProviderMetadata,
    ProviderStatus,
    ProviderType,
    ResourceConstraints,
    RoutingRequest,
)


def test_cost_spec_estimate_known():
    cost = CostSpec(
        cost_per_million_input_tokens=10.0,
        cost_per_million_output_tokens=20.0,
    )
    # 1M input + 1M output = $30.00 ; 1k/1k = $0.03
    assert cost.estimate() == pytest.approx(0.03)
    assert cost.is_known is True


def test_cost_spec_unknown_is_free():
    assert CostSpec().is_known is False
    assert CostSpec().estimate() is None


def test_deployment_mode_local_classification():
    model = ModelMetadata(
        model_id="m1",
        display_name="M1",
        provider_id="p1",
        context_window_tokens=4096,
        deployment_modes=frozenset({DeploymentMode.LOCAL}),
    )
    assert model.is_locally_executable is True


def test_provider_local_capable():
    provider = ProviderMetadata(
        provider_id="p",
        display_name="P",
        provider_type=ProviderType.LOCAL_RUNTIME,
        deployment_modes=frozenset({DeploymentMode.LOCAL}),
    )
    assert provider.is_local_capable is True
    assert provider.is_available is True


def test_provider_unavailable_transition():
    provider = ProviderMetadata(
        provider_id="p",
        display_name="P",
        provider_type=ProviderType.CLOUD,
    )
    updated = provider.model_copy(
        update={"status": ProviderStatus.UNAVAILABLE}
    )
    assert updated.is_available is False


def test_resource_constraints_represent_8gb_laptop():
    rc = ResourceConstraints(
        min_memory_mb=2048,
        recommended_memory_mb=4096,
        requires_gpu=False,
    )
    assert rc.requires_gpu is False
    assert rc.recommended_memory_mb == 4096


def test_routing_request_requires_signal():
    with pytest.raises(ValueError):
        RoutingRequest(required_capabilities=frozenset(), min_context_window_tokens=None)


def test_routing_request_capability_only_ok():
    req = RoutingRequest(required_capabilities=frozenset({"code_generation"}))
    assert req.min_context_window_tokens is None


def test_routing_request_offline_only_restricts_to_local():
    req = RoutingRequest(
        required_capabilities=frozenset({"text_generation"}),
        offline_only=True,
    )
    assert req.effective_allowed_deployment_modes() == frozenset(
        {DeploymentMode.LOCAL}
    )


def test_attempt_record_summary_is_json_safe():
    from autoforge_ai_infrastructure.metadata import AttemptRecord
    import uuid

    rec = AttemptRecord(
        execution_id=uuid.uuid4(),
        model_id="m",
        provider_id="p",
        attempt_number=1,
        error=ValueError("boom"),
        classification="retryable",
        succeeded=False,
        followed_by_failover=True,
    )
    summary = rec.summary()
    assert summary["error_type"] == "ValueError"
    assert summary["error_message"] == "boom"
    assert summary["succeeded"] is False
    assert summary["followed_by_failover"] is True


def test_model_supports_all_capabilities():
    model = ModelMetadata(
        model_id="m",
        display_name="M",
        provider_id="p",
        context_window_tokens=4096,
        capabilities=frozenset({"a", "b", "c"}),
    )
    assert model.supports_all(frozenset({"a", "b"})) is True
    assert model.supports_all(frozenset({"a", "z"})) is False