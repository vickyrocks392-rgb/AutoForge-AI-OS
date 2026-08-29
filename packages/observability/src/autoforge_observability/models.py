"""
Telemetry, logging, tracing, and dashboard read-models for AutoForge Observability.
"""

from __future__ import annotations
import uuid
from datetime import datetime, timezone
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


# ── Phase 17-A Dual-Level Observability Models ──────────────────────────────

class NodeStatusEnum(str, Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    OFFLINE = "offline"
    UNAVAILABLE = "unavailable"
    UNKNOWN = "unknown"
    PLANNED_SPEC = "planned_spec"


class NodeResourceMetadata(BaseModel):
    cpu_utilization_percent: Optional[float] = None
    memory_total_bytes: Optional[int] = None
    memory_used_bytes: Optional[int] = None
    memory_free_bytes: Optional[int] = None
    memory_total_gb: Optional[float] = None
    memory_free_gb: Optional[float] = None
    gpu_info: Optional[str] = None
    vram_total_bytes: Optional[int] = None
    vram_used_bytes: Optional[int] = None
    disk_total_bytes: Optional[int] = None
    disk_free_bytes: Optional[int] = None
    process_health: str = "healthy"
    extra: Dict[str, Any] = Field(default_factory=dict)


class NodeIdentity(BaseModel):
    node_id: str
    display_name: str
    hostname: str = "localhost"
    platform: str = "darwin"
    architecture: str = "arm64"
    autoforge_version: str = "1.0.0"
    runtime_version: str = "3.14"
    health: NodeStatusEnum = NodeStatusEnum.HEALTHY
    uptime_seconds: float = 0.0
    last_seen: Optional[datetime] = None
    capabilities: List[str] = Field(default_factory=list)
    providers: List[str] = Field(default_factory=list)
    models: List[str] = Field(default_factory=list)
    capacity_slots: int = 1
    active_slots: int = 0
    resource_metadata: NodeResourceMetadata = Field(default_factory=NodeResourceMetadata)
    is_live_hardware: bool = True
    endpoint: Optional[str] = None
    notes: str = ""


class RoutingDecisionRecord(BaseModel):
    decision_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc) if "timezone" in globals() else datetime.utcnow())
    correlation_id: Optional[str] = None
    task_id: Optional[str] = None
    worker_id: Optional[str] = None
    worker_type: Optional[str] = None
    required_capabilities: List[str] = Field(default_factory=list)
    min_context_window_tokens: int = 1024
    privacy_policy: str = "local_only"
    candidate_scores: List[Dict[str, Any]] = Field(default_factory=list)
    selected_node_id: str = ""
    selected_model_id: str = ""
    selected_provider_id: str = ""
    outcome: str = "success"  # "success", "failover", "failed"
    failover_occurred: bool = False
    notes: str = ""


class NodeObservabilityReadModel(BaseModel):
    node: NodeIdentity
    active_calls: int = 0
    total_requests: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    average_throughput_tps: float = 0.0
    average_latency_ms: float = 0.0
    retries_count: int = 0
    failovers_count: int = 0
    failures_count: int = 0
    queue_depth: int = 0
    utilization: float = 0.0
    model_metrics: Dict[str, Dict[str, Any]] = Field(default_factory=dict)
    provider_metrics: Dict[str, Dict[str, Any]] = Field(default_factory=dict)
    active_executions: List[Dict[str, Any]] = Field(default_factory=list)
    recent_events: List[Dict[str, Any]] = Field(default_factory=list)


class FleetObservabilityReadModel(BaseModel):
    nodes_count: int = 0
    healthy_nodes_count: int = 0
    degraded_nodes_count: int = 0
    offline_nodes_count: int = 0
    unavailable_nodes_count: int = 0
    total_calls: int = 0
    successful_calls: int = 0
    failed_calls: int = 0
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_tokens: int = 0
    aggregate_throughput_tps: float = 0.0
    average_latency_ms: float = 0.0
    total_retries: int = 0
    total_failovers: int = 0
    total_capacity_slots: int = 0
    total_active_slots: int = 0
    fleet_utilization: float = 0.0
    nodes: Dict[str, NodeIdentity] = Field(default_factory=dict)
    model_distribution: Dict[str, List[str]] = Field(default_factory=dict)
    routing_decisions: List[RoutingDecisionRecord] = Field(default_factory=list)
    failure_breakdown: Dict[str, int] = Field(default_factory=dict)

