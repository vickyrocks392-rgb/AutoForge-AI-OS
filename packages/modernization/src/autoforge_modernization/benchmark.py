# AutoForge Modernization Benchmark Result Schemas
from __future__ import annotations

import platform
import uuid
from datetime import UTC, datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

WORKLOAD_VIEWS = (
    "entire_workload",
    "source_only",
    "eligible_only",
    "transformable_only",
    "transformed_only",
    "verified_only",
    "accepted_only",
    "failed_only",
    "blocked_only",
)


class LOCClassification(str, Enum):
    SOURCE = "SOURCE"
    ELIGIBLE = "ELIGIBLE"
    TRANSFORMED = "TRANSFORMED"
    VERIFIED = "VERIFIED"
    ACCEPTED = "ACCEPTED"
    SKIPPED = "SKIPPED"
    FAILED = "FAILED"
    BLOCKED = "BLOCKED"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    PLACEHOLDER = "PLACEHOLDER"


class WorkloadView(str, Enum):
    ENTIRE_WORKLOAD = "entire_workload"
    SOURCE_ONLY = "source_only"
    ELIGIBLE_ONLY = "eligible_only"
    TRANSFORMABLE_ONLY = "transformable_only"
    TRANSFORMED_ONLY = "transformed_only"
    VERIFIED_ONLY = "verified_only"
    ACCEPTED_ONLY = "accepted_only"
    FAILED_ONLY = "failed_only"
    BLOCKED_ONLY = "blocked_only"


def _utc_now() -> datetime:
    return datetime.now(UTC)


class WorkloadMetrics(BaseModel):
    total_files: int = 0
    eligible_files: int = 0
    transformable_files: int = 0
    analyzed_files: int = 0
    transformed_files: int = 0
    verified_files: int = 0
    accepted_files: int = 0
    skipped_files: int = 0
    failed_files: int = 0
    blocked_files: int = 0
    review_required_files: int = 0
    physical_loc: int = 0
    logical_loc: int = 0
    active_loc: int = 0
    eligible_physical_loc: int = 0
    eligible_logical_loc: int = 0
    transformed_physical_loc: int = 0
    transformed_logical_loc: int = 0
    verified_physical_loc: int = 0
    verified_logical_loc: int = 0
    accepted_physical_loc: int = 0
    accepted_logical_loc: int = 0
    cobol_files: int = 0
    cobol_loc: int = 0
    copybook_files: int = 0
    copybook_loc: int = 0
    bms_files: int = 0
    bms_loc: int = 0
    jcl_files: int = 0
    jcl_loc: int = 0
    sql_files: int = 0
    sql_loc: int = 0
    other_files: int = 0
    other_loc: int = 0
    semantic_constructs_total: int = 0
    dependency_edges_total: int = 0
    control_flow_nodes_total: int = 0
    cics_detected_files: int = 0
    vsam_detected_files: int = 0
    ims_detected_files: int = 0
    db2_detected_files: int = 0
    deterministic_files: int = 0
    deterministic_loc: int = 0
    llm_assisted_files: int = 0
    llm_assisted_loc: int = 0
    llm_generated_files: int = 0
    llm_generated_loc: int = 0
    hybrid_files: int = 0
    hybrid_loc: int = 0
    review_required_files_loc: int = 0
    blocked_files_loc: int = 0
    failed_files_loc: int = 0
    target_java_loc: int = 0
    target_other_loc: int = 0


class StageTiming(BaseModel):
    stage: str = ""
    started_at: datetime = Field(default_factory=_utc_now)
    completed_at: datetime | None = None
    duration_ms: float = 0.0
    files: int = 0
    loc: int = 0
    status: str = "pending"
    error: str = ""

    @property
    def duration_seconds(self) -> float:
        return self.duration_ms / 1000.0

    @property
    def duration_minutes(self) -> float:
        return self.duration_ms / 60_000.0

    @property
    def duration_hours(self) -> float:
        return self.duration_ms / 3_600_000.0


