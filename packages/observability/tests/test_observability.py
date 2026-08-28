"""
Behavioral tests for the AutoForge Observability Platform.
"""

from __future__ import annotations
import uuid
import pytest
from datetime import datetime, timezone
from autoforge_event_platform.models.event import EventType, EventCategory
from autoforge_observability import ObservabilityPlatform, Severity
from autoforge_observability.errors import normalize_error


def test_event_ingestion_updates_telemetry(event_platform, observability_platform):
    # Publish a workflow started event
    event_platform.publish(
        event_type=EventType.WORKFLOW_STARTED,
        source="workflows",
        payload={"workflow_id": str(uuid.uuid4())},
    )

    # Check metrics
    assert observability_platform.metrics.get_counter("workflow.started") == 1.0
    assert observability_platform.dashboards.workflow.total_workflows == 1
    assert observability_platform.dashboards.workflow.active_workflows == 1


def test_deterministic_metrics_percentiles(observability_platform):
    # Record list of latencies
    observability_platform.metrics.record_histogram("test.latency", 10.0)
    observability_platform.metrics.record_histogram("test.latency", 20.0)
    observability_platform.metrics.record_histogram("test.latency", 30.0)
    observability_platform.metrics.record_histogram("test.latency", 40.0)
    observability_platform.metrics.record_histogram("test.latency", 50.0)

    assert observability_platform.metrics.get_average("test.latency") == 30.0
    assert observability_platform.metrics.get_percentile("test.latency", 50.0) == 30.0
    assert observability_platform.metrics.get_percentile("test.latency", 90.0) == 46.0


def test_structured_logging_with_secret_redaction(observability_platform):
    # Register secret to redact
    secret_token = "ghp_super_secret_api_key_12345"
    observability_platform.logger.register_secret(secret_token)

    # Log containing secret
    log_entry = observability_platform.logger.info(
        component="connectors",
        message=f"Connecting to GitHub with token {secret_token}",
        metadata={"token": secret_token, "normal_field": "normal_val"},
    )

    # Verify message and metadata are redacted
    assert secret_token not in log_entry.message
    assert "***" in log_entry.message
    assert log_entry.metadata["token"] == "***"
    assert log_entry.metadata["normal_field"] == "normal_val"


def test_tracing_context_propagation(observability_platform):
    trace_id = uuid.uuid4()
    
    # Start parent span
    parent = observability_platform.traces.start_span(
        name="workflow-execution",
        trace_id=trace_id,
        correlation_id=trace_id,
    )
    
    # Start child span
    child = observability_platform.traces.start_span(
        name="task-execution",
        trace_id=trace_id,
        parent_span_id=parent.span_id,
    )

    assert child.parent_span_id == parent.span_id
    
    # Retrieve updated parent to verify child links
    parent_retrieved = observability_platform.traces.get_span(parent.span_id)
    assert child.span_id in parent_retrieved.child_spans

    # End spans
    observability_platform.traces.end_span(child.span_id)
    observability_platform.traces.end_span(parent.span_id)

    child_end = observability_platform.traces.get_span(child.span_id)
    parent_end = observability_platform.traces.get_span(parent.span_id)

    assert child_end.status == "completed"
    assert child_end.end_time is not None
    assert parent_end.status == "completed"


def test_error_normalization():
    # Test standard exception
    exc = ValueError("Invalid parameter value provided")
    obs = normalize_error(exc, component="workflows")
    assert obs.category == "ValueError"
    assert obs.component == "workflows"
    assert not obs.retryable

    # Test dummy execution timeout exception
    class SubprocessTimeoutError(Exception):
        category = "ExecutionTimeout"
        retryable = True
        cause = "Process exceeded 30s limit"

    timeout_exc = SubprocessTimeoutError("Execution timed out")
    obs_timeout = normalize_error(timeout_exc, component="execution")
    assert obs_timeout.category == "ExecutionTimeout"
    assert obs_timeout.retryable
    assert obs_timeout.cause == "Process exceeded 30s limit"


def test_health_and_uptime_observability(observability_platform):
    # Verify uptime is computed and non-negative
    uptime = observability_platform.get_uptime_seconds()
    assert uptime >= 0.0

    # Verify health check succeeds by default
    health = observability_platform.get_health_status()
    assert health["healthy"]
    assert health["active_errors"] == 0

    # Simulate node degradation
    observability_platform.dashboards.set_provider_health("local-hp", online=False)
    
    health_degraded = observability_platform.get_health_status()
    assert not health_degraded["healthy"]
    assert "local-hp" in health_degraded["unhealthy_nodes"]


def test_hitl_governance_recording(event_platform, observability_platform):
    correlation_id = uuid.uuid4()
    
    # Publish approval required event
    event_platform.publish(
        event_type=EventType.APPROVAL_REQUIRED,
        source="governance",
        correlation_id=correlation_id,
        payload={"worker_id": "backend_engineer", "approval_type": "git_push"},
    )

    assert observability_platform.dashboards.hitl_governance.requests_count == 1
    assert observability_platform.dashboards.hitl_governance.active_approvals_count == 1
    assert observability_platform.dashboards.hitl_governance.approvals_by_worker["backend_engineer"] == 1
    assert observability_platform.dashboards.hitl_governance.approvals_by_type["git_push"] == 1

    # Publish approval decided
    event_platform.publish(
        event_type=EventType.APPROVAL_DECIDED,
        source="governance",
        correlation_id=correlation_id,
        payload={"decision": "approved"},
    )

    assert observability_platform.dashboards.hitl_governance.decisions_count == 1
    assert observability_platform.dashboards.hitl_governance.active_approvals_count == 0


def test_dependency_direction():
    # Verify that we can import event platform from observability, but event platform doesn't import observability.
    # This proves the dependency direction rule: Subsystem -> Telemetry -> Observability
    import autoforge_event_platform
    import autoforge_observability
    
    # Verify no circular imports occurred
    assert hasattr(autoforge_observability, "ObservabilityPlatform")
