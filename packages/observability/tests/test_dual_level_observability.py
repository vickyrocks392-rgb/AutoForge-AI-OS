"""
Comprehensive tests for Phase 17-A Dual-Level Observability (Node-Local and Fleet Observability).
"""

from __future__ import annotations
import uuid
from datetime import datetime, timezone
import pytest

from autoforge_event_platform.models.event import Event, EventCategory, EventType
from autoforge_observability.engine import ObservabilityPlatform
from autoforge_observability.models import (
    NodeIdentity,
    NodeStatusEnum,
    NodeResourceMetadata,
    RoutingDecisionRecord,
    NodeObservabilityReadModel,
    FleetObservabilityReadModel,
)


def test_node_identity_domain_model():
    """Verify NodeIdentity structure, defaults, and status enums."""
    node = NodeIdentity(
        node_id="local-hp",
        display_name="HP Workstation (LAN Worker Node)",
        hostname="192.168.1.105",
        platform="linux",
        architecture="x86_64",
        health=NodeStatusEnum.HEALTHY,
        capacity_slots=8,
        endpoint="http://192.168.1.105:11434",
        models=["qwen2.5-coder-3b"],
        providers=["local-hp"],
        resource_metadata=NodeResourceMetadata(
            memory_total_gb=128.0,
            memory_free_gb=86.2,
            gpu_info="NVIDIA GeForce RTX 4090",
        ),
    )
    assert node.node_id == "local-hp"
    assert node.health == NodeStatusEnum.HEALTHY
    assert node.capacity_slots == 8
    assert node.resource_metadata.gpu_info == "NVIDIA GeForce RTX 4090"
    assert node.is_live_hardware is True


def test_node_observability_scoping_and_fleet_aggregation(event_platform, observability_platform):
    """
    Verify that telemetry ingested for different nodes:
    1. Accurately updates each node's local read model.
    2. Correctly aggregates across all nodes in the fleet read model.
    """
    collector = observability_platform.collector
    dashboards = observability_platform.dashboards

    # Ingest inference on local-hp
    corr_hp = uuid.uuid4()
    collector.process_event(Event(
        event_type=EventType.CONNECTOR_EXECUTED,
        event_category=EventCategory.CONNECTOR,
        aggregate_type="Model",
        source="autoforge-ai-infrastructure",
        correlation_id=corr_hp,
        payload={
            "action": "llm_inference",
            "model_id": "qwen2.5-coder-3b",
            "provider_id": "local-hp",
            "node_id": "local-hp",
            "tokens": {"prompt_eval_count": 50, "eval_count": 100, "total_tokens": 150},
            "duration_ms": 15000.0,
            "throughput_tps": 10.0,
            "success": True,
            "task_id": "task-hp-001",
        },
    ))

    # Ingest inference on local-m1
    corr_m1 = uuid.uuid4()
    collector.process_event(Event(
        event_type=EventType.CONNECTOR_EXECUTED,
        event_category=EventCategory.CONNECTOR,
        aggregate_type="Model",
        source="autoforge-ai-infrastructure",
        correlation_id=corr_m1,
        payload={
            "action": "llm_inference",
            "model_id": "qwen2.5-coder-7b",
            "provider_id": "local-m1",
            "node_id": "local-m1",
            "tokens": {"prompt_eval_count": 80, "eval_count": 220, "total_tokens": 300},
            "duration_ms": 25000.0,
            "throughput_tps": 12.0,
            "success": True,
            "task_id": "task-m1-001",
        },
    ))

    # 1. Check Node-Local Projections
    hp_node_obs = dashboards.get_node("local-hp")
    assert hp_node_obs.node.node_id == "local-hp"
    assert hp_node_obs.total_requests == 1
    assert hp_node_obs.total_tokens == 150
    assert hp_node_obs.input_tokens == 50
    assert hp_node_obs.output_tokens == 100
    assert hp_node_obs.average_throughput_tps == 10.0
    assert hp_node_obs.average_latency_ms == 15000.0
    assert "qwen2.5-coder-3b" in hp_node_obs.model_metrics
    assert hp_node_obs.model_metrics["qwen2.5-coder-3b"]["tokens"] == 150

    m1_node_obs = dashboards.get_node("local-m1")
    assert m1_node_obs.node.node_id == "local-m1"
    assert m1_node_obs.total_requests == 1
    assert m1_node_obs.total_tokens == 300
    assert m1_node_obs.input_tokens == 80
    assert m1_node_obs.output_tokens == 220
    assert m1_node_obs.average_throughput_tps == 12.0
    assert m1_node_obs.average_latency_ms == 25000.0
    assert "qwen2.5-coder-7b" in m1_node_obs.model_metrics
    assert m1_node_obs.model_metrics["qwen2.5-coder-7b"]["tokens"] == 300

    # 2. Check Fleet Aggregate Projection
    fleet = dashboards.get_fleet()
    assert fleet.total_calls == 2
    assert fleet.successful_calls == 2
    assert fleet.failed_calls == 0
    assert fleet.total_tokens == 450
    assert fleet.total_input_tokens == 130
    assert fleet.total_output_tokens == 320
    assert fleet.nodes_count >= 3  # local-m1, local-hp, local-mac-mini-m6
    assert "local-hp" in fleet.nodes
    assert "local-m1" in fleet.nodes
    assert "local-mac-mini-m6" in fleet.nodes