class StageMetrics(BaseModel):
    discovery: StageTiming = Field(default_factory=lambda: StageTiming(stage="discovery"))
    analysis: StageTiming = Field(default_factory=lambda: StageTiming(stage="analysis"))
    semantic_understanding: StageTiming = Field(default_factory=lambda: StageTiming(stage="semantic_understanding"))
    transformation: StageTiming = Field(default_factory=lambda: StageTiming(stage="transformation"))
    verification: StageTiming = Field(default_factory=lambda: StageTiming(stage="verification"))
    repair: StageTiming = Field(default_factory=lambda: StageTiming(stage="repair"))
    acceptance: StageTiming = Field(default_factory=lambda: StageTiming(stage="acceptance"))
    wall_clock_started_at: datetime = Field(default_factory=_utc_now)
    wall_clock_completed_at: datetime | None = None
    wall_clock_duration_ms: float = 0.0
    sum_of_work_durations_ms: float = 0.0
    dependency_wait_ms: float = 0.0
    queue_wait_ms: float = 0.0
    critical_path_ms: float = 0.0

    @property
    def wall_clock_seconds(self) -> float:
        return self.wall_clock_duration_ms / 1000.0

    @property
    def wall_clock_minutes(self) -> float:
        return self.wall_clock_duration_ms / 60_000.0

    @property
    def wall_clock_hours(self) -> float:
        return self.wall_clock_duration_ms / 3_600_000.0



class LLMMetrics(BaseModel):
    status: str = "UNAVAILABLE"
    provider: str = ""
    model: str = ""
    model_version: str = ""
    worker: str = ""
    total_calls: int = 0
    successful_calls: int = 0
    failed_calls: int = 0
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_tokens: int = 0
    avg_latency_ms: float = 0.0
    p50_latency_ms: float = 0.0
    p95_latency_ms: float = 0.0
    min_latency_ms: float = 0.0
    max_latency_ms: float = 0.0
    queue_latency_ms: float = 0.0
    inference_latency_ms: float = 0.0
    total_latency_ms: float = 0.0
    retries: int = 0
    failures: int = 0
    max_concurrency: int = 0
    actual_concurrency: int = 0
    throughput_tokens_per_second: float = 0.0
    llm_throughput_loc_per_hour: float = 0.0
    rag_assisted_calls: int = 0


class RAGMetrics(BaseModel):
    status: str = "UNAVAILABLE"
    query_count: int = 0
    retrieval_latency_ms: float = 0.0
    documents_retrieved: int = 0
    avg_retrieval_latency_ms: float = 0.0
    hit_rate: float = 0.0
    context_injected_chars: int = 0
    rag_assisted_transformations: int = 0
    retrieval_failures: int = 0
    avg_documents_per_query: float = 0.0


class VerificationMetrics(BaseModel):
    total_verified: int = 0
    syntax_pass: int = 0
    syntax_fail: int = 0
    compile_pass: int = 0
    compile_fail: int = 0
    static_pass: int = 0
    static_fail: int = 0
    test_pass: int = 0
    test_fail: int = 0
    placeholder_warnings: int = 0
    verification_success_rate: float = 0.0
    compile_success_rate: float = 0.0
    placeholder_free_rate: float = 0.0
    total_verification_duration_ms: float = 0.0
    avg_verification_duration_ms: float = 0.0


class RepairMetrics(BaseModel):
    units_requiring_repair: int = 0
    total_repair_attempts: int = 0
    successful_repairs: int = 0
    failed_repairs: int = 0
    retry_exhausted: int = 0
    diagnosis_duration_ms: float = 0.0
    repair_latency_ms: float = 0.0
    initial_failure_rate: float = 0.0
    repair_success_rate: float = 0.0
    avg_repairs_per_failed_unit: float = 0.0
    repaired_loc: int = 0
    final_accepted_after_repair: int = 0


class ConcurrencyMetrics(BaseModel):
    configured_max_concurrency: int = 0
    active_workers: int = 0
    max_concurrency_observed: int = 0
    actual_avg_concurrency: float = 0.0
    queue_depth_at_start: int = 0
    queue_depth_at_end: int = 0
    dependency_waits: int = 0
    cpu_percent: float = 0.0
    memory_mb: float = 0.0
    gpu_available: bool = False
    gpu_vram_mb: float = 0.0
    inference_worker_utilization: float = 0.0
    worker_contention_detected: bool = False



class EstimateComparison(BaseModel):
    optimistic_duration_ms: float = 0.0
    expected_duration_ms: float = 0.0
    pessimistic_duration_ms: float = 0.0
    confidence: float = 0.0
    actual_duration_ms: float = 0.0
    drift_ms: float = 0.0
    drift_percent: float = 0.0
    drift_status: str = "unknown"
    estimate_error: float = 0.0
    estimate_error_percent: float = 0.0
    live_eta_snapshots: list[dict] = Field(default_factory=list)

    @property
    def optimistic_hours(self) -> float:
        return self.optimistic_duration_ms / 3_600_000.0

    @property
    def expected_hours(self) -> float:
        return self.expected_duration_ms / 3_600_000.0

    @property
    def pessimistic_hours(self) -> float:
        return self.pessimistic_duration_ms / 3_600_000.0

    @property
    def actual_hours(self) -> float:
        return self.actual_duration_ms / 3_600_000.0


