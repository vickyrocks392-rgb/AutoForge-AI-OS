"""Focused tests: 18-H2 per-node endpoint wiring in the composition root.

Verifies:
- Without ``node_endpoints`` the binding preserves the 18-H2 per-node behaviour
  (local-m1 and local-hp both fall back to the default local runtime URL).
- With ``node_endpoints`` each node gets its own LAN endpoint.
- A third node (e.g. ``local-mac-mini-m6``) is bound only when configured.
- ``build_ai_infrastructure`` forwards ``node_endpoints`` into the executor
  registry.

Gate 4 update: the canonical local runtime is now an OpenAI-compatible local
server (llama.cpp ``llama-server`` / MLX) rather than an Ollama daemon, so the
asserted default URL moved from ``:11434`` to the llama.cpp default
``http://127.0.0.1:8080/v1``. The behaviour under test — per-node independent
endpoints, default fallback, and no invented topology — is unchanged. Two tests
are added to pin the Gate 4 Ollama-removal contract.
"""
from __future__ import annotations

import pytest

from autoforge_ai_infrastructure.adapters.local_runtime import (
    DEFAULT_LOCAL_RUNTIME_BASE_URL,
    LocalRuntimeProviderAdapter,
)
from autoforge_ai_infrastructure.execution import ExecutorRegistry
from autoforge_composition.ai_infrastructure_wiring import (
    bind_default_provider_adapters,
    build_ai_infrastructure,
)


def _resolved_default() -> str:
    """The default local runtime URL *as the adapter resolves it*.

    ``AUTOFORGE_LOCAL_RUNTIME_URL`` overrides the compiled-in default, so the
    assertion resolves the same way the adapter does rather than hard-coding a
    URL that would break whenever a deployment (or a test run) points the
    runtime elsewhere.
    """
    import os

    return (os.environ.get("AUTOFORGE_LOCAL_RUNTIME_URL") or "").strip() or (
        DEFAULT_LOCAL_RUNTIME_BASE_URL
    )


def _base_url_of(executor_registry: ExecutorRegistry, provider_id: str) -> str:
    adapter = executor_registry.get(provider_id)
    assert isinstance(adapter, LocalRuntimeProviderAdapter)
    return adapter.base_url


def test_ollama_is_not_a_default_runtime_dependency():
    """Gate 4 §2/§13: the canonical binding must not require an Ollama daemon."""
    registry = ExecutorRegistry()
    bind_default_provider_adapters(registry)
    assert "local-ollama" not in registry.bound_providers()
    for provider_id in ("local-m1", "local-hp"):
        adapter = registry.get(provider_id)
        assert "Ollama" not in type(adapter).__name__
        assert ":11434" not in getattr(adapter, "base_url", "")


def test_ollama_remains_available_as_explicit_opt_in():
    """Provider neutrality is preserved rather than faked: Ollama still works."""
    registry = ExecutorRegistry()
    bind_default_provider_adapters(registry, bind_optional_ollama=True)
    assert "local-ollama" in registry.bound_providers()


def test_default_binding_preserves_18h_single_url_behavior():
    """Without node_endpoints both local nodes share the default base URL."""
    registry = ExecutorRegistry()
    bind_default_provider_adapters(registry)
    expected = _resolved_default()
    assert _base_url_of(registry, "local-m1") == expected
    assert _base_url_of(registry, "local-hp") == expected
    # openai-compatible is still bound (18-H default set).
    assert "openai-compatible" in registry.bound_providers()


def test_node_endpoints_gives_independent_lan_endpoints():
    """Each node can expose its own LAN endpoint."""
    registry = ExecutorRegistry()
    bind_default_provider_adapters(
        registry,
        node_endpoints={
            "local-m1": "http://127.0.0.1:8080/v1",
            "local-hp": "http://192.168.1.102:8080/v1",
        },
    )
    assert _base_url_of(registry, "local-m1") == "http://127.0.0.1:8080/v1"
    assert _base_url_of(registry, "local-hp") == "http://192.168.1.102:8080/v1"


def test_third_node_bound_only_when_configured():
    """A third node is bound only when explicitly provided."""
    registry = ExecutorRegistry()
    bind_default_provider_adapters(
        registry,
        node_endpoints={"local-mac-mini-m6": "http://192.168.1.110:8080/v1"},
    )
    assert _base_url_of(registry, "local-mac-mini-m6") == "http://192.168.1.110:8080/v1"
    # Unconfigured nodes still default (no invented topology).
    assert _base_url_of(registry, "local-m1") == _resolved_default()


def test_build_ai_infrastructure_forwards_node_endpoints():
    services = build_ai_infrastructure(
        bind_adapters=True,
        node_endpoints={
            "local-m1": "http://127.0.0.1:8080/v1",
            "local-hp": "http://192.168.1.102:8080/v1",
            "local-mac-mini-m6": "http://192.168.1.110:8080/v1",
        },
    )
    bound = services.executor_registry.bound_providers()
    assert "local-m1" in bound
    assert "local-hp" in bound
    assert "local-mac-mini-m6" in bound
    assert _base_url_of(services.executor_registry, "local-hp") == "http://192.168.1.102:8080/v1"
    assert _base_url_of(services.executor_registry, "local-mac-mini-m6") == "http://192.168.1.110:8080/v1"