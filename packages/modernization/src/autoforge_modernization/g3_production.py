"""G.3 Production: Legacy Mapping + Metrics + Output (Phase 18-G.3)."""
from __future__ import annotations
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any
from pydantic import BaseModel, Field


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


# ── Mapping Enums ──────────────────────────────────────────────────────────────

class MappingKind(str, Enum):
    DIRECT = "direct"; COMPOSITE = "composite"; CONDITIONAL = "conditional"
    REVIEW_REQUIRED = "review_required"; UNSUPPORTED = "unsupported"


class MappingConfidence(str, Enum):
    HIGH = "high"; MEDIUM = "medium"; LOW = "low"; UNKNOWN = "unknown"


class MappingRisk(str, Enum):
    LOW = "low"; MEDIUM = "medium"; HIGH = "high"; CRITICAL = "critical"


class TechnologyMapping(BaseModel):
    source_technology: str; source_construct: str
    target_technology: str; target_construct: str
    mapping_kind: MappingKind; description: str = ""
    strategy: str = ""
    preconditions: list[str] = Field(default_factory=list)
    incompatibilities: list[str] = Field(default_factory=list)
    business_risks: list[str] = Field(default_factory=list)
    verification_requirements: list[str] = Field(default_factory=list)
    confidence: MappingConfidence = MappingConfidence.MEDIUM
    risk: MappingRisk = MappingRisk.MEDIUM


class LegacyMappingEngine:
    def __init__(self):
        self._mappings: list[TechnologyMapping] = [
            TechnologyMapping(source_technology="COBOL", source_construct="PERFORM paragraph", target_technology="Java", target_construct="method call", mapping_kind=MappingKind.DIRECT, description="COBOL PERFORM maps to Java method invocation", strategy="method_call", confidence=MappingConfidence.HIGH, risk=MappingRisk.LOW, verification_requirements=["behavioral equivalence test"]),
            TechnologyMapping(source_technology="COBOL", source_construct="MOVE data", target_technology="Java", target_construct="variable assignment", mapping_kind=MappingKind.DIRECT, description="COBOL MOVE maps to Java assignment", strategy="assignment", confidence=MappingConfidence.HIGH, risk=MappingRisk.LOW),
            TechnologyMapping(source_technology="COBOL", source_construct="IF condition THEN", target_technology="Java", target_construct="if statement", mapping_kind=MappingKind.DIRECT, description="COBOL IF maps to Java if", strategy="conditional", confidence=MappingConfidence.HIGH, risk=MappingRisk.LOW),
            TechnologyMapping(source_technology="COBOL", source_construct="EVALUATE", target_technology="Java", target_construct="switch/if-else", mapping_kind=MappingKind.DIRECT, description="COBOL EVALUATE maps to Java switch", strategy="switch", confidence=MappingConfidence.HIGH, risk=MappingRisk.LOW),
            TechnologyMapping(source_technology="COBOL", source_construct="COMPUTE field", target_technology="Java", target_construct="arithmetic expression", mapping_kind=MappingKind.DIRECT, description="COBOL COMPUTE maps to Java arithmetic", strategy="arithmetic", confidence=MappingConfidence.HIGH, risk=MappingRisk.LOW),
            TechnologyMapping(source_technology="COBOL", source_construct="CALL program", target_technology="Java", target_construct="method call", mapping_kind=MappingKind.DIRECT, description="COBOL CALL maps to Java method", strategy="method_call", confidence=MappingConfidence.MEDIUM, risk=MappingRisk.MEDIUM, incompatibilities=["parameter semantics differ"]),
            TechnologyMapping(source_technology="COBOL", source_construct="COPY copybook", target_technology="Java", target_construct="import statement", mapping_kind=MappingKind.DIRECT, description="COBOL COPY maps to Java import", strategy="import", confidence=MappingConfidence.HIGH, risk=MappingRisk.LOW),
            TechnologyMapping(source_technology="COBOL", source_construct="Working-Storage group", target_technology="Java", target_construct="class fields", mapping_kind=MappingKind.COMPOSITE, description="COBOL WS group items map to Java class fields", strategy="data_structure", confidence=MappingConfidence.MEDIUM, risk=MappingRisk.MEDIUM),
            TechnologyMapping(source_technology="COBOL", source_construct="File I/O", target_technology="Java", target_construct="NIO streams", mapping_kind=MappingKind.COMPOSITE, description="COBOL file I/O maps to Java NIO", strategy="file_io", confidence=MappingConfidence.MEDIUM, risk=MappingRisk.MEDIUM),
            TechnologyMapping(source_technology="JCL", source_construct="EXEC PGM", target_technology="workflow", target_construct="task step", mapping_kind=MappingKind.DIRECT, description="JCL EXEC maps to workflow task", strategy="step_to_task", confidence=MappingConfidence.MEDIUM, risk=MappingRisk.MEDIUM),
            TechnologyMapping(source_technology="JCL", source_construct="DD DSN", target_technology="workflow", target_construct="data source", mapping_kind=MappingKind.DIRECT, description="JCL DD DSN maps to workflow data source", strategy="dataset_to_datasource", confidence=MappingConfidence.MEDIUM, risk=MappingRisk.MEDIUM),
            TechnologyMapping(source_technology="DB2", source_construct="CREATE TABLE", target_technology="PostgreSQL", target_construct="CREATE TABLE", mapping_kind=MappingKind.DIRECT, description="DB2 schema maps to PostgreSQL", strategy="schema_migration", confidence=MappingConfidence.HIGH, risk=MappingRisk.LOW),
            TechnologyMapping(source_technology="DB2", source_construct="Stored procedure", target_technology="PostgreSQL", target_construct="function", mapping_kind=MappingKind.DIRECT, description="DB2 stored procedures map to PostgreSQL functions", strategy="procedure_to_function", confidence=MappingConfidence.MEDIUM, risk=MappingRisk.MEDIUM),
            TechnologyMapping(source_technology="BMS", source_construct="DFHMSD MAP", target_technology="React/HTML", target_construct="UI component", mapping_kind=MappingKind.REVIEW_REQUIRED, description="BMS maps require human review for UI strategy", confidence=MappingConfidence.UNKNOWN, risk=MappingRisk.HIGH, verification_requirements=["UI equivalence", "user acceptance testing"]),
            TechnologyMapping(source_technology="CICS", source_construct="EXEC CICS LINK", target_technology="REST/Spring", target_construct="REST API call", mapping_kind=MappingKind.REVIEW_REQUIRED, description="CICS requires architectural review for REST design", confidence=MappingConfidence.UNKNOWN, risk=MappingRisk.HIGH),
            TechnologyMapping(source_technology="VSAM", source_construct="KSDS/ESDS/RRDS", target_technology="PostgreSQL", target_construct="relational table", mapping_kind=MappingKind.REVIEW_REQUIRED, description="VSAM datasets require data modeling review", confidence=MappingConfidence.UNKNOWN, risk=MappingRisk.HIGH),
        ]

    def find_mapping(self, source_tech: str, construct: str) -> list[TechnologyMapping]:
        sl = source_tech.lower(); cl = construct.lower()
        return [m for m in self._mappings if m.source_technology.lower() == sl and (cl in m.source_construct.lower() or m.source_construct.lower() in cl)]

    def report(self) -> dict[str, Any]:
        return {"total": len(self._mappings), "direct": len([m for m in self._mappings if m.mapping_kind == MappingKind.DIRECT]), "review_required": len([m for m in self._mappings if m.mapping_kind == MappingKind.REVIEW_REQUIRED])}


