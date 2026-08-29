"""
Tests for Dual-Level Observability REST API endpoints and Service Layer.
"""

from __future__ import annotations
import pytest
from autoforge_api.service import AutoForgeApiService
from autoforge_observability.models import NodeStatusEnum


def test_api_current_node_service(autoforge_service: AutoForgeApiService):
    """Test get_current_node() returns canonical host node identity."""
    res = autoforge_service.get_current_node()
    assert res.current_node_id == "local-m1"
    assert res.node.node_id == "local-m1"
    assert res.node.health == "healthy"
    assert res.node.is_live_hardware is True
    assert "qwen2.5-coder-7b" in res.node.models


def test_api_node_observability_service(autoforge_service: AutoForgeApiService):
    """Test get_node_observability() for specific nodes."""
    # Test local-hp
    hp_res = autoforge_service.get_node_observability(node_id="local-hp")
    assert hp_res.node.node_id == "local-hp"
    assert hp_res.node.health == "healthy"
    assert hp_res.node.endpoint == "http://192.168.1.105:11434"
    assert "qwen2.5-coder-3b" in hp_res.node.models

    # Test local-m1
    m1_res = autoforge_service.get_node_observability(node_id="local-m1")
    assert m1_res.node.node_id == "local-m1"
    assert m1_res.node.health == "healthy"

    # Test simulated/unprovisioned future node
    m6_res = autoforge_service.get_node_observability(node_id="local-mac-mini-m6")
    assert m6_res.node.node_id == "local-mac-mini-m6"
    assert m6_res.node.health == "unavailable"
    assert m6_res.node.is_live_hardware is False


def test_api_fleet_observability_service(autoforge_service: AutoForgeApiService):
    """Test get_fleet_observability() aggregates all nodes."""
    fleet = autoforge_service.get_fleet_observability()
    assert fleet.nodes_count >= 3
    assert fleet.healthy_nodes_count >= 2
    assert "local-m1" in fleet.nodes
    assert "local-hp" in fleet.nodes
    assert "local-mac-mini-m6" in fleet.nodes
    assert fleet.total_capacity_slots >= 12
    assert "qwen2.5-coder-3b" in fleet.model_distribution
    assert "local-hp" in fleet.model_distribution["qwen2.5-coder-3b"]
