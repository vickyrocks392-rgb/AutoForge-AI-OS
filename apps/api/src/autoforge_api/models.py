"""
API Models and View Schemas for AutoForge Product Experience.
"""

from __future__ import annotations
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class EpistemicState(str, Enum):
    FACT = "FACT"
    INFERENCE = "INFERENCE"
    HYPOTHESIS = "HYPOTHESIS"
    UNKNOWN = "UNKNOWN"


class WorkspaceMode(str, Enum):
    GREENFIELD = "GREENFIELD"
    LEGACY_MODERNIZATION = "LEGACY_MODERNIZATION"


class SystemStatusResponse(BaseModel):
    is_healthy: bool
    uptime_seconds: float
    platform_version: str = "0.1.0"
    active_operations_count: int = 0
    active_errors_count: int = 0
    security_violations: int = 0
    queue_depth: int = 0
    workspace_mode: WorkspaceMode = WorkspaceMode.GREENFIELD


class ProjectCreateRequest(BaseModel):
    name: str
    description: Optional[str] = ""
    template: Optional[str] = "greenfield"
    configuration: Dict[str, Any] = Field(default_factory=dict)


class ProjectResponse(BaseModel):
    project_id: str
    name: str
    description: str
    status: str
    active_workflow: Optional[str] = None
    current_phase: str = "initial"
    active_workers_count: int = 0
    artifacts_count: int = 0
    created_at: str
    updated_at: str


class WorkerProfileResponse(BaseModel):
    worker_type: str
    display_name: str
    category: str # "greenfield" | "legacy"
    capabilities: List[str]
    model_profile: Dict[str, Any]
    status: str # "ready" | "busy" | "idle" | "error"
    active_task_id: Optional[str] = None
    queue_depth: int = 0
    latency_ms: float = 0.0
    throughput_tps: float = 0.0
    errors_count: int = 0
    retries_count: int = 0
    allocated_model: Optional[str] = None
    node: str = "local_m1"
    permissions: List[Dict[str, Any]] = Field(default_factory=list)


class HITLApprovalRequest(BaseModel):
    action_type: str # e.g. "stack_finalization", "architecture_finalization", "migration_execution", "cutover"
    target_resource: str
    requester: str
    evidence: str
    risk_level: str # "low", "medium", "high", "critical"
    metadata: Dict[str, Any] = Field(default_factory=dict)


class HITLDecisionRequest(BaseModel):
    approval_id: str
    decision: str # "approve", "reject", "steer"
    actor_id: str
    feedback: Optional[str] = ""


class HITLApprovalResponse(BaseModel):
    approval_id: str
    action_type: str
    target_resource: str
    requester: str
    evidence: str
    risk_level: str
    status: str # "pending", "approved", "rejected", "steered"
    requested_at: str
    decided_at: Optional[str] = None
    decided_by: Optional[str] = None
    feedback: Optional[str] = None


class BusinessRuleResponse(BaseModel):
    rule_id: str
    rule_name: str
    description: str
    source_file: str
    line_range: str
    epistemic_state: EpistemicState
    confidence: float
    evidence: str


class ArchitectureComponentResponse(BaseModel):
    component_id: str
    name: str
    layer: str
    technologies: List[str]
    dependencies: List[str]
    epistemic_state: EpistemicState
    confidence: float
    evidence: str


class LegacyModernizationWorkspaceResponse(BaseModel):
    intake: Dict[str, Any]
    archaeology: Dict[str, Any]
    business_rules: List[BusinessRuleResponse]
    architecture_reconstruction: List[ArchitectureComponentResponse]
    modernization_strategy: Dict[str, Any]
    migration: Dict[str, Any]
    cutover: Dict[str, Any]
    deliverables: List[Dict[str, Any]]
    analysis_coverage_percent: float
    uncertainty_summary: Dict[str, int]


class NodeStatusResponse(BaseModel):
    node_id: str
    display_name: str
    status: str # "online", "busy", "offline", "planned_spec"
    is_live_hardware: bool
    capacity_slots: int
    active_slots: int
    queue_depth: int
    supported_models: List[str]
    notes: Optional[str] = None


