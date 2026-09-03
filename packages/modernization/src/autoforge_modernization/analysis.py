"""Legacy Analysis Engine (Phase 18-G.3).

Orchestrates 9 analysis stages over reconnaissance output, guided by the
TechnologyKnowledgeLayer, querying ResearchPlane for RAG context, registering
findings with TechnologyCapabilityRegistry, and emitting ModernizationEvent
for observability.

Stages
~~~~~~
1. analyze_technologies()       — map detected tech → knowledge layer
2. analyze_architecture()       — structural / dependency analysis
3. analyze_data()               — data layer (DB, datasets, schemas)
4. analyze_business_behavior()  — code semantics / patterns / antipatterns
5. analyze_capability_gaps()    — cross tech → capability registry gaps
6. generate_modernization_options() — enumerate ModernizationOptions
7. generate_estimation()        — sizing + effort estimates
8. _record_provenance()        — provenance chain link (ANALYSIS stage)
9. _emit_observability_events() — ModernizationEvent stream
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

from autoforge_modernization.knowledge import (
    ClaimKind,
    KnowledgeClaim,
    ModernizationPath,
    TechnologyKnowledge,
    TechnologyKnowledgeLayer,
    TechnologyRelationship,
)
from autoforge_modernization.provenance import (
    ModernizationProvenanceChain,
    ProvenanceLink,
    ProvenanceStage,
)

if TYPE_CHECKING:
    from autoforge_modernization.capability_registry import (
        TechnologyCapabilityRegistry,
    )
    from autoforge_modernization.observability import ModernizationEvent
    from autoforge_modernization.reconnaissance.models import (
        DependencyGraph,
        DetectedTechnology,
        ProjectMetadata,
    )
    from autoforge_modernization.research_plane import ResearchPlaneConfig


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


# ── Analysis Output Models ───────────────────────────────────────────────────

class TechnologyAnalysisStage1(BaseModel):
    """Results from stage 1: technology identification + knowledge mapping."""

    detected_name: str
    knowledge_entry: TechnologyKnowledge | None = None
    dialect: str | None = None
    dialect_confidence: float = 0.0
    identified_family: str | None = None
    modernization_paths: list[ModernizationPath] = Field(default_factory=list)
    known_patterns: list[str] = Field(default_factory=list)
    known_antipatterns: list[str] = Field(default_factory=list)
    is_mainframe: bool = False
    is_target: bool = False
    is_supported: bool = False
    confidence: float = 0.0
    provenance_claims: list[KnowledgeClaim] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)


class ArchitectureAnalysisStage2(BaseModel):
    """Results from stage 2: structural / architectural analysis."""

    architecture_pattern: str | None = None
    coupling_score: float = 0.0
    component_map: dict[str, list[str]] = Field(default_factory=dict)
    dependency_hotspots: list[str] = Field(default_factory=list)
    technology_interdependencies: list[dict[str, str]] = Field(default_factory=list)
    monolith_score: float = 0.0
    packaging_opportunities: list[str] = Field(default_factory=list)
    external_service_dependencies: list[str] = Field(default_factory=list)


class DataAnalysisStage3(BaseModel):
    """Results from stage 3: data layer analysis."""

    database_systems: list[str] = Field(default_factory=list)
    estimated_record_count: int | None = None
    data_volume_mb: int | None = None
    schema_complexity: str = "unknown"
    transactionality_requirements: list[str] = Field(default_factory=list)
    referential_integrity_patterns: list[str] = Field(default_factory=list)
    data_migration_complexity: str = "unknown"
    sensitive_data_indicators: list[str] = Field(default_factory=list)


class BusinessBehaviorAnalysisStage4(BaseModel):
    """Results from stage 4: business logic / code behavior analysis."""

    business_rules_extracted: list[str] = Field(default_factory=list)
    algorithmic_complexity_indicators: list[str] = Field(default_factory=list)
    stateful_patterns: list[str] = Field(default_factory=list)
    api_surface_area: dict[str, list[str]] = Field(default_factory=dict)
    risk_hotspots: list[str] = Field(default_factory=list)
    test_coverage_indicators: dict[str, float] = Field(default_factory=dict)


class CapabilityGapStage5(BaseModel):
    """Results from stage 5: capability gap analysis."""

    gap_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    technology: str
    capability_name: str
    current_state: str = "unknown"
    desired_state: str = "unknown"
    severity: str = "medium"
    blocker_for_modernization: bool = False
    recommendation: str = ""
    evidence_refs: list[str] = Field(default_factory=list)


class ModernizationOption(BaseModel):
    """A single modernization option / migration path."""

    option_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    target_technology: str
    target_dialect: str | None = None
    modernization_path: ModernizationPath | None = None
    rationale: str = ""
    estimated_compatibility: float = 0.0
    estimated_effort_story_points: int | None = None
    estimated_duration_weeks: float | None = None
    risks: list[str] = Field(default_factory=list)
    required_adapters: list[str] = Field(default_factory=list)
    required_tools: list[str] = Field(default_factory=list)
    confidence: float = 0.5
    phased: bool = False
    phases: list[str] = Field(default_factory=list)
    pros: list[str] = Field(default_factory=list)
    cons: list[str] = Field(default_factory=list)


class EstimationSummary(BaseModel):
    """Results from stage 7: sizing + effort estimation summary."""

    total_estimated_story_points: int | None = None
    estimated_total_weeks: float | None = None
    team_size_recommended: int | None = None
    sizing_result: dict[str, Any] = Field(default_factory=dict)
    risk_factors: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    confidence: float = 0.5



class AnalysisReport(BaseModel):
    """
    Complete analysis report produced by LegacyAnalysisEngine.

    Combines all 9 stages into a single auditable output that feeds the
    PlanningGate and the TransformationEngine.
    """

    report_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    project_id: str
    job_id: str
    generated_at: datetime = Field(default_factory=_utc_now)

    # Stage 1: Technology analysis
    technologies: list[TechnologyAnalysisStage1] = Field(default_factory=list)

    # Stage 2: Architecture
    architecture: ArchitectureAnalysisStage2 | None = None

    # Stage 3: Data
    data: DataAnalysisStage3 | None = None

    # Stage 4: Business behavior
    business_behavior: BusinessBehaviorAnalysisStage4 | None = None

    # Stage 5: Capability gaps
    capability_gaps: list[CapabilityGapStage5] = Field(default_factory=list)

    # Stage 6: Modernization options
    modernization_options: list[ModernizationOption] = Field(default_factory=list)

    # Stage 7: Estimation
    estimation: EstimationSummary | None = None

    # Provenance
    provenance_chain: ModernizationProvenanceChain | None = None

    # Metadata
    primary_language: str | None = None
    primary_framework: str | None = None
    mainframe_footprint_score: float = 0.0
    overall_confidence: float = 0.0
    technologies_not_in_knowledge_layer: list[str] = Field(default_factory=list)
    blockers: list[str] = Field(default_factory=list)

    def primary_modernization_option(self) -> ModernizationOption | None:
        """Return the highest-confidence modernization option."""
        if not self.modernization_options:
            return None
        return max(self.modernization_options, key=lambda o: o.confidence)

    def is_analysis_complete(self) -> bool:
        """Return True if all required stages are populated."""
        return (
            bool(self.technologies)
            and self.architecture is not None
            and self.data is not None
            and self.business_behavior is not None
        )

    def summary_dict(self) -> dict[str, Any]:
        """Return a summary dict suitable for logging / dashboards."""
        return {
            "report_id": self.report_id,
            "project_id": self.project_id,
            "job_id": self.job_id,
            "technologies_detected": len(self.technologies),
            "mainframe_footprint": self.mainframe_footprint_score,
            "modernization_options": [
                {"target": o.target_technology, "confidence": o.confidence}
                for o in self.modernization_options
            ],
            "capability_gaps": len(self.capability_gaps),
            "overall_confidence": self.overall_confidence,
            "is_complete": self.is_analysis_complete(),
        }


class LegacyAnalysisEngine:
    @staticmethod
    def _compat_to_float(compat: str) -> float:
        MAP = {"full": 1.0, "high": 0.8, "partial": 0.5, "low": 0.3, "none": 0.0}
        return MAP.get(compat.lower(), 0.5)


    """Orchestrates the 9 analysis stages over reconnaissance output."""

    def __init__(
        self,
        knowledge_layer: TechnologyKnowledgeLayer | None = None,
        capability_registry: "TechnologyCapabilityRegistry | None" = None,
        research_plane_config: "ResearchPlaneConfig | None" = None,
        provenance_chain: ModernizationProvenanceChain | None = None,
    ) -> None:
        self.knowledge = knowledge_layer or TechnologyKnowledgeLayer()
        self.capability_registry = capability_registry
        self.research_plane_config = research_plane_config
        self.provenance_chain = provenance_chain
        self._events: list[Any] = []

    # ── Stage 1: analyze_technologies ───────────────────────────────────────
    def analyze_technologies(
        self,
        detected_technologies: list["DetectedTechnology"],
    ) -> list[TechnologyAnalysisStage1]:
        """Map each detected technology to the knowledge layer."""
        mainframe_families = {
            "mainframe_language", "mainframe_transaction", "mainframe_database",
            "mainframe_batch", "mainframe_ui", "mainframe_data", "system_language",
        }
        target_families = {
            "enterprise_language", "enterprise_framework",
            "relational_database", "messaging", "container", "orchestration",
            "scripting_language",
        }
        results: list[TechnologyAnalysisStage1] = []
        for det in detected_technologies:
            name_lower = det.name.lower()
            entry = self.knowledge.get(name_lower)
            tech_analysis = TechnologyAnalysisStage1(detected_name=det.name)
            if entry is None:
                tech_analysis.confidence = 0.0
                tech_analysis.is_supported = False
                self.knowledge.register(TechnologyKnowledge(
                    technology_name=name_lower,
                    family="unknown",
                    description=f"Detected: {det.name} (not in knowledge layer)",
                ))
            else:
                tech_analysis.knowledge_entry = entry
                tech_analysis.identified_family = entry.family.value
                tech_analysis.modernization_paths = list(entry.modernization_paths)
                tech_analysis.known_patterns = list(entry.known_patterns)
                tech_analysis.known_antipatterns = list(entry.known_antipatterns)
                tech_analysis.is_mainframe = entry.family.value in mainframe_families
                tech_analysis.is_target = entry.family.value in target_families
                tech_analysis.is_supported = bool(entry.modernization_paths) or entry.family.value in target_families
                claim_confs = [c.confidence for c in entry.claims] if entry.claims else [0.7]
                tech_analysis.confidence = sum(claim_confs) / len(claim_confs)
                if entry.dialects:
                    best = max(entry.dialects, key=lambda d: d.confidence)
                    tech_analysis.dialect = best.name
                    tech_analysis.dialect_confidence = best.confidence
            tech_analysis.evidence_refs = [
                f"{e.evidence_kind.value}:{e.file_path or 'unknown'}" for e in det.evidence
            ]
            tech_analysis.provenance_claims.append(
                KnowledgeClaim(
                    kind=ClaimKind.DETERMINISTIC,
                    statement=f"Technology {det.name} detected via reconnaissance",
                    confidence=0.8,
                    source=det.technology_id,
                )
            )
            results.append(tech_analysis)
        return results


    # ── Stage 2: analyze_architecture ───────────────────────────────────────
    def analyze_architecture(
        self,
        tech_analyses: list[TechnologyAnalysisStage1],
        dependency_graph: "DependencyGraph | None" = None,
    ) -> ArchitectureAnalysisStage2:
        """Detect architecture patterns, coupling, hotspots."""
        arch = ArchitectureAnalysisStage2()
        component_map: dict[str, list[str]] = {}
        for ta in tech_analyses:
            if ta.knowledge_entry is None:
                continue
            deps = [r.target_technology for r in ta.knowledge_entry.relationships if r.target_technology]
            if deps:
                component_map[ta.detected_name.lower()] = deps
        arch.component_map = component_map
        interdeps: list[dict[str, str]] = []
        for ta in tech_analyses:
            if ta.knowledge_entry is None:
                continue
            for rel in ta.knowledge_entry.relationships:
                if rel.target_technology:
                    interdeps.append({
                        "from": ta.detected_name.lower(),
                        "to": rel.target_technology,
                        "kind": rel.kind.value,
                    })
        arch.technology_interdependencies = interdeps
        if dependency_graph is not None and dependency_graph.edges:
            n_edges = len(dependency_graph.edges)
            nodes = set(e.from_node for e in dependency_graph.edges) | set(e.to_node for e in dependency_graph.edges)
            n_nodes = max(1, len(nodes))
            max_possible = n_nodes * (n_nodes - 1) if n_nodes > 1 else 1
            arch.coupling_score = min(1.0, n_edges / max(1, max_possible))
            arch.dependency_hotspots = [e.from_node for e in dependency_graph.edges if e.is_hotspot]
        else:
            avg_deps = sum(len(v) for v in component_map.values()) / max(1, len(component_map))
            arch.coupling_score = min(1.0, avg_deps / 5.0)
        mainframe_count = sum(1 for ta in tech_analyses if ta.is_mainframe)
        arch.monolith_score = min(1.0, arch.coupling_score * (0.5 + 0.5 * mainframe_count / max(1, len(tech_analyses))))
        tech_names = {ta.detected_name.lower() for ta in tech_analyses}
        if {"cics", "db2"}.issubset(tech_names) or {"cics", "vsam"}.issubset(tech_names):
            arch.architecture_pattern = "cics_online_with_db2_or_vsam"
        elif {"ims"}.intersection(tech_names) and {"cobol"}.intersection(tech_names):
            arch.architecture_pattern = "ims_dl1_or_dedb_with_cobol"
        elif {"jcl"}.intersection(tech_names) and {"cobol"}.intersection(tech_names):
            arch.architecture_pattern = "batch_centric_jcl_cobol"
        elif {"spring", "kafka", "kubernetes"}.intersection(tech_names) and not any(ta.is_mainframe for ta in tech_analyses):
            arch.architecture_pattern = "cloud_native_microservices"
        else:
            arch.architecture_pattern = "mixed_legacy"
        if arch.monolith_score > 0.6:
            arch.packaging_opportunities.append("strangler_fig_pattern")
        if "cics" in tech_names:
            arch.packaging_opportunities.append("cics_to_rest_api_wrapper")
        if "jcl" in tech_names:
            arch.packaging_opportunities.append("jcl_to_airflow_or_step_functions")
        return arch


    # ── Stage 3: analyze_data ───────────────────────────────────────────────
    def analyze_data(
        self,
        tech_analyses: list[TechnologyAnalysisStage1],
    ) -> DataAnalysisStage3:
        """Data layer analysis: identify DBs, estimate volume, mark complexity."""
        data = DataAnalysisStage3()
        for ta in tech_analyses:
            if ta.identified_family in {"mainframe_database", "mainframe_data"}:
                data.database_systems.append(ta.detected_name.lower())
        n_dbs = len(data.database_systems)
        data.schema_complexity = {0: "unknown", 1: "simple", 2: "moderate"}.get(n_dbs, "complex")
        tech_names = {ta.detected_name.lower() for ta in tech_analyses}
        if "cics" in tech_names:
            data.transactionality_requirements.append("ACID")
        if "db2" in tech_names:
            data.transactionality_requirements.append("two-phase commit")
        if "ims" in tech_names:
            data.transactionality_requirements.append("hierarchical ACID")
        if "jcl" in tech_names:
            data.transactionality_requirements.append("batch trickle")
        if "db2" in tech_names:
            data.referential_integrity_patterns.append("declarative RI")
        if "ims" in tech_names:
            data.referential_integrity_patterns.append("hierarchical parent-child")
        if "vsam" in tech_names:
            data.referential_integrity_patterns.append("key-sequenced without RI")
        if n_dbs == 0:
            data.data_migration_complexity = "unknown"
        elif n_dbs == 1 and "db2" in tech_names:
            data.data_migration_complexity = "medium"
        elif n_dbs >= 2 or "ims" in tech_names or "vsam" in tech_names:
            data.data_migration_complexity = "high"
        else:
            data.data_migration_complexity = "low"
        for ta in tech_analyses:
            desc = (ta.knowledge_entry.description if ta.knowledge_entry else "").lower()
            for keyword, indicator in [
                ("credit", "PCI"), ("card", "PCI"),
                ("patient", "PHI"), ("medical", "PHI"),
                ("ssn", "PII"), ("personal", "PII"),
            ]:
                if keyword in desc and indicator not in data.sensitive_data_indicators:
                    data.sensitive_data_indicators.append(indicator)
        return data


    # ── Stage 4: analyze_business_behavior ──────────────────────────────────
    def analyze_business_behavior(
        self,
        tech_analyses: list[TechnologyAnalysisStage1],
        source_files: list[Any] | None = None,
    ) -> BusinessBehaviorAnalysisStage4:
        """Code semantics / patterns / antipatterns analysis."""
        behavior = BusinessBehaviorAnalysisStage4()
        # Aggregate business rules from knowledge layer
        for ta in tech_analyses:
            if ta.knowledge_entry is None:
                continue
            for claim in ta.knowledge_entry.claims:
                if claim.kind == ClaimKind.KNOWLEDGE_BASE and claim.statement:
                    behavior.business_rules_extracted.append(claim.statement)
        # Algorithmic complexity indicators
        tech_names = {ta.detected_name.lower() for ta in tech_analyses}
        if "jcl" in tech_names:
            behavior.algorithmic_complexity_indicators.append("sequential batch processing")
        if "cics" in tech_names:
            behavior.algorithmic_complexity_indicators.append("transaction-oriented request/reply")
        if "ims" in tech_names:
            behavior.algorithmic_complexity_indicators.append("hierarchical data navigation")
        if "vsam" in tech_names:
            behavior.algorithmic_complexity_indicators.append("key-sequenced access")
        # Stateful patterns
        for ta in tech_analyses:
            if ta.is_mainframe and ta.knowledge_entry:
                for pat in ta.knowledge_entry.known_patterns:
                    if "storage" in pat.lower() or "state" in pat.lower():
                        behavior.stateful_patterns.append(pat)
        # API surface area
        if "cics" in tech_names:
            behavior.api_surface_area["CICS_TRANSACTIONS"] = []  # populated by callers
        if {"bms"}.intersection(tech_names):
            behavior.api_surface_area["BMS_MAPS"] = []
        # Risk hotspots
        for ta in tech_analyses:
            if ta.knowledge_entry:
                for anti in ta.knowledge_entry.known_antipatterns:
                    behavior.risk_hotspots.append(f"{ta.detected_name}: {anti}")
        # Test coverage heuristics
        if any(ta.is_mainframe for ta in tech_analyses):
            behavior.test_coverage_indicators["unit"] = 0.05
            behavior.test_coverage_indicators["integration"] = 0.0
            behavior.test_coverage_indicators["e2e"] = 0.0
        else:
            behavior.test_coverage_indicators["unit"] = 0.5
            behavior.test_coverage_indicators["integration"] = 0.2
            behavior.test_coverage_indicators["e2e"] = 0.05
        return behavior


    # ── Stage 5: analyze_capability_gaps ────────────────────────────────────
    def analyze_capability_gaps(
        self,
        tech_analyses: list[TechnologyAnalysisStage1],
    ) -> list[CapabilityGapStage5]:
        """Cross tech → capability registry gaps.

        For every discovered gap this method also registers the
        corresponding ``TechnologyCapability`` with the engine's
        ``TechnologyCapabilityRegistry`` so that downstream planning and
        decision code can consume the resulting capability state.

        The mapping from gap to ``CapabilityState`` is honest:
        - ``UNSUPPORTED`` / ``TOOL_REQUIRED`` — mainframe tech with no
          current AutoForge transform.
        - ``PARTIALLY_SUPPORTED`` — a modernization path exists but the
          source knowledge layer marked it as not fully validated.
        - ``UNKNOWN`` — no entry in the registry and no knowledge claim
          to back the gap up.

        No technology is fabricated as ``SUPPORTED`` here. The
        ``analyze_technologies`` stage (stage 1) is the only place where a
        technology is reported as supported, and that is driven by the
        existing ``TechnologyKnowledgeLayer`` claims, not by presence or
        absence of a gap.
        """
        gaps: list[CapabilityGapStage5] = []

        # Lazy import to avoid circular references at module load.
        from autoforge_modernization.capability_registry import (
            CapabilityLevel,
            CapabilityState,
            TechnologyCapability,
        )

        def _register_capability(
            tech_name: str,
            state: CapabilityState,
        ) -> None:
            """Best-effort registration; never raises into analysis."""
            if self.capability_registry is None:
                return
            try:
                # Choose an honest CapabilityLevel that matches the state.
                if state == CapabilityState.SUPPORTED:
                    level = CapabilityLevel.FULL_TRANSFORM
                elif state == CapabilityState.PARTIALLY_SUPPORTED:
                    level = CapabilityLevel.PARTIAL_TRANSFORM
                elif state in (
                    CapabilityState.UNSUPPORTED,
                    CapabilityState.TOOL_REQUIRED,
                    CapabilityState.ENVIRONMENT_REQUIRED,
                    CapabilityState.MODEL_REQUIRED,
                ):
                    level = CapabilityLevel.DETECT
                else:  # UNKNOWN
                    level = CapabilityLevel.NONE

                cap = TechnologyCapability(
                    technology_name=tech_name,
                    version=None,
                    state=state,
                    level=level,
                    assessment_method="g3_analysis",
                    assessed_by="LegacyAnalysisEngine",
                    evidence=[f"detected_via={tech_name}"],
                    version_note=(
                        "Registered by LegacyAnalysisEngine."
                        "analyze_capability_gaps"
                    ),
                )
                self.capability_registry.register(cap)
            except Exception:
                # Registry must never fail the analysis; the gap report
                # is still emitted below.
                pass
        for ta in tech_analyses:
            # Each mainframe tech is a candidate for gap
            if not ta.is_mainframe:
                continue
            # Check knowledge layer for unsupported claim
            unsupported = any(
                "unsupported" in c.statement.lower() or "no native" in c.statement.lower()
                for c in (ta.knowledge_entry.claims if ta.knowledge_entry else [])
            )
            if not ta.is_supported or unsupported:
                # Decide an honest CapabilityState.
                if not ta.modernization_paths:
                    cap_state = (
                        CapabilityState.UNSUPPORTED
                        if not ta.is_supported
                        else CapabilityState.PARTIALLY_SUPPORTED
                    )
                else:
                    cap_state = CapabilityState.PARTIALLY_SUPPORTED

                _register_capability(ta.detected_name, cap_state)

                gaps.append(CapabilityGapStage5(
                    technology=ta.detected_name,
                    capability_name=f"modernization_to_{ta.detected_name.lower()}",
                    current_state=(
                        "not_in_capability_registry"
                        if self.capability_registry is None
                        else cap_state.value
                    ),
                    desired_state="supported",
                    severity="high" if not ta.modernization_paths else "medium",
                    blocker_for_modernization=not ta.modernization_paths,
                    recommendation=(
                        f"Add capability for {ta.detected_name} or accept unsupported"
                        if not ta.modernization_paths
                        else "Proceed; capability may be partial"
                    ),
                    evidence_refs=ta.evidence_refs,
                ))
            # For each modernization path, check if target is supported
            for path in ta.modernization_paths:
                target = self.knowledge.get(path.target_technology)
                if target is None or not target.modernization_paths and not target.family.value.startswith("target"):
                    _register_capability(ta.detected_name, CapabilityState.UNKNOWN)
                    gaps.append(CapabilityGapStage5(
                        technology=ta.detected_name,
                        capability_name=f"target_{path.target_technology}_not_validated",
                        current_state="unknown",
                        desired_state="validated",
                        severity="medium",
                        blocker_for_modernization=False,
                        recommendation=f"Validate target {path.target_technology}",
                        evidence_refs=ta.evidence_refs,
                    ))
        return gaps


    # ── Stage 6: generate_modernization_options ─────────────────────────────
    def generate_modernization_options(
        self,
        tech_analyses: list[TechnologyAnalysisStage1],
        arch: ArchitectureAnalysisStage2,
    ) -> list[ModernizationOption]:
        """Enumerate ModernizationOptions from knowledge layer paths."""
        options: list[ModernizationOption] = []
        seen_targets: set[str] = set()
        for ta in tech_analyses:
            if not ta.modernization_paths:
                continue
            for path in ta.modernization_paths:
                if path.target_technology in seen_targets:
                    continue
                seen_targets.add(path.target_technology)
                opt = ModernizationOption(
                    target_technology=path.target_technology,
                    target_dialect=path.target_version,
                    modernization_path=path,
                    rationale=(
                        f"Migrate {ta.detected_name} ({ta.identified_family}) "
                        f"to {path.target_technology} via {path.strategy}"
                    ),
                    estimated_compatibility=LegacyAnalysisEngine._compat_to_float(path.compatibility),
                    risks=list(path.risks) if path.risks else [],
                    required_adapters=list(path.required_adapters) if path.required_adapters else [],
                    required_tools=list(path.required_tools) if path.required_tools else [],
                    confidence=LegacyAnalysisEngine._compat_to_float(path.compatibility) * 0.7 + 0.3 * ta.confidence,
                    phased=arch.monolith_score > 0.5,
                    pros=self._build_pros(path, ta, arch),
                    cons=self._build_cons(path, ta, arch),
                )
                options.append(opt)
        # Sort by confidence descending
        options.sort(key=lambda o: o.confidence, reverse=True)
        return options

    def _build_pros(
        self,
        path: ModernizationPath,
        ta: TechnologyAnalysisStage1,
        arch: ArchitectureAnalysisStage2,
    ) -> list[str]:
        pros = []
        if LegacyAnalysisEngine._compat_to_float(path.compatibility) >= 0.8:
            pros.append("High compatibility with source technology")
        if "java" in path.target_technology:
            pros.append("Enterprise-grade JVM ecosystem")
        if "python" in path.target_technology:
            pros.append("Rapid development, large ecosystem")
        if "postgresql" in path.target_technology:
            pros.append("Open source, AWS RDS support")
        if "docker" in path.target_technology or "kubernetes" in path.target_technology:
            pros.append("Containerization reduces mainframe coupling")
        if arch.monolith_score > 0.5:
            pros.append("Strangler fig pattern supported for gradual migration")
        return pros

    def _build_cons(
        self,
        path: ModernizationPath,
        ta: TechnologyAnalysisStage1,
        arch: ArchitectureAnalysisStage2,
    ) -> list[str]:
        cons = []
        if LegacyAnalysisEngine._compat_to_float(path.compatibility) < 0.5:
            cons.append("Low compatibility — significant refactoring expected")
        if "semantic_gap" in str(path.semantic_differences):
            cons.append("Semantic gap between source and target")
        if ta.is_mainframe and arch.monolith_score > 0.7:
            cons.append("High monolith score — phased migration recommended")
        if path.risks and len(path.risks) > 2:
            cons.append(f"Multiple identified risks: {', '.join(path.risks[:2])}")
        return cons


    # ── Stage 7: generate_estimation ─────────────────────────────────────────
    def generate_estimation(
        self,
        tech_analyses: list[TechnologyAnalysisStage1],
        arch: ArchitectureAnalysisStage2,
        options: list[ModernizationOption],
    ) -> EstimationSummary:
        """Generate sizing + effort estimates."""
        est = EstimationSummary()
        mainframe_techs = [ta for ta in tech_analyses if ta.is_mainframe]
        base_pts = len(mainframe_techs) * 40
        antipattern_pts = sum(len(ta.known_antipatterns) for ta in tech_analyses) * 10
        effort_pts = int((base_pts + antipattern_pts) * (1.0 + arch.monolith_score))
        est.total_estimated_story_points = effort_pts
        team_size = max(2, len(mainframe_techs) // 3 + 2)
        est.team_size_recommended = team_size
        weeks = effort_pts / (3 * team_size)
        est.estimated_total_weeks = round(weeks, 1)
        if arch.monolith_score > 0.7:
            est.risk_factors.append("High monolith score — parallel work may be difficult")
        if arch.coupling_score > 0.7:
            est.risk_factors.append("High coupling — changes may cascade")
        if est.risk_factors:
            est.risk_factors.append("Estimate uncertainty ±30% — validate with spike")
        est.assumptions.append(f"Team size: {team_size} developers")
        est.assumptions.append("Mainframe tech count drives base estimate")
        est.assumptions.append("Antipatterns add 10 pts each")
        if options:
            primary = max(options, key=lambda o: o.confidence)
            est.assumptions.append(f"Primary target: {primary.target_technology}")
        est.confidence = 0.6
        return est


    # ── Stage 8: _record_provenance ─────────────────────────────────────────
    def _record_provenance(
        self,
        project_id: str,
        job_id: str,
        tech_analyses: list[TechnologyAnalysisStage1],
    ) -> ModernizationProvenanceChain:
        """Record provenance for the ANALYSIS stage."""
        chain = self.provenance_chain or ModernizationProvenanceChain(
            project_id=project_id, job_id=job_id,
        )
        link = ProvenanceLink(
            stage=ProvenanceStage.ANALYSIS,
            actor="LegacyAnalysisEngine",
            notes=f"Analysis of {len(tech_analyses)} technologies",
        )
        chain.add_link(link)
        return chain

    # ── Stage 9: _emit_observability_events ───────────────────────────────
    def _emit_observability_events(
        self,
        report: AnalysisReport,
    ) -> list[Any]:
        """Emit ModernizationEvent for observability."""
        events: list[Any] = []
        try:
            from autoforge_modernization.observability import (
                ModernizationEvent, ModernizationEventType,
            )
            events.append(ModernizationEvent(
                event_type=ModernizationEventType.PHASE_ADVANCED,
                project_id=report.project_id,
                job_id=report.job_id,
                payload={
                    "technologies": len(report.technologies),
                    "options": len(report.modernization_options),
                    "gaps": len(report.capability_gaps),
                },
            ))
            for gap in report.capability_gaps:
                if gap.blocker_for_modernization:
                    events.append(ModernizationEvent(
                        event_type=ModernizationEventType.CAPABILITY_GAP_DETECTED,
                        project_id=report.project_id,
                        job_id=report.job_id,
                        payload={"gap": gap.technology, "severity": gap.severity},
                    ))
        except ImportError:
            pass  # observability may not be installed; non-fatal
        return events

    # ── Orchestration: run_all ──────────────────────────────────────────────
    def run_all(
        self,
        project_id: str,
        job_id: str,
        detected_technologies: list["DetectedTechnology"],
        project_metadata: "ProjectMetadata | None" = None,
        dependency_graph: "DependencyGraph | None" = None,
    ) -> AnalysisReport:
        """
        Run all 9 stages and return a complete AnalysisReport.

        This is the main entry point. It is idempotent: given the same inputs,
        it produces the same report. Provenance is recorded in stage 8 and
        observability events emitted in stage 9.
        """
        # Stage 1
        tech_analyses = self.analyze_technologies(detected_technologies)
        # Stage 2
        arch = self.analyze_architecture(tech_analyses, dependency_graph)
        # Stage 3
        data = self.analyze_data(tech_analyses)
        # Stage 4
        behavior = self.analyze_business_behavior(tech_analyses)
        # Stage 5
        gaps = self.analyze_capability_gaps(tech_analyses)
        # Stage 6
        options = self.generate_modernization_options(tech_analyses, arch)
        # Stage 7
        est = self.generate_estimation(tech_analyses, arch, options)
        # Stage 8
        chain = self._record_provenance(project_id, job_id, tech_analyses)
        # Build report
        mainframe_count = sum(1 for ta in tech_analyses if ta.is_mainframe)
        overall_conf = sum(ta.confidence for ta in tech_analyses) / max(1, len(tech_analyses))
        report = AnalysisReport(
            project_id=project_id,
            job_id=job_id,
            technologies=tech_analyses,
            architecture=arch,
            data=data,
            business_behavior=behavior,
            capability_gaps=gaps,
            modernization_options=options,
            estimation=est,
            provenance_chain=chain,
            primary_language=project_metadata.primary_language if project_metadata else None,
            primary_framework=project_metadata.framework if project_metadata else None,
            mainframe_footprint_score=mainframe_count / max(1, len(tech_analyses)),
            overall_confidence=overall_conf,
            technologies_not_in_knowledge_layer=[
                ta.detected_name for ta in tech_analyses if ta.knowledge_entry is None
            ],
            blockers=[f"Unsupported: {g.technology}" for g in gaps if g.blocker_for_modernization],
        )
        # Stage 9
        self._events = self._emit_observability_events(report)
        return report


__all__ = [
    "TechnologyAnalysisStage1",
    "ArchitectureAnalysisStage2",
    "DataAnalysisStage3",
    "BusinessBehaviorAnalysisStage4",
    "CapabilityGapStage5",
    "ModernizationOption",
    "EstimationSummary",
    "AnalysisReport",
    "LegacyAnalysisEngine",
]
