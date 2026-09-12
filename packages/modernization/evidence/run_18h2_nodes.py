"""18-H2 inference fabric node configuration (readiness support module).

This module is the MINIMUM configuration seam needed to run the September 22
three-node experiment (M1 + HP + Mac Mini) without redesigning the routing
system.

Design constraints honored:

* The frozen 18-H routing table (run_18g_entry_c1._ai_tasks) stays untouched.
* ``build_ai_tasks()`` returns the EXACT frozen 6-task table (same component,
  role, prompt, machine, endpoint, tag and worker ids) when only the default
  two-node topology is configured. This keeps every existing M1+HP harness
  byte-identical.
* A third node (``AUTOFORGE_MACMINI_OLLAMA_URL``) is purely additive: it is
  only included when explicitly configured. No model fleet for the Mac Mini is
  invented here — candidates are resolved by the caller at experiment time.
* Endpoints always come from environment variables (LAN-only, no WAN
  assumptions), matching ``run_18g_entry_a``.
"""
from __future__ import annotations

import os

# Canonical node ids used by the frozen routing table.
M1_NODE_ID = "M1"
HP_NODE_ID = "HP"
MACMINI_NODE_ID = "MACMINI"

# Environment variables that configure each LAN inference node.
NODE_ENV_VARS = {
    M1_NODE_ID: "AUTOFORGE_M1_OLLAMA_URL",
    HP_NODE_ID: "AUTOFORGE_HP_OLLAMA_URL",
    MACMINI_NODE_ID: "AUTOFORGE_MACMINI_OLLAMA_URL",
}

# Frozen 18-H default endpoints (identical to run_18g_entry_a defaults).
DEFAULT_ENDPOINTS = {
    M1_NODE_ID: "http://127.0.0.1:11434",
    HP_NODE_ID: "http://192.168.1.102:11434",
}

# Canonical fleet roles used by the frozen routing table (no new models).
ROLE_PRIMARY_CODING = "PRIMARY_CODING_ENGINE"
ROLE_REASONING = "ARCHITECTURAL_REASONING_ENGINE"
ROLE_SECONDARY = "SECONDARY_DISTRIBUTED_CODING_WORKER"


def node_id_to_provider_id(node_id: str) -> str:
    """Map a harness node id to the production registry provider id.

    ``M1 -> local-m1``, ``HP -> local-hp``, ``MACMINI -> local-mac-mini-m6``.
    """
    return {
        M1_NODE_ID: "local-m1",
        HP_NODE_ID: "local-hp",
        MACMINI_NODE_ID: "local-mac-mini-m6",
    }.get(node_id, "local-" + node_id.lower())


def resolve_node_endpoints() -> dict[str, str]:
    """Return configured endpoints for every node that has a non-empty URL.

    M1 and HP fall back to the frozen defaults; the Mac Mini is only present
    when ``AUTOFORGE_MACMINI_OLLAMA_URL`` is set (an empty value is treated as
    "not configured" so the two-node behavior is preserved).
    """
    endpoints = {}
    for node_id, env_name in NODE_ENV_VARS.items():
        value = os.environ.get(env_name, "").strip()
        if value:
            endpoints[node_id] = value.rstrip("/")
        elif node_id in DEFAULT_ENDPOINTS:
            endpoints[node_id] = DEFAULT_ENDPOINTS[node_id]
    return endpoints


def _third_node_tasks(endpoints: dict[str, str]) -> list[tuple]:
    """Build the additive task table for a configured third node.

    IMPORTANT: no Mac Mini model fleet is assumed. If the caller does not
    provide an explicit tag for the new node this returns an empty list, i.e.
    the third node is configured but carries no tasks — which is the honest
    pre-measurement state. The September 22 experiment decides the fleet.
    """
    return []


def build_ai_tasks(endpoints: dict[str, str] | None = None) -> list[tuple]:
    """Return the AI task routing table for the configured topology.

    Default (two-node M1+HP) reproduces ``run_18g_entry_c1._ai_tasks()``
    exactly. A configured Mac Mini has no canonical fleet yet, so the frozen
    six tasks are returned unchanged; the experiment allocates tasks to the
    third node only after measurement.
    """
    from run_18g_entry_c1 import _ai_tasks

    resolved = endpoints if endpoints is not None else resolve_node_endpoints()
    tasks = list(_ai_tasks())

    # Rebind endpoints from configuration (frozen tuples already carry the
    # default URLs, so this is a no-op unless a node endpoint was overridden).
    by_node = {node_id: URL for node_id, URL in resolved.items()}
    rebound = []
    for comp, role, prompt, machine, _old_ep, tag, worker in tasks:
        ep = by_node.get(machine, _old_ep)
        rebound.append((comp, role, prompt, machine, ep, tag, worker))
    # Additive tasks for a configured third node (empty until the fleet is
    # decided — never fabricated here).
    rebound.extend(_third_node_tasks(resolved))
    return rebound


def build_warm_preload_list(endpoints: dict[str, str] | None = None) -> list[tuple]:
    """Return the keep-alive warm preload spec for the configured topology.

    Shape: list of ``(endpoint, model_tag, machine_name)`` consumed by
    ``run_18h_helpers.warm_preload``. Identical to the frozen 18-H preload for
    the default two-node topology.
    """
    from run_18g_entry_a import CODING, HP_CODING, REASON

    resolved = endpoints if endpoints is not None else resolve_node_endpoints()
    if not resolved.get(M1_NODE_ID) or not resolved.get(HP_NODE_ID):
        raise ValueError("M1 and HP endpoints are required for the warm preload")
    return [
        (resolved[M1_NODE_ID], CODING, M1_NODE_ID),
        (resolved[M1_NODE_ID], REASON, M1_NODE_ID),
        (resolved[HP_NODE_ID], HP_CODING, HP_NODE_ID),
    ]


def node_endpoints_from_env_for_wiring(endpoints: dict[str, str] | None = None) -> dict[str, str]:
    """Translate harness node endpoints into the production wiring map.

    Returned dict maps production provider ids to Ollama base URLs so the
    composition wiring (``build_ai_infrastructure(node_endpoints=...)``) can
    bind exactly the same topology.
    """
    resolved = endpoints if endpoints is not None else resolve_node_endpoints()
    return {node_id_to_provider_id(node_id): url for node_id, url in resolved.items()}