class SelfImprovementResponse(BaseModel):
    """Self-Improvement Center read model.

    PHASE 19B-1 GATE 9 (GAP-12): the defaults were previously
    ``learned_heuristics_count=14`` and
    ``last_regression_status="ALL_PASSING (1119/1119)"``. Those are
    fabricated claims about system state originating from no engine, so a
    caller who forgot to set them still received false data.

    The defaults are now truthful: zero learning artifacts, and an explicit
    ``UNAVAILABLE`` regression status. Unknown is never rendered as success.
    """

    is_autonomous_active: bool = False
    gated_policy_enforced: bool = True
    learned_heuristics_count: int = 0
    candidate_improvements_count: int = 0
    accepted_modifications_count: int = 0
    rejected_modifications_count: int = 0
    last_regression_status: str = "UNAVAILABLE"
    safety_gating_mode: str = "STRICT_HUMAN_IN_THE_LOOP"
    learned_heuristics: List[Dict[str, Any]] = Field(default_factory=list)
    learned_items: List[Dict[str, Any]] = Field(default_factory=list)
    candidate_improvements: List[Dict[str, Any]] = Field(default_factory=list)
    experiments: List[Dict[str, Any]] = Field(default_factory=list)
    benchmark_results: List[Dict[str, Any]] = Field(default_factory=list)
    regression_results: List[Dict[str, Any]] = Field(default_factory=list)
    accepted_changes: List[Dict[str, Any]] = Field(default_factory=list)
    rejected_changes: List[Dict[str, Any]] = Field(default_factory=list)
    version_lineage: List[Dict[str, Any]] = Field(default_factory=list)
    rollback_history: List[Dict[str, Any]] = Field(default_factory=list)

    #: True when these figures were read from real runtime state. Lets a UI
    #: distinguish "genuinely zero" from "not measured".
    data_available: bool = False
    notes: str = ""




# ── Live Agent / Worker Activity Models ─────────────────────────────────────

class AgentActivityItem(BaseModel):
    event_id: str
    timestamp: str
    worker_id: str
    worker_type: str
    workflow_id: str
    task_id: str
    event_type: str # worker_started, model_allocated, tool_executed, file_modified, test_run, rag_query, etc.
    summary: str
    action_type: Optional[str] = None
    safe_input: Optional[Dict[str, Any]] = None
    safe_output: Optional[Dict[str, Any]] = None
    model_id: Optional[str] = None
    provider_id: Optional[str] = None
    node_id: Optional[str] = None
    duration_ms: Optional[float] = None
    trace_id: Optional[str] = None
    parent_event_id: Optional[str] = None
    status: str = "completed" # "completed", "running", "failed", "pending"


class ExecutionDrilldownResponse(BaseModel):
    execution_id: str
    workflow_id: str
    task_id: str
    worker_id: str
    worker_type: str
    status: str = "completed"
    model_policy: Dict[str, Any] = Field(default_factory=dict)
    effective_requirements: Dict[str, Any] = Field(default_factory=dict)
    allocator_decision: Dict[str, Any] = Field(default_factory=dict)
    allocated_model: str = "qwen2.5-coder-7b"
    router_decision: Dict[str, Any] = Field(default_factory=dict)
    provider_id: str = "local-m1"
    deployment_mode: str = "local"
    node_id: str = "local_m1"
    node_assignment: Dict[str, Any] = Field(default_factory=dict)
    inference_metrics: Dict[str, Any] = Field(default_factory=dict) # tokens, latency, cost or UNAVAILABLE
    tool_actions: List[Dict[str, Any]] = Field(default_factory=list)
    result_summary: str = ""
    artifact_id: Optional[str] = None
    artifacts: List[Dict[str, Any]] = Field(default_factory=list)
    review_gate: Optional[Dict[str, Any]] = None
    trace_id: str = ""



# ── Authoritative Model & Node Management Models ────────────────────────────

class ModelDetailResponse(BaseModel):
    model_id: str
    display_name: str
    provider_id: str
    family: str
    version: str
    status: str # "active", "disabled", "deprecated"
    context_window_tokens: int
    max_output_tokens: int
    capabilities: List[str]
    quality_tier: int
    reliability: float
    throughput_tps: float
    typical_latency_ms: float
    cost_per_m_in: float
    cost_per_m_out: float
    deployment_modes: List[str]
    node_assignments: List[str]
    utilization: float
    error_rate: float
    is_locally_executable: bool


class ModelCreateOrUpdateRequest(BaseModel):
    model_id: str
    display_name: str
    provider_id: str
    family: Optional[str] = "custom"
    version: Optional[str] = "1.0"
    status: Optional[str] = "active"
    context_window_tokens: int = 16384
    max_output_tokens: int = 2048
    capabilities: List[str] = Field(default_factory=list)
    quality_tier: int = 2
    reliability: float = 1.0
    throughput_tps: float = 12.0
    typical_latency_ms: float = 800.0
    deployment_modes: List[str] = Field(default_factory=lambda: ["local"])
    node_assignments: List[str] = Field(default_factory=list)