class ModernizationMetrics(BaseModel):
    metrics_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    project_id: str = ""; generated_at: datetime = Field(default_factory=_utc_now)
    total_files: int = 0; total_LOC: int = 0; physical_LOC: int = 0
    deterministic_files: int = 0; deterministic_LOC: int = 0
    analyzer_files: int = 0; analyzer_LOC: int = 0
    LLM_analyzed_files: int = 0; LLM_analyzed_LOC: int = 0
    loc_by_technology: dict[str, int] = Field(default_factory=dict)
    files_by_technology: dict[str, int] = Field(default_factory=dict)
    planned_files: int = 0; planned_LOC: int = 0
    transformed_files: int = 0; transformed_LOC: int = 0
    blocked_files: int = 0; blocked_LOC: int = 0
    review_required_files: int = 0; review_required_LOC: int = 0
    failed_files: int = 0; failed_LOC: int = 0; rolled_back_files: int = 0
    LLM_calls: int = 0; LLM_tokens_in: int = 0; LLM_tokens_out: int = 0
    LLM_latency_ms: float = 0.0; parallel_LLM_calls: int = 0; serial_LLM_calls: int = 0
    RAG_calls: int = 0; RAG_latency_ms: float = 0.0
    wall_clock_time_ms: float = 0.0
    start_time: datetime | None = None; end_time: datetime | None = None

    @property
    def transformation_throughput_loc_per_hour(self) -> float:
        if self.wall_clock_time_ms <= 0: return 0.0
        h = self.wall_clock_time_ms / 3600000.0
        return self.transformed_LOC / h if h > 0 else 0.0

    @property
    def analysis_throughput_loc_per_hour(self) -> float:
        if self.wall_clock_time_ms <= 0: return 0.0
        h = self.wall_clock_time_ms / 3600000.0
        return (self.deterministic_LOC + self.analyzer_LOC + self.LLM_analyzed_LOC) / h if h > 0 else 0.0

    def summary(self) -> dict[str, Any]:
        return {"total_files": self.total_files, "total_LOC": self.total_LOC, "transformed_files": self.transformed_files, "transformed_LOC": self.transformed_LOC, "LLM_calls": self.LLM_calls, "wall_clock_ms": self.wall_clock_time_ms, "throughput_loc_per_hour": self.transformation_throughput_loc_per_hour}


