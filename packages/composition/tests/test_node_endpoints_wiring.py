"""Focused tests: 18-H2 per-node endpoint wiring in the composition root.

Verifies:
- Without ``node_endpoints`` the binding is byte-identical to 18-H behavior
  (local-m1 and local-hp both fall back to ``ollama_base_url``).
- With ``node_endpoints`` each node gets its own LAN endpoint.
- A third node (e.g. ``local-mac-mini-m6``) is bound only when configured.
- ``build_ai_infrastructure`` forwards ``node_endpoints`` into the executor
  registry.
"""
from __future__ import annotations

import pytest

from autoforge_ai_infrastructure.adapters.ollama import OllamaProviderAdapter
from autoforge_ai_infrastructure.execution import ExecutorRegistry
from autoforge_composition.ai_infrastructure_wiring import (
    bind_default_provider_adapters,
    build_ai_infrastructure,
)


def _base_url_of(executor_registry: ExecutorRegistry, provider_id: str) -> str:
    adapter = executor_registry.get(provider_id)
    assert isinstance(adapter, OllamaProviderAdapter)
    return adapter.base_url


def test_default_binding_preserves_18h_single_url_behavior():
    """Without node_endpoints both local nodes share the default base URL."""
    registry = ExecutorRegistry()
    bind_default_provider_adapters(registry)
    assert _base_url_of(registry, "local-m1") == "http://127.0.0.1:11434"
    assert _base_url_of(registry, "local-hp") == "http://127.0.0.1:11434"
    # openai-compatible is still bound (18-H default set).
    assert "openai-compatible" in registry.bound_providers()


def test_node_endpoints_gives_independent_lan_endpoints():
    """Each node can expose its own LAN endpoint."""
    registry = ExecutorRegistry()
    bind_default_provider_adapters(
        registry,
        node_endpoints={
            "local-m1": "http://127.0.0.1:11434",
            "local-hp": "http://192.168.1.102:11434",
        },
    )
    assert _base_url_of(registry, "local-m1") == "http://127.0.0.1:11434"
    assert _base_url_of(registry, "local-hp") == "http://192.168.1.102:11434"


def test_third_node_bound_only_when_configured():
    """A third node is bound only when explicitly provided."""
    registry = ExecutorRegistry()
    bind_default_provider_adapters(
        registry,
        node_endpoints={"local-mac-mini-m6": "http://192.168.1.110:11434"},
    )
    assert _base_url_of(registry, "local-mac-mini-m6") == "http://192.168.1.110:11434"
    # Unconfigured nodes still default (no invented topology).
    assert _base_url_of(registry, "local-m1") == "http://127.0.0.1:11434"


def test_build_ai_infrastructure_forwards_node_endpoints():
    services = build_ai_infrastructure(
        bind_adapters=True,
        node_endpoints={
            "local-m1": "http://127.0.0.1:11434",
            "local-hp": "http://192.168.1.102:11434",
            "local-mac-mini-m6": "http://192.168.1.110:11434",
        },
    )
    bound = services.executor_registry.bound_providers()
    assert "local-m1" in bound
    assert "local-hp" in bound
    assert "local-mac-mini-m6" in bound
    assert _base_url_of(services.executor_registry, "local-hp") == "http://192.168.1.102:11434"
    assert _base_url_of(services.executor_registry, "local-mac-mini-m6") == "http://192.168.1.110:11434"