class ThroughputRates(BaseModel):
    analyzed_loc_per_second: float = 0.0
    analyzed_loc_per_minute: float = 0.0
    analyzed_loc_per_hour: float = 0.0
    files_analyzed_per_hour: float = 0.0
    transformed_loc_per_second: float = 0.0
    transformed_loc_per_minute: float = 0.0
    transformed_loc_per_hour: float = 0.0
    files_transformed_per_hour: float = 0.0
    verified_loc_per_second: float = 0.0
    verified_loc_per_hour: float = 0.0
    files_verified_per_hour: float = 0.0
    accepted_loc_per_second: float = 0.0
    accepted_loc_per_minute: float = 0.0
    accepted_loc_per_hour: float = 0.0
    accepted_files_per_hour: float = 0.0
    verified_e2e_loc_per_hour: float = 0.0
    accepted_e2e_loc_per_hour: float = 0.0
    deterministic_loc: int = 0
    deterministic_loc_per_hour: float = 0.0
    llm_assisted_loc: int = 0
    llm_assisted_loc_per_hour: float = 0.0
    hybrid_loc: int = 0
    hybrid_loc_per_hour: float = 0.0
    llm_generated_loc: int = 0
    llm_generated_loc_per_hour: float = 0.0

    @property
    def primary_throughput(self) -> tuple[float, str]:
        return (self.accepted_e2e_loc_per_hour, "source LOC/hour (accepted, end-to-end)")


class MarketProjection(BaseModel):
    method: str = "extrapolation_from_measured_run"
    measured_throughput_loc_per_hour: float = 0.0
    measured_duration_seconds: float = 0.0
    measured_source_loc: int = 0
    projection_100k_loc_hours: float = 0.0
    projection_100k_loc_days: float = 0.0
    projection_100k_loc_months: float = 0.0
    projection_1m_loc_days: float = 0.0
    projection_1m_loc_months: float = 0.0
    projection_10m_loc_months: float = 0.0
    projection_10m_loc_years: float = 0.0
    projection_100m_loc_years: float = 0.0
    scaling_factors: dict[str, str] = Field(default_factory=dict)
    confidence: str = "low"



