"""Tests for the Capability Registry."""

from __future__ import annotations

import pytest

from autoforge_ai_infrastructure.errors import (
    DuplicateRegistrationError,
    UnknownEntityError,
)
from autoforge_ai_infrastructure.metadata import (
    CapabilityMetadata,
    DeploymentMetadata,
    DeploymentMode,
    ModelMetadata,
    ModelQuery,
    ModelStatus,
    ProviderMetadata,
    ProviderStatus,
    ProviderType,
)
from autoforge_ai_infrastructure.registry import InMemoryCapabilityRegistry


@pytest.fixture
def registry() -> InMemoryCapabilityRegistry:
    return InMemoryCapabilityRegistry()


def _provider(
    pid: str = "p1", status: ProviderStatus = ProviderStatus.AVAILABLE
) -> ProviderMetadata:
    return ProviderMetadata(
        provider_id=pid,
        display_name=f"Provider {pid}",
        provider_type=ProviderType.CLOUD,
        status=status,
        deployment_modes=frozenset({DeploymentMode.CLOUD}),
    )


def _model(
    mid: str = "m1",
    pid: str = "p1",
    caps: set[str] | None = None,
    status: ModelStatus = ModelStatus.ACTIVE,
    deployment: DeploymentMode = DeploymentMode.CLOUD,
) -> ModelMetadata:
    return ModelMetadata(
        model_id=mid,
        display_name=f"Model {mid}",
        provider_id=pid,
        status=status,
        context_window_tokens=4096,
        capabilities=frozenset(caps or {"text_generation"}),
        deployment_modes=frozenset({deployment}),
    )


def _cap(cid: str = "c1") -> CapabilityMetadata:
    return CapabilityMetadata(capability_id=cid, display_name=f"Cap {cid}")


def _register_caps(registry: InMemoryCapabilityRegistry, *cap_ids: str) -> None:
    """Register capabilities so strict model registration can succeed."""
    for cid in cap_ids:
        if registry.get_capability(cid) is None:
            registry.register_capability(_cap(cid))


def _seeded_registry() -> InMemoryCapabilityRegistry:
    """A registry with providers, capabilities and two models, ready to query."""
    reg = InMemoryCapabilityRegistry()
    _register_caps(reg, "text_generation", "code_generation")
    reg.register_provider(_provider("p1"))
    reg.register_provider(_provider("p2"))
    reg.register_model(
        _model("m1", "p1", caps={"text_generation"}, deployment=DeploymentMode.CLOUD)
    )
    reg.register_model(
        _model("m2", "p2", caps={"code_generation"}, deployment=DeploymentMode.CLOUD)
    )
    return reg


def _seed(registry: InMemoryCapabilityRegistry) -> None:
    """Seed a caller-provided registry with providers+capabilities+models."""
    _register_caps(registry, "text_generation", "code_generation")
    registry.register_provider(_provider("p1"))
    registry.register_provider(_provider("p2"))
    registry.register_model(
        _model("m1", "p1", caps={"text_generation"}, deployment=DeploymentMode.CLOUD)
    )
    registry.register_model(
        _model("m2", "p2", caps={"code_generation"}, deployment=DeploymentMode.CLOUD)
    )


# ── capabilities ────────────────────────────────────────────────────────────


def test_register_and_list_capabilities(registry):
    registry.register_capability(_cap("c1"))
    assert registry.get_capability("c1") is not None
    assert [c.capability_id for c in registry.list_capabilities()] == ["c1"]


def test_duplicate_capability_rejected(registry):
    registry.register_capability(_cap("c1"))
    with pytest.raises(DuplicateRegistrationError):
        registry.register_capability(_cap("c1"))


# ── providers ───────────────────────────────────────────────────────────────


def test_register_and_get_provider(registry):
    registry.register_provider(_provider("p1"))
    assert registry.get_provider("p1").provider_id == "p1"
    assert len(registry.list_providers()) == 1


def test_duplicate_provider_rejected(registry):
    registry.register_provider(_provider("p1"))
    with pytest.raises(DuplicateRegistrationError):
        registry.register_provider(_provider("p1"))


def test_set_provider_status_records_transition(registry):
    registry.register_provider(_provider("p1"))
    updated = registry.set_provider_status(
        "p1", ProviderStatus.UNAVAILABLE, reason="outage"
    )
    assert updated.status == ProviderStatus.UNAVAILABLE
    assert updated.is_available is False
    assert updated.health["status_transitions"][-1]["reason"] == "outage"


def test_set_provider_status_unknown(registry):
    with pytest.raises(UnknownEntityError):
        registry.set_provider_status("nope", ProviderStatus.UNAVAILABLE)


# ── models ──────────────────────────────────────────────────────────────────