class NodeDetailResponse(BaseModel):
    node_id: str
    display_name: str
    node_type: str # "apple_silicon", "x86_workstation", "cloud_cluster", "simulation"
    status: str # "online", "busy", "offline", "planned_spec"
    is_live_hardware: bool
    capacity_slots: int
    active_slots: int
    utilization: float
    supported_models: List[str]
    memory_total_gb: Optional[float] = None
    memory_free_gb: Optional[float] = None
    accelerator_info: Optional[str] = None
    notes: Optional[str] = None



class NodeCreateOrUpdateRequest(BaseModel):
    node_id: str
    display_name: str
    node_type: str = "apple_silicon"
    status: Optional[str] = "online"
    is_live_hardware: bool = True
    capacity_slots: int = 4
    supported_models: List[str] = Field(default_factory=list)
    memory_total_gb: float = 64.0
    accelerator_info: str = "CPU/GPU"
    notes: Optional[str] = None


# ── Knowledge & RAG Pipeline & Telemetry Models ─────────────────────────────

class RAGPipelineStageResponse(BaseModel):
    stage_id: str
    stage_name: str
    order: int
    status: str # "active", "idle", "processing"
    description: str
    throughput_items_sec: Optional[float] = None
    average_latency_ms: Optional[float] = None
    error_count: int = 0


class KnowledgeTelemetryResponse(BaseModel):
    ingestion: Dict[str, Any]
    chunking: Dict[str, Any]
    embedding: Dict[str, Any]
    indexing: Dict[str, Any]
    retrieval: Dict[str, Any]
    reranking: Dict[str, Any]
    context_assembly: Dict[str, Any]
    quality: Dict[str, Any]
    cache: Dict[str, Any]
    cost: Dict[str, Any]


class KnowledgeWorkerTraceResponse(BaseModel):
    trace_id: str
    worker_id: str
    worker_type: str
    task_id: str
    query: str
    retriever_used: str
    retrieved_sources_count: int
    sources: List[Dict[str, Any]]
    reranker_used: str
    reranked_top_k: int
    context_tokens: int
    allocated_model: str
    output_artifact_id: Optional[str] = None
    timestamp: str


# ── Interactive Capabilities & Ingestion Models ─────────────────────────────

class CapabilityExecutionRequest(BaseModel):
    capability: str # "planning", "research", "coding", "full_stack"
    prompt: str
    project_id: Optional[str] = None
    documents: List[Dict[str, Any]] = Field(default_factory=list)
    parameters: Dict[str, Any] = Field(default_factory=dict)


class CapabilityExecutionResponse(BaseModel):
    execution_id: str
    capability: str
    status: str # "running", "completed", "failed"
    summary: str
    activities: List[AgentActivityItem] = Field(default_factory=list)
    artifacts: List[Dict[str, Any]] = Field(default_factory=list)
    telemetry: Dict[str, Any] = Field(default_factory=dict)
    timestamp: str


class ProjectUploadRequest(BaseModel):
    name: str
    description: Optional[str] = ""
    template: Optional[str] = "greenfield"
    files: List[Dict[str, str]] = Field(default_factory=list) # [{"path": "...", "content": "..."}]


class ProjectUploadResponse(BaseModel):
    project_id: str
    name: str
    files_discovered: int
    files_ingested: int
    chunks_created: int
    embeddings_generated: int
    ingestion_lifecycle: List[Dict[str, Any]] = Field(default_factory=list)
    status: str = "knowledge_ready"


class DocumentIngestResponse(BaseModel):
    document_id: str
    file_path: str
    mime_type: str
    size_bytes: int
    chunks_count: int
    status: str
    epistemic_provenance: str


class KnowledgeChunkResponse(BaseModel):
    chunk_id: str
    document_id: str
    file_path: str
    line_range: str
    content_snippet: str
    embedding_model: str
    epistemic_state: str


# ── Phase 17-A Dual-Level Observability API Response Models ─────────────────

class NodeIdentityDTO(BaseModel):
    node_id: str
    display_name: str
    hostname: str
    platform: str
    architecture: str
    autoforge_version: str
    runtime_version: str
    health: str
    uptime_seconds: float
    last_seen: Optional[str] = None
    capabilities: List[str] = Field(default_factory=list)
    providers: List[str] = Field(default_factory=list)
    models: List[str] = Field(default_factory=list)
    capacity_slots: int
    active_slots: int
    resource_metadata: Dict[str, Any] = Field(default_factory=dict)
    is_live_hardware: bool = True
    endpoint: Optional[str] = None
    notes: str = ""


class CurrentNodeResponse(BaseModel):
    current_node_id: str
    node: NodeIdentityDTO