def test_routing_decision_trail_recording(observability_platform):
    """Verify that routing decision records are stored in fleet history and node events."""
    dashboards = observability_platform.dashboards
    collector = observability_platform.collector

    corr_id = uuid.uuid4()
    collector.process_event(Event(
        event_type=EventType.MODEL_SELECTED,
        event_category=EventCategory.INFRASTRUCTURE,
        aggregate_type="Model",
        source="autoforge-ai-infrastructure",
        correlation_id=corr_id,
        payload={
            "task_id": "task-test-routing-01",
            "worker_id": "backend_engineer_01",
            "worker_type": "backend_engineer",
            "capabilities": ["text_generation", "code_generation"],
            "model_id": "qwen2.5-coder-3b",
            "provider_id": "local-hp",
            "node_id": "local-hp",
            "candidates": [
                {"model_id": "qwen2.5-coder-3b", "provider_id": "local-hp", "score": 1000.95},
                {"model_id": "qwen2.5-coder-7b", "provider_id": "local-m1", "score": 900.50},
            ],
            "privacy_policy": "local_only",
        },
    ))


    fleet = dashboards.get_fleet()
    assert len(fleet.routing_decisions) >= 1
    latest_decision = fleet.routing_decisions[0]
    assert latest_decision.task_id == "task-test-routing-01"
    assert latest_decision.selected_node_id == "local-hp"
    assert latest_decision.selected_model_id == "qwen2.5-coder-3b"
    assert latest_decision.outcome == "success"

    # Node event log check
    hp_obs = dashboards.get_node("local-hp")
    assert len(hp_obs.recent_events) >= 1
    assert hp_obs.recent_events[0]["task_id"] == "task-test-routing-01"


def test_node_health_state_transitions(observability_platform):
    """Verify health state transitions and fleet summary updates."""
    dashboards = observability_platform.dashboards

    dashboards.set_node_health("local-hp", NodeStatusEnum.DEGRADED, notes="High load")
    fleet = dashboards.get_fleet()
    assert fleet.degraded_nodes_count == 1
    assert dashboards.get_node("local-hp").node.health == NodeStatusEnum.DEGRADED

    dashboards.set_node_health("local-hp", NodeStatusEnum.OFFLINE, notes="Daemon stopped")
    fleet = dashboards.get_fleet()
    assert fleet.offline_nodes_count == 1
    assert dashboards.get_node("local-hp").node.health == NodeStatusEnum.OFFLINE

    dashboards.set_node_health("local-hp", NodeStatusEnum.HEALTHY, notes="Recovered")
    fleet = dashboards.get_fleet()
    assert fleet.healthy_nodes_count >= 2
    assert dashboards.get_node("local-hp").node.health == NodeStatusEnum.HEALTHY