def test_register_model_requires_provider(registry):
    _register_caps(registry, "text_generation")
    registry.register_provider(_provider("p1"))
    registry.register_model(_model("m1", "p1"))
    assert registry.get_model("m1").model_id == "m1"


def test_register_model_missing_provider_rejected(registry):
    _register_caps(registry, "text_generation")
    with pytest.raises(UnknownEntityError):
        registry.register_model(_model("m1", "ghost"))


def test_register_model_strict_capabilities_rejects_unknown(registry):
    registry.register_provider(_provider("p1"))
    with pytest.raises(UnknownEntityError):
        registry.register_model(_model("m1", "p1", caps={"not_registered"}))


def test_register_model_non_strict_allows_unknown(registry):
    registry.register_provider(_provider("p1"))
    registry.register_model(_model("m1", "p1", caps={"not_registered"}), strict_capabilities=False)
    assert registry.get_model("m1") is not None


def test_duplicate_model_rejected(registry):
    _register_caps(registry, "text_generation")
    registry.register_provider(_provider("p1"))
    registry.register_model(_model("m1", "p1"))
    with pytest.raises(DuplicateRegistrationError):
        registry.register_model(_model("m1", "p1"))


# ── deployments ─────────────────────────────────────────────────────────────


def test_register_deployment(registry):
    _register_caps(registry, "text_generation")
    registry.register_provider(_provider("p1"))
    registry.register_model(_model("m1", "p1"))
    registry.register_deployment(
        DeploymentMetadata(model_id="m1", mode=DeploymentMode.CLOUD, environment="cloud")
    )
    deps = registry.get_deployments("m1")
    assert len(deps) == 1
    assert deps[0].mode == DeploymentMode.CLOUD


def test_register_deployment_unknown_model(registry):
    with pytest.raises(UnknownEntityError):
        registry.register_deployment(
            DeploymentMetadata(model_id="ghost", mode=DeploymentMode.CLOUD)
        )


def test_duplicate_deployment_mode_rejected(registry):
    _register_caps(registry, "text_generation")
    registry.register_provider(_provider("p1"))
    registry.register_model(_model("m1", "p1"))
    registry.register_deployment(
        DeploymentMetadata(model_id="m1", mode=DeploymentMode.CLOUD)
    )
    with pytest.raises(DuplicateRegistrationError):
        registry.register_deployment(
            DeploymentMetadata(model_id="m1", mode=DeploymentMode.CLOUD)
        )


# ── querying / filtering ────────────────────────────────────────────────────


def test_query_models_required_capability(registry):
    _seed(registry)
    models = registry.query_models(
        ModelQuery(required_capabilities=frozenset({"code_generation"}))
    )
    assert [m.model_id for m in models] == ["m2"]


def test_query_excludes_unavailable_provider(registry):
    _seed(registry)
    registry.set_provider_status("p2", ProviderStatus.UNAVAILABLE)
    models = registry.query_models(
        ModelQuery(required_capabilities=frozenset({"code_generation"}))
    )
    assert models == []


def test_query_filters_by_status(registry):
    _seed(registry)
    registry.update_model_status("m2", ModelStatus.DEPRECATED)
    models = registry.query_models(
        ModelQuery(required_capabilities=frozenset({"code_generation"}))
    )
    assert models == []


def test_query_allowed_deployment_modes(registry):
    _seed(registry)
    registry.register_model(
        _model("m3", "p1", caps={"text_generation"}, deployment=DeploymentMode.LOCAL)
    )
    models = registry.query_models(
        ModelQuery(
            required_capabilities=frozenset({"text_generation"}),
            allowed_deployment_modes=frozenset({DeploymentMode.LOCAL}),
        )
    )
    assert [m.model_id for m in models] == ["m3"]


def test_query_excluded_provider(registry):
    _seed(registry)
    models = registry.query_models(
        ModelQuery(
            required_capabilities=frozenset({"text_generation"}),
            excluded_provider_ids=frozenset({"p1"}),
        )
    )
    assert models == []


def test_query_results_deterministic(registry):
    _seed(registry)
    a = registry.query_models(ModelQuery(required_capabilities=frozenset({"text_generation"})))
    b = registry.query_models(ModelQuery(required_capabilities=frozenset({"text_generation"})))
    assert [x.model_id for x in a] == [x.model_id for x in b]


def test_models_with_capability_any_status(registry):
    _seed(registry)
    registry.update_model_status("m2", ModelStatus.RETIRED)
    matched = registry.models_with_capability("code_generation")
    assert [m.model_id for m in matched] == ["m2"]


def test_snapshot_counts(registry):
    _seed(registry)
    registry.register_deployment(
        DeploymentMetadata(model_id="m1", mode=DeploymentMode.CLOUD)
    )
    counts = registry.snapshot_counts()
    assert counts == {
        "capabilities": 2,
        "providers": 2,
        "models": 2,
        "deployments": 1,
    }