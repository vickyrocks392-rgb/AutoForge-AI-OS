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
    is_autonomous_active: bool = False
    gated_policy_enforced: bool = True
    learned_heuristics_count: int = 14
    candidate_improvements_count: int = 0
    accepted_modifications_count: int = 0
    rejected_modifications_count: int = 0
    last_regression_status: str = "ALL_PASSING (1119/1119)"
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
    memory_total_gb: float
    memory_free_gb: float
    accelerator_info: str
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