class ThroughputBenchmarkResult(BaseModel):
    benchmark_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    run_id: str = ""
    session_id: str = ""
    autoforge_version: str = "0.1.0"
    autoforge_commit: str = ""
    project_name: str = ""
    project_path: str = ""
    platform: str = ""
    python_version: str = ""
    hardware_cpu_cores: int = 0
    hardware_memory_mb: float = 0.0
    gpu_available: bool = False
    gpu_model: str = ""
    max_concurrency: int = 0
    llm_available: bool = False
    rag_available: bool = False
    repair_enabled: bool = True
    workload: WorkloadMetrics = Field(default_factory=WorkloadMetrics)
    workload_view: str = "entire_workload"
    throughput: ThroughputRates = Field(default_factory=ThroughputRates)
    stages: StageMetrics = Field(default_factory=StageMetrics)
    llm: LLMMetrics = Field(default_factory=LLMMetrics)
    rag: RAGMetrics = Field(default_factory=RAGMetrics)
    verification: VerificationMetrics = Field(default_factory=VerificationMetrics)
    repair: RepairMetrics = Field(default_factory=RepairMetrics)
    concurrency: ConcurrencyMetrics = Field(default_factory=ConcurrencyMetrics)
    estimation: EstimateComparison = Field(default_factory=EstimateComparison)
    projection: MarketProjection = Field(default_factory=MarketProjection)
    timestamp: datetime = Field(default_factory=_utc_now)
    provenance: list[dict] = Field(default_factory=list)
    throughput_kind: str = "MEASURED"
    llm_kind: str = "UNAVAILABLE"
    rag_kind: str = "UNAVAILABLE"
    estimation_kind: str = "ESTIMATED"

    def to_machine_readable(self) -> dict[str, Any]:
        return self.model_dump(mode="json")

    def to_human_readable(self) -> str:
        w = self.workload
        t = self.throughput
        llm_m = self.llm
        rag_m = self.rag
        rep = self.repair
        ver = self.verification
        stg = self.stages
        est = self.estimation
        con = self.concurrency
        proj = self.projection
        parts: list[str] = []
        parts.append("=" * 70)
        parts.append("AUTOFORGE MODERNIZATION BENCHMARK")
        parts.append("=" * 70)
        parts.append(f"Benchmark ID:     {self.benchmark_id}")
        parts.append(f"Run ID:           {self.run_id}")
        parts.append(f"Commit:           {self.autoforge_commit or 'N/A'}")
        parts.append(f"Project:          {self.project_name}")
        parts.append(f"Path:             {self.project_path}")
        parts.append("")
        parts.append("-- WORKLOAD ----------------------------------------")
        parts.append(f"Total files:      {w.total_files}")
        parts.append(f"Source LOC:       {w.physical_loc:,}")
        parts.append(f"Logical LOC:      {w.logical_loc:,}")
        parts.append(f"Eligible LOC:      {w.eligible_physical_loc:,}")
        parts.append(f"Transformable:    {w.transformable_files} files")
        parts.append("")
        parts.append("-- TECHNOLOGY DISTRIBUTION ------------------------------")
        parts.append(f"COBOL:            {w.cobol_files} files / {w.cobol_loc:,} LOC")
        parts.append(f"COPYBOOK:         {w.copybook_files} files / {w.copybook_loc:,} LOC")
        parts.append(f"BMS:              {w.bms_files} files / {w.bms_loc:,} LOC")
        parts.append(f"JCL:              {w.jcl_files} files / {w.jcl_loc:,} LOC")
        parts.append(f"SQL:              {w.sql_files} files / {w.sql_loc:,} LOC")
        parts.append("")
        parts.append("-- THROUGHPUT (MEASURED) -------------------------------")
        parts.append(f"Analysis:         {t.analyzed_loc_per_hour:,.0f} LOC/hour")
        parts.append(f"Transformation:   {t.transformed_loc_per_hour:,.0f} LOC/hour")
        parts.append(f"Verification:     {t.verified_loc_per_hour:,.0f} LOC/hour")
        parts.append(f"Accepted E2E:     {t.accepted_e2e_loc_per_hour:,.0f} LOC/hour  PRIMARY")
        parts.append("")
        parts.append("-- STRATEGY BREAKDOWN ----------------------------------")
        parts.append(f"Deterministic:    {w.deterministic_files} files / {w.deterministic_loc:,} LOC")
        parts.append(f"LLM-assisted:     {w.llm_assisted_files} files / {w.llm_assisted_loc:,} LOC")
        parts.append(f"Hybrid:           {w.hybrid_files} files / {w.hybrid_loc:,} LOC")
        parts.append(f"Review-required:  {w.review_required_files} files")
        parts.append(f"Failed:           {w.failed_files} files")
        parts.append("")
        parts.append(f"-- LLM ({self.llm_kind}) ------------------------------------")
        parts.append(f"Status:           {llm_m.status}")
        parts.append(f"Provider:         {llm_m.provider or 'N/A'}")
        parts.append(f"Model:            {llm_m.model or 'N/A'}")
        parts.append(f"Calls:            {llm_m.total_calls}")
        parts.append(f"Tokens:           {llm_m.total_tokens:,}")
        parts.append(f"Avg latency:      {llm_m.avg_latency_ms:,.0f} ms")
        parts.append(f"LLM throughput:   {llm_m.llm_throughput_loc_per_hour:,.0f} LOC/hour")
        parts.append("")
        parts.append(f"-- RAG ({self.rag_kind}) ------------------------------------")
        parts.append(f"Status:           {rag_m.status}")
        parts.append(f"Queries:          {rag_m.query_count}")
        parts.append(f"Retrieval time:   {rag_m.retrieval_latency_ms:,.0f} ms")
        parts.append(f"RAG-assisted LOC: {rag_m.rag_assisted_transformations}")

        parts.append("")
        parts.append("-- REPAIR ----------------------------------------------")
        parts.append(f"Failures:         {rep.units_requiring_repair}")
        parts.append(f"Repairs:          {rep.total_repair_attempts}")
        parts.append(f"Repair success:    {rep.repair_success_rate:.1%}")
        parts.append(f"Accepted after:   {rep.final_accepted_after_repair}")
        parts.append("")
        parts.append("-- VERIFICATION ----------------------------------------")
        parts.append(f"Total verified:   {ver.total_verified}")
        parts.append(f"Success rate:     {ver.verification_success_rate:.1%}")
        parts.append(f"Placeholder-free: {ver.placeholder_free_rate:.1%}")
        parts.append("")
        parts.append("-- TIME ------------------------------------------------")
        parts.append(f"Wall clock:        {stg.wall_clock_minutes:.1f} minutes")
        parts.append(f"Analysis:         {stg.analysis.duration_minutes:.1f} min")
        parts.append(f"Transformation:   {stg.transformation.duration_minutes:.1f} min")
        parts.append(f"Verification:     {stg.verification.duration_minutes:.1f} min")
        parts.append("")
        parts.append(f"-- ESTIMATION ({self.estimation_kind}) ---------------------------")
        parts.append(f"Initial ETA:      {est.optimistic_hours:.1f}h / {est.expected_hours:.1f}h / {est.pessimistic_hours:.1f}h")
        parts.append(f"Actual:           {est.actual_hours:.1f}h")
        parts.append(f"Drift:            {est.drift_percent:+.1f}% ({est.drift_status})")
        parts.append(f"Confidence:       {est.confidence:.0%}")
        parts.append("")
        parts.append("-- CONCURRENCY ------------------------------------------")
        parts.append(f"Max concurrency:  {con.configured_max_concurrency}")
        parts.append(f"Observed max:     {con.max_concurrency_observed}")
        parts.append(f"Avg concurrency:  {con.actual_avg_concurrency:.1f}")
        parts.append("")
        parts.append("-- PROJECTION (EXTRAPOLATION -- NOT MEASURED) --------")
        parts.append(f"100K LOC:          {proj.projection_100k_loc_days:.1f} days")
        parts.append(f"1M LOC:            {proj.projection_1m_loc_months:.1f} months")
        parts.append(f"10M LOC:           {proj.projection_10m_loc_months:.0f} months")
        parts.append(f"100M LOC:          {proj.projection_100m_loc_years:.1f} years")
        parts.append("")
        parts.append("-- OUTPUT FILES ------------------------------------------")
        parts.append(f"Transformed:       {w.transformed_files}")
        parts.append(f"Verified:          {w.verified_files}")
        parts.append(f"Accepted:          {w.accepted_files}")
        parts.append(f"Target Java LOC:  {w.target_java_loc:,}")
        parts.append("")
        parts.append("=" * 70)
        return "\n".join(parts)

    def summary_dict(self) -> dict[str, Any]:
        return {
            "benchmark_id": self.benchmark_id,
            "run_id": self.run_id,
            "project": self.project_name,
            "source_loc": self.workload.physical_loc,
            "eligible_loc": self.workload.eligible_physical_loc,
            "accepted_e2e_loc_per_hour": self.throughput.accepted_e2e_loc_per_hour,
            "llm_kind": self.llm_kind,
            "llm_available": self.llm_available,
            "wall_clock_minutes": self.stages.wall_clock_minutes,
            "analysis_minutes": self.stages.analysis.duration_minutes,
            "transformation_minutes": self.stages.transformation.duration_minutes,
            "verification_minutes": self.stages.verification.duration_minutes,
            "files_total": self.workload.total_files,
            "files_accepted": self.workload.accepted_files,
            "files_failed": self.workload.failed_files,
            "strategy_deterministic_loc": self.workload.deterministic_loc,
            "strategy_llm_assisted_loc": self.workload.llm_assisted_loc,
            "strategy_hybrid_loc": self.workload.hybrid_loc,
            "projection_100k_loc_days": self.projection.projection_100k_loc_days,
            "projection_1m_loc_months": self.projection.projection_1m_loc_months,
        }


def collect_hardware_metadata() -> dict[str, Any]:
    return {
        "platform": platform.platform(),
        "python_version": platform.python_version(),
        "hardware_cpu_cores": _cpu_count_or_default(),
        "hardware_memory_mb": _memory_mb_or_default(),
    }


def _cpu_count_or_default() -> int:
    try:
        import os

        return os.cpu_count() or 0
    except Exception:
        return 0


def _memory_mb_or_default() -> float:
    try:
        import resource

        usage = resource.getrusage(resource.RUSAGE_SELF)
        return float(usage.ru_maxrss) / 1024.0
    except Exception:
        return 0.0


__all__ = [
    "WorkloadView",
    "LOCClassification",
    "WorkloadMetrics",
    "StageTiming",
    "StageMetrics",
    "LLMMetrics",
    "RAGMetrics",
    "VerificationMetrics",
    "RepairMetrics",
    "ConcurrencyMetrics",
    "EstimateComparison",
    "ThroughputRates",
    "MarketProjection",
    "ThroughputBenchmarkResult",
    "collect_hardware_metadata",
]