class NodeObservabilityResponse(BaseModel):
    node: NodeIdentityDTO
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


class RoutingTrailItem(BaseModel):
    decision_id: str
    timestamp: str
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
    outcome: str = "success"
    failover_occurred: bool = False
    notes: str = ""


class FleetObservabilityResponse(BaseModel):
    nodes_count: int
    healthy_nodes_count: int
    degraded_nodes_count: int
    offline_nodes_count: int
    unavailable_nodes_count: int
    total_calls: int
    successful_calls: int
    failed_calls: int
    total_input_tokens: int
    total_output_tokens: int
    total_tokens: int
    aggregate_throughput_tps: float
    average_latency_ms: float
    total_retries: int
    total_failovers: int
    total_capacity_slots: int
    total_active_slots: int
    fleet_utilization: float
    nodes: Dict[str, NodeIdentityDTO] = Field(default_factory=dict)
    model_distribution: Dict[str, List[str]] = Field(default_factory=dict)
    routing_decisions: List[RoutingTrailItem] = Field(default_factory=list)
    failure_breakdown: Dict[str, int] = Field(default_factory=dict)

# ── Intent Understanding, Path Optimization & Output Models ─────────────────

class StageExecutionStatus(str, Enum):
    COMPLETED = "COMPLETED"
    RUNNING = "RUNNING"
    SKIPPED = "SKIPPED"
    PENDING = "PENDING"
    FAILED = "FAILED"


class IntentStageInfo(BaseModel):
    stage_id: str
    stage_name: str
    order: int
    status: StageExecutionStatus
    reason: Optional[str] = None
    worker_type: Optional[str] = None
    worker_id: Optional[str] = None
    model_id: Optional[str] = None
    node_id: Optional[str] = None
    duration_ms: Optional[float] = None
    details: Dict[str, Any] = Field(default_factory=dict)


# ── Technical Approach & Engineering Lifecycle Models ─────────────────────────

class TechStackProposal(BaseModel):
    application_name: str
    requested_type: str # e.g. "Desktop Application", "Web Application", "CLI Utility", "API Service"
    actual_type: str # e.g. "Web Application (Local Server & Client)", "Desktop Application", "CLI Utility"
    target_platform: str # e.g. "macOS (Darwin)", "Linux", "Windows", "Web"
    language: str # e.g. "Python 3.10+"
    ui_framework: str # e.g. "HTML5 / CSS3 / Vanilla JS Web UI"
    testing_framework: str # e.g. "pytest"
    packaging: str # e.g. "Physical Distribution Tarball (.tar.gz)"
    runtime: str # e.g. "Local Python Process Server with HTTP & CLI"
    build_target: str # e.g. "Localhost Web Application Runtime"
    packaging_disclaimer: Optional[str] = None
    estimated_complexity: str = "Low"
    approval_status: str = "PENDING" # "PENDING", "APPROVED", "MODIFIED", "REJECTED"


class ProjectPlanInfo(BaseModel):
    requirements: List[str] = Field(default_factory=list)
    goals: List[str] = Field(default_factory=list)
    milestones: List[Dict[str, Any]] = Field(default_factory=list)
    dependencies: List[str] = Field(default_factory=list)
    testing_strategy: str = "Automated isolated Pytest execution with mathematical edge case coverage."
    delivery_strategy: str = "Compiled distribution package (.tar.gz) + local runtime launch target."


class ArchitectureSpecInfo(BaseModel):
    pattern: str = "Layered Architecture (Presentation -> Application Services -> Domain Logic -> Runtime Server)"
    layers: List[Dict[str, Any]] = Field(default_factory=list)
    components: List[Dict[str, Any]] = Field(default_factory=list)
    interfaces: List[Dict[str, Any]] = Field(default_factory=list)


class DesignSpecInfo(BaseModel):
    screens: List[Dict[str, Any]] = Field(default_factory=list)
    components: List[Dict[str, Any]] = Field(default_factory=list)
    interactions: List[Dict[str, Any]] = Field(default_factory=list)
    states: List[str] = Field(default_factory=list)
    responsive_behavior: str = "Adaptive viewport layout (320px to full-width desktop)"


class PackagingToolchainStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    UNAVAILABLE = "UNAVAILABLE"
    DETECTED = "DETECTED"


class PackagingToolchainInfo(BaseModel):
    tool_name: str
    category: str # "python_desktop", "archive", "container", "macos_dmg"
    detected_path: Optional[str] = None
    version: Optional[str] = None
    status: PackagingToolchainStatus = PackagingToolchainStatus.UNAVAILABLE
    reason_if_unavailable: Optional[str] = None
    supported_targets: List[str] = Field(default_factory=list)


