"""Focused tests: 18-H2 node configuration module (evidence/routing seam).

Verifies:
- Default two-node resolution reproduces frozen 18-H endpoints.
- ``build_ai_tasks()`` returns the EXACT frozen 6-task table (byte-identical
  to ``run_18g_entry_c1._ai_tasks``) when no third node is configured.
- The warm preload list matches the frozen 18-H preload.
- A third node is represented only when configured via env var, and adds no
  fabricated tasks or models.
- Node-id -> production provider-id translation is correct.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

_EVIDENCE_DIR = str(Path(__file__).resolve().parents[1] / "evidence")


def _import(name):
    if _EVIDENCE_DIR not in sys.path:
        sys.path.insert(0, _EVIDENCE_DIR)
    return __import__(name)


def test_default_endpoints_match_frozen_values():
    nodes = _import("run_18h2_nodes")
    # Ensure no MACMINI env leak from the environment.
    os.environ.pop("AUTOFORGE_MACMINI_OLLAMA_URL", None)
    endpoints = nodes.resolve_node_endpoints()
    assert endpoints["M1"] == "http://127.0.0.1:11434"
    assert endpoints["HP"] == "http://192.168.1.102:11434"
    assert "MACMINI" not in endpoints


def test_build_ai_tasks_matches_frozen_table_by_default():
    nodes = _import("run_18h2_nodes")
    entry_c1 = _import("run_18g_entry_c1")
    os.environ.pop("AUTOFORGE_MACMINI_OLLAMA_URL", None)
    assert nodes.build_ai_tasks() == list(entry_c1._ai_tasks())


def test_build_ai_tasks_respects_explicit_endpoints():
    nodes = _import("run_18h2_nodes")
    entry_c1 = _import("run_18g_entry_c1")
    explicit = {
        "M1": "http://127.0.0.1:11434",
        "HP": "http://192.168.1.102:11434",
    }
    assert nodes.build_ai_tasks(endpoints=explicit) == list(entry_c1._ai_tasks())


def test_third_node_is_additive_not_invented():
    nodes = _import("run_18h2_nodes")
    entry_c1 = _import("run_18g_entry_c1")
    endpoints = {
        "M1": "http://127.0.0.1:11434",
        "HP": "http://192.168.1.102:11434",
        "MACMINI": "http://192.168.1.110:11434",
    }
    tasks = nodes.build_ai_tasks(endpoints=endpoints)
    # No fabricated Mac Mini fleet yet: the frozen six tasks are unchanged.
    assert tasks == list(entry_c1._ai_tasks())
    assert len(tasks) == 6


def test_warm_preload_matches_frozen_18h():
    nodes = _import("run_18h2_nodes")
    entry_a = _import("run_18g_entry_a")
    preloads = nodes.build_warm_preload_list()
    frozen = [
        (entry_a.M1_URL, entry_a.CODING, "M1"),
        (entry_a.M1_URL, entry_a.REASON, "M1"),
        (entry_a.HP_URL, entry_a.HP_CODING, "HP"),
    ]
    assert preloads == frozen


def test_node_id_to_provider_id():
    nodes = _import("run_18h2_nodes")
    assert nodes.node_id_to_provider_id("M1") == "local-m1"
    assert nodes.node_id_to_provider_id("HP") == "local-hp"
    assert nodes.node_id_to_provider_id("MACMINI") == "local-mac-mini-m6"


def test_endpoints_translate_to_production_wiring():
    nodes = _import("run_18h2_nodes")
    endpoints = {
        "M1": "http://127.0.0.1:11434",
        "HP": "http://192.168.1.102:11434",
        "MACMINI": "http://192.168.1.110:11434",
    }
    wiring = nodes.node_endpoints_from_env_for_wiring(endpoints)
    assert wiring == {
        "local-m1": "http://127.0.0.1:11434",
        "local-hp": "http://192.168.1.102:11434",
        "local-mac-mini-m6": "http://192.168.1.110:11434",
    }