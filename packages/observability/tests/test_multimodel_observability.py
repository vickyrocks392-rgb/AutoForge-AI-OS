"""
Tests for multi-model topology tracking and deterministic model routing explanations.
"""

from __future__ import annotations
import uuid
import pytest
from autoforge_event_platform.models.event import EventType
from autoforge_observability import ObservabilityPlatform


def test_multimodel_observability_distinction(event_platform, observability_platform):
    """
    Simulate:
    Node A (local-m1) -> Model A (qwen2.5-coder-7b)
    Node B (local-hp) -> Model B (qwen2.5-coder-3b)
    Node C (local-mac-mini-m6) -> Model C (mac-mini-m6-node)
    
    Execute three independent tasks and verify that observability distinguishes them.
    """
    correlation_a = uuid.uuid4()
    correlation_b = uuid.uuid4()
    correlation_c = uuid.uuid4()

    # Task A routing to Model A on Node A
    event_platform.publish(
        event_type=EventType.MODEL_SELECTED,
        source="model_router",
        correlation_id=correlation_a,
        payload={
            "model_id": "qwen2.5-coder-7b",
            "provider_id": "local-m1",
            "node_id": "local-m1",
            "capabilities": ["code_generation"],
        },
    )
    event_platform.publish(
        event_type=EventType.WORKER_DISPATCHED,
        source="execution_engine",
        correlation_id=correlation_a,
        payload={
            "worker_id": "backend_engineer_1",
            "worker_type": "backend_engineer",
            "task_id": str(uuid.uuid4()),
        },
    )

    # Task B routing to Model B on Node B
    event_platform.publish(
        event_type=EventType.MODEL_SELECTED,
        source="model_router",
        correlation_id=correlation_b,
        payload={
            "model_id": "qwen2.5-coder-3b",
            "provider_id": "local-hp",
            "node_id": "local-hp",
            "capabilities": ["text_generation"],
        },
    )
    event_platform.publish(
        event_type=EventType.WORKER_DISPATCHED,
        source="execution_engine",
        correlation_id=correlation_b,
        payload={
            "worker_id": "documentation_engineer_1",
            "worker_type": "documentation_engineer",
            "task_id": str(uuid.uuid4()),
        },
    )

    # Task C routing to Model C on Node C
    event_platform.publish(
        event_type=EventType.MODEL_SELECTED,
        source="model_router",
        correlation_id=correlation_c,
        payload={
            "model_id": "mac-mini-m6-node",
            "provider_id": "local-mac-mini-m6",
            "node_id": "local-mac-mini-m6",
            "capabilities": ["reasoning"],
        },
    )
    event_platform.publish(
        event_type=EventType.WORKER_DISPATCHED,
        source="execution_engine",
        correlation_id=correlation_c,
        payload={
            "worker_id": "research_engineer_1",
            "worker_type": "research_engineer",
            "task_id": str(uuid.uuid4()),
        },
    )

    # Verify that the inference node dashboard tracked active models correctly per node
    dashboard = observability_platform.dashboards.inference_node
    assert "qwen2.5-coder-7b" in dashboard.active_models_per_node["local-m1"]
    assert "qwen2.5-coder-3b" in dashboard.active_models_per_node["local-hp"]
    assert "mac-mini-m6-node" in dashboard.active_models_per_node["local-mac-mini-m6"]

    # Verify worker dispatches are distinguished
    workforce_db = observability_platform.dashboards.workforce
    assert workforce_db.worker_dispatch_counts["backend_engineer"] == 1
    assert workforce_db.worker_dispatch_counts["documentation_engineer"] == 1
    assert workforce_db.worker_dispatch_counts["research_engineer"] == 1


def test_deterministic_routing_explanations(observability_platform):
    """
    Verify explain_routing_decision returns clean checkmarks and crosses
    without LLM invocation.
    """
    decision_metadata = {
        "selected_model_id": "Model A",
        "rejected": {
            "Model B": "insufficient context",
            "Cloud Model C": "local-only policy",
        }
    }

    explanation = observability_platform.explain_routing_decision(decision_metadata)
    
    expected = (
        "Selected Model A because:\n"
        "✓ capability match\n"
        "✓ local-only satisfied\n"
        "✓ context requirement satisfied\n"
        "✓ node healthy\n"
        "✓ capacity available\n"
        "\n"
        "Rejected Model B because:\n"
        "✗ insufficient context\n"
        "\n"
        "Rejected Cloud Model C because:\n"
        "✗ local-only policy"
    )
    assert explanation == expected