class SandboxInfo(BaseModel):
    sandbox_id: str
    root_directory: str
    source_directory: str
    build_directory: str
    dist_directory: str
    runtime_directory: str
    isolation_enforced: bool = True
    mutates_control_plane: bool = False


class BuildMetricsInfo(BaseModel):
    total_build_time_seconds: float = 0.0
    planning_time_seconds: float = 0.0
    research_time_seconds: float = 0.0
    design_time_seconds: float = 0.0
    implementation_time_seconds: float = 0.0
    testing_time_seconds: float = 0.0
    packaging_time_seconds: float = 0.0
    error_count: int = 0 # An execution/runtime/problem event
    failure_count: int = 0 # A stage that did not successfully complete
    retry_count: int = 0 # Repeating an operation without changing implementation
    rectification_loop_count: int = 0 # Failure -> diagnosis -> code/design modification -> reimplementation -> retest
    tests_generated: int = 8
    tests_executed: int = 8
    tests_passed: int = 8
    tests_failed: int = 0
    files_created: int = 3
    files_modified: int = 0
    workers_used: List[str] = Field(default_factory=list)
    models_used: List[str] = Field(default_factory=list)
    nodes_used: List[str] = Field(default_factory=list)
    inference_count: int = 1
    tokens_in: Optional[int] = None
    tokens_out: Optional[int] = None
    total_tokens: Optional[int] = None


class TechStackApprovalRequest(BaseModel):
    approval_id: str
    decision: str # "APPROVE", "MODIFY", "REJECT"
    modified_stack: Optional[Dict[str, Any]] = None
    feedback: Optional[str] = None


class IntentAnalysisRequest(BaseModel):
    prompt: str
    context: Optional[Dict[str, Any]] = None
    uploaded_files: List[str] = Field(default_factory=list)


class IntentAnalysisResponse(BaseModel):
    intent_type: str # application_build, planning, research, design, implementation, modernization, testing
    title: str
    description: str
    detected_inputs: Dict[str, bool] # e.g. {"plan_detected": True, "design_detected": False, ...}
    shortest_path_stages: List[IntentStageInfo]
    skipped_stages_summary: List[str]
    assigned_workforce: List[Dict[str, str]]
    recommended_model: str
    recommended_node: str
    estimated_duration_seconds: float
    tech_stack_proposal: Optional[TechStackProposal] = None
    project_plan: Optional[ProjectPlanInfo] = None
    architecture_spec: Optional[ArchitectureSpecInfo] = None
    design_spec: Optional[DesignSpecInfo] = None
    approval_required: bool = True
    approval_id: Optional[str] = None
    toolchains: List[PackagingToolchainInfo] = Field(default_factory=list)
    sandbox: Optional[SandboxInfo] = None


class IntentExecutionRequest(BaseModel):
    prompt: str
    intent_type: Optional[str] = "application_build"
    stages: Optional[List[IntentStageInfo]] = None
    context: Optional[Dict[str, Any]] = None
    tech_stack: Optional[TechStackProposal] = None
    approval_id: Optional[str] = None


class IntentExecutionResponse(BaseModel):
    execution_id: str
    project_id: str
    project_name: str
    status: str
    stages: List[IntentStageInfo]
    activities: List[AgentActivityItem]
    summary: str
    artifacts: List[Dict[str, Any]]
    output_preview: Dict[str, Any]
    tech_stack: Optional[TechStackProposal] = None
    build_metrics: Optional[BuildMetricsInfo] = None
    toolchains: List[PackagingToolchainInfo] = Field(default_factory=list)
    sandbox: Optional[SandboxInfo] = None


class ProjectOutputResponse(BaseModel):
    project_id: str
    name: str
    status: str
    summary: str
    created_at: str
    completed_at: str
    artifacts: List[Dict[str, Any]] = Field(default_factory=list)
    files_generated: List[Dict[str, Any]] = Field(default_factory=list)
    test_results: Dict[str, Any] = Field(default_factory=dict)
    architecture_summary: Dict[str, Any] = Field(default_factory=dict)
    deployment_info: Dict[str, Any] = Field(default_factory=dict)
    tech_stack: Optional[TechStackProposal] = None
    project_plan: Optional[ProjectPlanInfo] = None
    architecture_spec: Optional[ArchitectureSpecInfo] = None
    design_spec: Optional[DesignSpecInfo] = None
    build_metrics: Optional[BuildMetricsInfo] = None
    toolchains: List[PackagingToolchainInfo] = Field(default_factory=list)
    sandbox: Optional[SandboxInfo] = None