class ProductionOutput(BaseModel):
    output_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    generated_at: datetime = Field(default_factory=_utc_now); version: str = "1.0.0"
    repository_identity: str = ""; repository_path: str = ""; source_integrity_checksum: str = ""
    start_time: datetime | None = None; end_time: datetime | None = None; elapsed_seconds: float | None = None
    total_files: int = 0; total_LOC: int = 0; physical_LOC: int = 0
    technologies: list[str] = Field(default_factory=list)
    technology_coverage: dict[str, Any] = Field(default_factory=dict)
    business_analysis_summary: str = ""; business_findings: list[str] = Field(default_factory=list)
    capability_state: dict[str, str] = Field(default_factory=dict); tooling_state: dict[str, str] = Field(default_factory=dict)
    LLM_calls: int = 0; LLM_tokens_in: int = 0; LLM_tokens_out: int = 0
    LLM_latency_ms: float = 0.0; parallel_LLM_calls: int = 0; serial_LLM_calls: int = 0; RAG_calls: int = 0
    planned_files: int = 0; planned_LOC: int = 0; transformed_files: int = 0; transformed_LOC: int = 0
    blocked_files: int = 0; blocked_LOC: int = 0; review_required_files: int = 0; review_required_LOC: int = 0
    failed_files: int = 0; failed_LOC: int = 0; rolled_back_files: int = 0
    transformation_throughput_loc_per_hour: float = 0.0; analysis_throughput_loc_per_hour: float = 0.0
    estimated_completion: str = "NOT_AVAILABLE"; remaining_LOC: int = 0; remaining_files: int = 0
    human_decisions_required: int = 0; human_decision_topics: list[str] = Field(default_factory=list)
    capability_gaps: list[str] = Field(default_factory=list)
    remaining_unsupported_workload: str = ""; final_status: str = "UNKNOWN"; verdict: str = ""


    def to_text(self) -> str:
        lines = ["PHASE 18-G.3 — REAL MODERNIZATION PRODUCTION OUTPUT", "=" * 60,
            f"Generated: {self.generated_at.isoformat()}", f"Repository: {self.repository_identity}",
            f"Start: {self.start_time.isoformat() if self.start_time else 'N/A'}",
            f"Elapsed: {self.elapsed_seconds:.2f}s" if self.elapsed_seconds else "Elapsed: N/A",
            "", "SIZING", "-" * 40, f"Files: {self.total_files}", f"LOC: {self.total_LOC}",
            "", "TECHNOLOGIES", "-" * 40]
        for t in self.technologies: lines.append(f"  - {t}")
        lines += ["", "INFERENCE", "-" * 40, f"LLM calls: {self.LLM_calls}",
            f"LLM tokens: {self.LLM_tokens_in} in / {self.LLM_tokens_out} out",
            f"LLM latency: {self.LLM_latency_ms:.1f}ms", f"RAG calls: {self.RAG_calls}",
            "", "TRANSFORMATION", "-" * 40,
            f"Planned: {self.planned_files} files ({self.planned_LOC} LOC)",
            f"Transformed: {self.transformed_files} files ({self.transformed_LOC} LOC)",
            f"Blocked: {self.blocked_files} files ({self.blocked_LOC} LOC)",
            f"Review-required: {self.review_required_files} files ({self.review_required_LOC} LOC)",
            f"Failed: {self.failed_files} files ({self.failed_LOC} LOC)",
            "", "THROUGHPUT", "-" * 40,
            f"Transformation: {self.transformation_throughput_loc_per_hour:.1f} LOC/hour",
            f"Analysis: {self.analysis_throughput_loc_per_hour:.1f} LOC/hour",
            f"ETA: {self.estimated_completion}",
            "", "HUMAN DECISIONS", "-" * 40, f"Required: {self.human_decisions_required}"]
        for t in self.human_decision_topics: lines.append(f"  - {t}")
        lines += ["", "FINAL STATUS", "-" * 40, f"Status: {self.final_status}", f"Verdict: {self.verdict}", "=" * 60]
        return "\n".join(lines)

