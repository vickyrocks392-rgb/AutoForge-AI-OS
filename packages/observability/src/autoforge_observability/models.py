"""
Telemetry, logging, tracing, and dashboard read-models for AutoForge Observability.
"""

from __future__ import annotations
import uuid
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Set
from pydantic import BaseModel, Field


class Severity(str, Enum):
    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class MetricObservation(BaseModel):
    name: str
    value: float
    timestamp: datetime
    dimensions: Dict[str, Any] = Field(default_factory=dict)


class StructuredLogEntry(BaseModel):
    timestamp: datetime
    severity: Severity
    component: str
    message: str
    correlation_id: Optional[uuid.UUID] = None
    project_id: Optional[uuid.UUID] = None
    workflow_id: Optional[uuid.UUID] = None
    task_id: Optional[uuid.UUID] = None
    execution_id: Optional[uuid.UUID] = None
    attempt_id: Optional[uuid.UUID] = None
    worker_id: Optional[str] = None
    model_id: Optional[str] = None
    provider_id: Optional[str] = None
    deployment_id: Optional[str] = None
    node_id: Optional[str] = None
    artifact_id: Optional[uuid.UUID] = None
    review_id: Optional[uuid.UUID] = None
    approval_id: Optional[uuid.UUID] = None
    error_category: Optional[str] = None
    retryable: Optional[bool] = None
    duration_ms: Optional[float] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class TraceSpan(BaseModel):
    span_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    trace_id: uuid.UUID
    parent_span_id: Optional[uuid.UUID] = None
    name: str
    start_time: datetime
    end_time: Optional[datetime] = None
    status: str = "active"  # active, completed, failed
    correlation_id: Optional[uuid.UUID] = None
    project_id: Optional[uuid.UUID] = None
    workflow_id: Optional[uuid.UUID] = None
    task_id: Optional[uuid.UUID] = None
    execution_id: Optional[uuid.UUID] = None
    attempt_id: Optional[uuid.UUID] = None
    worker_id: Optional[str] = None
    loop_id: Optional[uuid.UUID] = None
    artifact_id: Optional[uuid.UUID] = None
    review_id: Optional[uuid.UUID] = None
    approval_id: Optional[uuid.UUID] = None
    model_id: Optional[str] = None
    provider_id: Optional[str] = None
    deployment_id: Optional[str] = None
    node_id: Optional[str] = None
    logs: List[StructuredLogEntry] = Field(default_factory=list)
    child_spans: List[uuid.UUID] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)


# ── Dashboard Schemas ─────────────────────────────────────────────────────────

class SystemDashboard(BaseModel):
    uptime_seconds: float = 0.0
    is_healthy: bool = True
    active_errors_count: int = 0
    throughput_events_per_sec: float = 0.0
    error_categories: Dict[str, int] = Field(default_factory=dict)
    security_violations: int = 0


class WorkflowDashboard(BaseModel):
    total_workflows: int = 0
    active_workflows: int = 0
    completed_workflows: int = 0
    failed_workflows: int = 0
    total_tasks: int = 0
    active_tasks: int = 0
    completed_tasks: int = 0
    failed_tasks: int = 0
    queued_tasks: int = 0
    average_workflow_duration_sec: float = 0.0
    average_task_duration_sec: float = 0.0
    concurrency: int = 0
    retries_count: int = 0


class ExecutionDashboard(BaseModel):
    total_executions: int = 0
    active_executions: int = 0
    completed_executions: int = 0
    failed_executions: int = 0
    cancelled_executions: int = 0
    average_execution_duration_sec: float = 0.0
    attempts_count: int = 0
    timeouts_count: int = 0
    recoveries_count: int = 0


class WorkforceDashboard(BaseModel):
    registered_workers: Set[str] = Field(default_factory=set)
    active_workers: Set[str] = Field(default_factory=set)
    worker_success_rates: Dict[str, float] = Field(default_factory=dict)  # worker_type -> rate
    worker_failure_rates: Dict[str, float] = Field(default_factory=dict)
    worker_dispatch_counts: Dict[str, int] = Field(default_factory=dict)
    loop_iterations: Dict[str, int] = Field(default_factory=dict)
    worker_remediations: Dict[str, int] = Field(default_factory=dict)  # worker_id -> repair attempts


class AIInfrastructureDashboard(BaseModel):
    total_model_calls: int = 0
    successful_model_calls: int = 0
    failed_model_calls: int = 0
    average_model_latency_ms: float = 0.0
    fallback_events_count: int = 0
    routing_decisions_count: int = 0
    active_routing_requests: int = 0
    estimated_cost: float = 0.0
    token_usage: Dict[str, int] = Field(default_factory=dict)  # input/output/total -> count
    provider_failovers: Dict[str, int] = Field(default_factory=dict)


class CapabilityDashboard(BaseModel):
    capability_usage_counts: Dict[str, int] = Field(default_factory=dict)  # capability -> count
    active_capabilities: Set[str] = Field(default_factory=set)
    rejected_capabilities_counts: Dict[str, int] = Field(default_factory=dict)


class ProviderDashboard(BaseModel):
    provider_status: Dict[str, bool] = Field(default_factory=dict)  # provider_id -> is_healthy
    provider_call_counts: Dict[str, int] = Field(default_factory=dict)
    provider_latencies: Dict[str, List[float]] = Field(default_factory=dict)


class ModelDashboard(BaseModel):
    model_status: Dict[str, str] = Field(default_factory=dict)  # model_id -> status
    model_call_counts: Dict[str, int] = Field(default_factory=dict)
    model_latencies: Dict[str, List[float]] = Field(default_factory=dict)
    model_estimated_costs: Dict[str, float] = Field(default_factory=dict)
    model_token_usage: Dict[str, int] = Field(default_factory=dict)


class InferenceNodeDashboard(BaseModel):
    node_status: Dict[str, bool] = Field(default_factory=dict)  # node_id -> online
    active_models_per_node: Dict[str, Set[str]] = Field(default_factory=dict)
    concurrency_per_node: Dict[str, int] = Field(default_factory=dict)
    resource_pressure: Dict[str, float] = Field(default_factory=dict)  # node_id -> load/pressure level


class ArtifactDashboard(BaseModel):
    artifacts_created_count: int = 0
    versions_created_count: int = 0
    publications_count: int = 0
    rollbacks_count: int = 0
    integrity_failures_count: int = 0
    artifacts_by_type: Dict[str, int] = Field(default_factory=dict)


class ReviewDashboard(BaseModel):
    total_reviews: int = 0
    passed_reviews: int = 0
    failed_reviews: int = 0
    average_review_latency_ms: float = 0.0
    repair_loops_count: int = 0
    approval_waits_count: int = 0


class LegacyModernizationDashboard(BaseModel):
    systems_analyzed: int = 0
    evidence_items_count: int = 0
    analysis_gaps_count: int = 0
    unknowns_encountered_count: int = 0
    business_rules_extracted: int = 0
    modernization_decisions_count: int = 0
    migration_plans_created: int = 0
    hitl_approvals_count: int = 0
    evidence_types: Dict[str, int] = Field(default_factory=dict)  # FACT, INFERENCE, etc.
    stage_durations: Dict[str, float] = Field(default_factory=dict)  # stage -> duration


class HITLGovernanceDashboard(BaseModel):
    requests_count: int = 0
    decisions_count: int = 0
    timeouts_count: int = 0
    average_wait_time_sec: float = 0.0
    active_approvals_count: int = 0
    approvals_by_worker: Dict[str, int] = Field(default_factory=dict)
    approvals_by_type: Dict[str, int] = Field(default_factory=dict)
