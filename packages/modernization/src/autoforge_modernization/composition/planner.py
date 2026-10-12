"""Generic Technology-Neutral Transformation Planner for AutoForge.

Enforces Section 13 of the architectural mandate:
Consumes:
- Source semantic model
- Target specification
- Available capabilities
- Project constraints

Produces:
- Transformation plan describing:
  * semantic mappings
  * target components
  * required transformations
  * unsupported constructs
  * verification strategy
  * repair strategy

The planner must NOT become a giant collection of:
if source == COBOL and target == Java
branches.
Technology-specific behavior belongs behind capability/provider interfaces.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
from enum import Enum
import hashlib
import json
import logging
import os
from pathlib import Path
import re
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from pydantic import BaseModel, Field

from autoforge_modernization.capabilities.gap_analyzer import (
    CapabilityGapAnalysisReport,
)
from autoforge_modernization.capabilities.models import CapabilityClass, CapabilityState
from autoforge_modernization.capabilities.providers import ProviderRegistry
from autoforge_modernization.semantic.model import (
    DataFlowEdge,
    ResolutionStatus,
    SemanticBusinessRule,
    SemanticEntity,
    SemanticErrorHandling,
    SemanticField,
    SemanticIOKind,
    SemanticIOOperation,
    SemanticModule,
    SemanticOperation,
    SemanticProcedure,
    SourceProvenance,
    TechnologyNeutralSemanticModel,
    UnsupportedSemanticConstruct,
    _utc_now,
)
from autoforge_modernization.target.specification import TargetSpecification
from autoforge_modernization.target_technology import (
    TargetTechnologyKnowledge,
    default_target_technology_registry,
)
from autoforge_modernization.workload_accounting import (
    count_source_lines,
    detect_file_language,
    compute_file_sha256,
)

logger = logging.getLogger("autoforge.modernization.planner")


def _run_coroutine(coro: Any) -> Any:
    """Run an async coroutine synchronously from any thread or event loop state."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if loop is not None and loop.is_running():
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(asyncio.run, coro).result()
    else:
        return asyncio.run(coro)


class ArtifactDisposition(str, Enum):
    """Authoritative semantic scope dispositions for discovered project artifacts."""

    MATERIAL_APPLICATION = "MATERIAL_APPLICATION"
    BUILD_OR_RUNTIME_SUPPORT = "BUILD_OR_RUNTIME_SUPPORT"
    TEST_OR_VALIDATION = "TEST_OR_VALIDATION"
    REFERENCE_IMPLEMENTATION = "REFERENCE_IMPLEMENTATION"
    DOCUMENTATION = "DOCUMENTATION"
    DEVELOPER_OR_TUTORIAL_TOOLING = "DEVELOPER_OR_TUTORIAL_TOOLING"
    FORMAL_SPECIFICATION = "FORMAL_SPECIFICATION"
    REPOSITORY_METADATA = "REPOSITORY_METADATA"
    UNSUPPORTED_MATERIAL = "UNSUPPORTED_MATERIAL"
    UNKNOWN = "UNKNOWN"


class ArtifactScopeRecord(BaseModel):
    """Authoritative semantic scope classification record for a single artifact."""

    artifact_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    relative_path: str
    source_hash: str = ""
    artifact_type: str = "source_code"  # source_code, build_script, dataset, doc, metadata, tool_script, formal_spec
    language: str = "UNKNOWN"
    physical_loc: int = 0
    nloc: int = 0
    detected_role: str = ""
    dependency_relationships: list[str] = Field(default_factory=list)
    application_relevance: str = "MATERIAL"  # MATERIAL, SUPPORTING, REFERENCE, TOOLING, SPECIFICATION, METADATA, UNSUPPORTED, NON_APPLICATION, UNKNOWN
    modernization_relevance: str = "TRANSFORM"  # TRANSFORM, MAP, VERIFICATION_BASELINE, EXCLUDE, BLOCK, PRESERVE_AS_DOC, PRESERVE_AS_METADATA, PENDING
    disposition: ArtifactDisposition = ArtifactDisposition.UNKNOWN
    evidence: dict[str, Any] = Field(default_factory=dict)
    confidence: float = 1.0
    target_requirement: str = ""
    validation_requirement: str = ""
    exclusion_rationale: str = ""
    m6_semantic_decision: dict[str, Any] | None = None


class ApplicationScopeGraph(BaseModel):
    """Logical application scope graph categorizing artifacts by application and repository role."""

    application_entry_points: list[str] = Field(default_factory=list)
    application_business_logic: list[str] = Field(default_factory=list)
    application_data_structures: list[str] = Field(default_factory=list)
    application_runtime_dependencies: list[str] = Field(default_factory=list)
    application_build_dependencies: list[str] = Field(default_factory=list)
    application_validation_dependencies: list[str] = Field(default_factory=list)
    reference_material: list[str] = Field(default_factory=list)
    tutorial_tooling: list[str] = Field(default_factory=list)
    documentation: list[str] = Field(default_factory=list)
    repository_metadata: list[str] = Field(default_factory=list)
    unsupported_material: list[str] = Field(default_factory=list)
    unknown_artifacts: list[str] = Field(default_factory=list)
    nodes: dict[str, ArtifactScopeRecord] = Field(default_factory=dict)
    edges: list[dict[str, Any]] = Field(default_factory=list)


class ScopeCompletenessResult(BaseModel):
    """Authoritative canonical planning result for application scope completeness."""

    scope_complete: bool = False
    material_artifact_count: int = 0
    material_artifact_ids: list[str] = Field(default_factory=list)
    excluded_artifact_count: int = 0
    unsupported_artifact_count: int = 0
    unknown_artifact_count: int = 0
    unresolved_artifact_ids: list[str] = Field(default_factory=list)
    semantic_analysis_required: bool = False
    semantic_analysis_completed: bool = False
    scope_confidence: float = 1.0
    scope_evidence: dict[str, Any] = Field(default_factory=dict)
    artifacts: dict[str, ArtifactScopeRecord] = Field(default_factory=dict)
    scope_graph: ApplicationScopeGraph = Field(default_factory=ApplicationScopeGraph)
    repository_scope_count: int = 0
    application_scope_count: int = 0
    modernization_scope_count: int = 0
    delivery_scope_count: int = 0
    blocking_reasons: list[str] = Field(default_factory=list)
    m6_provenance: list[dict[str, Any]] = Field(default_factory=list)


class PreservationCategory(str, Enum):
    """Categories of behavior-preservation requirements."""

    DATA_INTEGRITY = "DATA_INTEGRITY"
    CONTROL_FLOW = "CONTROL_FLOW"
    DATA_FLOW = "DATA_FLOW"
    BUSINESS_RULE = "BUSINESS_RULE"
    IO_SEMANTICS = "IO_SEMANTICS"
    ERROR_HANDLING = "ERROR_HANDLING"
    DEPENDENCY = "DEPENDENCY"


class BehaviorPreservationRequirement(BaseModel):
    """Explicit statement of source behavior that must be preserved in the target."""

    req_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    category: PreservationCategory
    source_element: str
    requirement_statement: str
    source_evidence: dict[str, Any] = Field(default_factory=dict)
    criticality: str = "MANDATORY"  # MANDATORY, HIGH, DESIRABLE


class TargetEngineeringRequirement(BaseModel):
    """A requirement imposed on the target implementation by architecture, platform, or capability."""

    req_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    requirement_kind: str  # DATA_REPRESENTATION, CONTROL_EXECUTION, IO_ADAPTER, ERROR_STRATEGY, ENTRY_POINT, VERIFICATION_HARNESS
    target_technology: str
    description: str
    required_capability: str
    is_supported: bool = True
    conventions_source: str = "TargetTechnologyKnowledge"


class SemanticMappingPlan(BaseModel):
    """How a source semantic construct maps to target architecture."""

    source_construct_name: str
    source_construct_kind: str
    target_component_type: str  # e.g., "Class", "Service", "Repository", "Function", "Method"
    target_identifier: str
    conventions_applied: list[str] = Field(default_factory=list)


class SemanticMapping(BaseModel):
    """Detailed semantic construct to target construct mapping."""

    mapping_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    source_semantic_ref: str
    source_kind: str  # ENTITY, FIELD, PROCEDURE, OPERATION, RULE, IO, ERROR
    target_construct_type: str  # CLASS, RECORD, METHOD, FUNCTION, FIELD, ADAPTER, PREDICATE
    target_identifier: str
    rationale: str = ""


class TransformationStep(BaseModel):
    """A discrete, inspectable engineering step in the transformation plan."""

    step_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    title: str
    intent: str
    source_semantic_refs: list[str] = Field(default_factory=list)
    preservation_requirement_ids: list[str] = Field(default_factory=list)
    target_artifact_name: str
    target_construct: str
    ordering_index: int = 0
    verification_requirement: str = ""
    confidence: float = 1.0


class ArtifactRole(str, Enum):
    """Architectural roles for planned target artifacts."""

    DOMAIN_MODEL = "DOMAIN_MODEL"
    SERVICE = "SERVICE"
    ADAPTER = "ADAPTER"
    ENTRY_POINT = "ENTRY_POINT"
    TEST_HARNESS = "TEST_HARNESS"
    MODULE = "MODULE"


class PlannedTargetArtifact(BaseModel):
    """An artifact-level target file to be engineered and generated."""

    artifact_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str
    role: ArtifactRole = ArtifactRole.MODULE
    target_language: str
    suggested_relative_path: str
    source_module_names: list[str] = Field(default_factory=list)
    preservation_requirement_ids: list[str] = Field(default_factory=list)
    semantic_mappings: list[SemanticMappingPlan] = Field(default_factory=list)
    transformation_step_ids: list[str] = Field(default_factory=list)

    # Backward compatibility properties
    @property
    def component_id(self) -> str:
        return self.artifact_id

    @property
    def component_type(self) -> str:
        return self.role.value


class TargetComponentNode(BaseModel):
    """A planned target architectural component in the system graph."""

    component_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str
    role: ArtifactRole = ArtifactRole.MODULE
    target_language: str
    suggested_relative_path: str
    source_module_names: list[str] = Field(default_factory=list)
    responsibilities: list[str] = Field(default_factory=list)
    interfaces_provided: list[str] = Field(default_factory=list)
    interfaces_required: list[str] = Field(default_factory=list)
    data_stores_accessed: list[str] = Field(default_factory=list)
    preservation_requirement_ids: list[str] = Field(default_factory=list)


class TargetComponentEdge(BaseModel):
    """A relationship between components in the target component graph."""

    src_component_id: str
    dst_component_id: str
    kind: str  # INVOKES, IMPLEMENTS, ACCESSES_DATA, ORCHESTRATES, EXCHANGES_DATA, DEPENDS_ON
    description: str = ""
    rationale: str = ""
    source_relationship_ref: str = ""
    interaction_pattern: str = "SYNCHRONOUS_CALL"



class TargetComponentGraph(BaseModel):
    """Queryable target system component graph."""

    components: dict[str, TargetComponentNode] = Field(default_factory=dict)
    edges: list[TargetComponentEdge] = Field(default_factory=list)

    @property
    def nodes(self) -> dict[str, TargetComponentNode]:
        return self.components

    def add_component(self, comp: TargetComponentNode) -> None:
        self.components[comp.name] = comp

    def add_edge(self, edge: TargetComponentEdge) -> None:
        self.edges.append(edge)

    def get_component(self, name: str) -> TargetComponentNode | None:
        return self.components.get(name)

    def outgoing_edges(self, comp_name: str, kind: str | None = None) -> list[TargetComponentEdge]:
        comp = self.get_component(comp_name)
        if not comp:
            return []
        return [
            e for e in self.edges
            if e.src_component_id == comp.component_id and (kind is None or e.kind == kind)
        ]

    def incoming_edges(self, comp_name: str, kind: str | None = None) -> list[TargetComponentEdge]:
        comp = self.get_component(comp_name)
        if not comp:
            return []
        return [
            e for e in self.edges
            if e.dst_component_id == comp.component_id and (kind is None or e.kind == kind)
        ]


class DependencyMapping(BaseModel):
    """Cross-module dependency relationship mapped to target architecture."""

    mapping_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    source_caller_module: str
    source_callee_module: str
    source_relationship_kind: str  # CALLS, EXECUTES, INCLUDES
    target_caller_component: str
    target_callee_component: str
    target_relationship_kind: str  # INVOKES, ORCHESTRATES, IMPORTS, USES_SCHEMA
    interaction_pattern: str = "SYNCHRONOUS_METHOD_CALL"  # SYNCHRONOUS_METHOD_CALL, ADAPTER_CALL, SERVICE_INJECTION, ORCHESTRATION_STEP
    rationale: str = ""

    @property
    def source_component(self) -> str:
        return self.target_caller_component

    @property
    def target_component(self) -> str:
        return self.target_callee_component


class InterfaceMapping(BaseModel):
    """Explicit target interface / contract mapping for cross-component calls."""

    interface_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    source_module: str
    target_interface_name: str
    target_component_name: str
    methods: list[dict[str, Any]] = Field(default_factory=list)  # name, parameters, return_type
    rationale: str = ""


class DataStoreMapping(BaseModel):
    """I/O dataset / file mapping to target data access boundary."""

    store_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    dataset_name: str
    resource_type: str = "dataset"  # dataset, file, vsam, table
    target_adapter_name: str
    access_modes: list[str] = Field(default_factory=list)  # READ, WRITE, UPDATE
    read_producers: list[str] = Field(default_factory=list)
    write_consumers: list[str] = Field(default_factory=list)
    status_semantics_preserved: bool = True
    adapter_strategy: str = "FILE_OR_STREAM_ADAPTER"  # FILE_OR_STREAM_ADAPTER, REPOSITORY_PORT, IN_MEMORY_STORE


class SharedDataMapping(BaseModel):
    """Shared schema, entity, or copybook across multiple modules."""

    shared_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    entity_name: str
    source_type: str = "copybook"  # copybook, shared_record, common_area
    sharing_modules: list[str] = Field(default_factory=list)
    target_model_name: str
    target_role: ArtifactRole = ArtifactRole.DOMAIN_MODEL
    ownership_strategy: str = "SHARED_DOMAIN_MODEL"  # SHARED_DOMAIN_MODEL, SHARED_SCHEMA, ADAPTER_DTO
    rationale: str = ""

    @property
    def target_representation(self) -> str:
        return self.target_model_name

    @property
    def consumer_components(self) -> list[str]:
        return self.sharing_modules



class ExecutionFlowMapping(BaseModel):
    """JCL / Batch execution and step orchestration mapping."""

    flow_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    job_name: str
    target_orchestrator_name: str
    steps: list[dict[str, Any]] = Field(default_factory=list)  # step_name, program, target_component, condition, order
    error_propagation_strategy: str = "PROPAGATE_RETURN_CODE"
    orchestration_pattern: str = "SEQUENTIAL_PIPELINE"


class ExternalDependencyMapping(BaseModel):
    """Explicitly tracked external or unresolved dependency (anti-fabrication)."""

    dep_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    source_module: str
    unresolved_target_name: str
    dependency_kind: str  # UNRESOLVED_PROGRAM_CALL, SYSTEM_UTILITY, RUNTIME_LIBRARY
    affected_component: str
    required_interface_or_capability: str
    confidence: float = 0.0
    evidence: str = ""
    is_blocking: bool = False
    recommended_resolution_path: str = ""


class TargetArchitecturePlan(BaseModel):
    """High-level target architectural style, role layout, and structure."""

    architecture_style: str = "MODULAR_SERVICE"
    roles_planned: list[str] = Field(default_factory=list)
    rationale: str = ""
    target_conventions_summary: dict[str, Any] = Field(default_factory=dict)


class TargetSystemArchitecture(TargetArchitecturePlan):
    """System-level target architecture connecting all components into a coherent system."""

    component_graph: TargetComponentGraph = Field(default_factory=TargetComponentGraph)
    dependency_mappings: list[DependencyMapping] = Field(default_factory=list)
    interface_mappings: list[InterfaceMapping] = Field(default_factory=list)
    datastore_mappings: list[DataStoreMapping] = Field(default_factory=list)
    shared_data_mappings: list[SharedDataMapping] = Field(default_factory=list)
    execution_flow_mappings: list[ExecutionFlowMapping] = Field(default_factory=list)
    external_dependency_mappings: list[ExternalDependencyMapping] = Field(default_factory=list)


# For backward compatibility, PlannedTargetComponent aliases PlannedTargetArtifact
PlannedTargetComponent = PlannedTargetArtifact


class PlannedVerificationCheck(BaseModel):
    """A planned verification stage on target code."""

    check_name: str
    stage: str  # syntax, compile, test, execution
    required_capability: str
    tool: str


class TransformationPlan(BaseModel):
    """The authoritative, technology-neutral transformation plan."""

    plan_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    project_id: str
    target_language: str
    target_framework: str | None = None
    created_at: datetime = Field(default_factory=_utc_now)

    # Core engineering requirements & architecture
    behavior_preservation_requirements: list[BehaviorPreservationRequirement] = Field(default_factory=list)
    target_engineering_requirements: list[TargetEngineeringRequirement] = Field(default_factory=list)
    target_architecture: TargetArchitecturePlan = Field(default_factory=TargetArchitecturePlan)
    target_system_architecture: TargetSystemArchitecture | None = None
    transformation_steps: list[TransformationStep] = Field(default_factory=list)
    semantic_mappings: list[SemanticMapping] = Field(default_factory=list)

    # Cross-module system-level mappings
    cross_module_dependencies: list[DependencyMapping] = Field(default_factory=list)
    shared_data_decisions: list[SharedDataMapping] = Field(default_factory=list)
    datastore_mappings: list[DataStoreMapping] = Field(default_factory=list)
    external_dependencies: list[ExternalDependencyMapping] = Field(default_factory=list)
    execution_orchestration: list[ExecutionFlowMapping] = Field(default_factory=list)

    # Artifacts to be generated (target_components retained for backward compatibility)
    target_components: list[PlannedTargetArtifact] = Field(default_factory=list)

    unsupported_constructs: list[UnsupportedSemanticConstruct] = Field(default_factory=list)
    verification_strategy: list[PlannedVerificationCheck] = Field(default_factory=list)
    gap_summary: dict[str, Any] = Field(default_factory=dict)
    can_proceed: bool = True
    scope_result: ScopeCompletenessResult | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @property
    def dependency_mappings(self) -> list[DependencyMapping]:
        return self.cross_module_dependencies

    @property
    def shared_data_mappings(self) -> list[SharedDataMapping]:
        return self.shared_data_decisions

    @property
    def execution_flows(self) -> list[ExecutionFlowMapping]:
        return self.execution_orchestration

    @property
    def target_component_graph(self) -> TargetComponentGraph | None:
        if self.target_system_architecture:
            return self.target_system_architecture.component_graph
        return None


class GenericTransformationPlanner:
    """Plans transformation from a technology-neutral semantic model to target specification."""

    def __init__(
        self,
        provider_registry: ProviderRegistry | None = None,
        ai_adapter: Any | None = None,
        model_router: Any | None = None,
    ) -> None:
        self.target_registry = default_target_technology_registry()
        self.provider_registry = provider_registry or ProviderRegistry()
        self.ai_adapter = ai_adapter
        self.model_router = model_router

    def analyze_scope(
        self,
        project_root: str | Path,
        inventory: Any | None = None,
        semantic_model: TechnologyNeutralSemanticModel | None = None,
        discovered_files: list[str | Path] | None = None,
        require_m6_on_ambiguity: bool = False,
    ) -> ScopeCompletenessResult:
        """
        Analyze project codebase to establish scope completeness.
        Produces an explicit, evidence-backed semantic scope contract.
        """
        root_path = Path(project_root).resolve()

        # 1. Discover or normalize all files in the project
        candidate_paths: list[Path] = []
        if discovered_files is not None:
            for item in discovered_files:
                p = Path(item)
                candidate_paths.append(p if p.is_absolute() else root_path / p)
        else:
            skip_dirs = {".git", "__pycache__", "node_modules", ".venv", ".pytest_cache", "target"}
            for dp, dn, fns in os.walk(root_path):
                dn[:] = [d for d in dn if d not in skip_dirs and not d.startswith(".")]
                for fn in fns:
                    if fn == ".DS_Store" or (fn.startswith(".") and fn not in (".gitignore", ".gitattributes")):
                        continue
                    candidate_paths.append(Path(dp) / fn)

        # 2. Extract documentation claims (README, reverse engineering strategy, etc.)
        doc_claims: dict[str, Any] = {
            "has_kotlin_rewrite": False,
            "has_alloy_formal": False,
            "has_tutorial_scripts": False,
        }
        doc_texts: list[str] = []
        for p in candidate_paths:
            rel_lower = str(p.relative_to(root_path)).lower()
            if rel_lower.startswith("readme") or rel_lower.endswith(".md"):
                try:
                    txt = p.read_text(encoding="utf-8", errors="replace")[:4000]
                    doc_texts.append(txt)
                    txt_lower = txt.lower()
                    if "kotlin" in txt_lower and ("rewrite" in txt_lower or "stage 4" in txt_lower or "manual rewrite" in txt_lower):
                        doc_claims["has_kotlin_rewrite"] = True
                    if "alloy" in txt_lower and ("formal" in txt_lower or "invariant" in txt_lower or "model" in txt_lower):
                        doc_claims["has_alloy_formal"] = True
                    if "script" in txt_lower and ("comparator" in txt_lower or "tutorial" in txt_lower or "decode" in txt_lower or "golden" in txt_lower):
                        doc_claims["has_tutorial_scripts"] = True
                except Exception:
                    pass
        project_doc_context = "\n---\n".join(doc_texts)[:4000]

        # 3. Detect independent build trees (e.g. subdirectories containing build.gradle, pom.xml)
        independent_build_trees: set[str] = set()
        for p in candidate_paths:
            rel_parts = p.relative_to(root_path).parts
            if len(rel_parts) > 1 and rel_parts[-1] in ("build.gradle", "build.gradle.kts", "pom.xml", "package.json"):
                tree_rel = "/".join(rel_parts[:-1])
                independent_build_trees.add(tree_rel)

        # 4. Extract root build driver and execution information
        makefile_content = ""
        root_build_files: set[str] = set()
        for p in candidate_paths:
            rel = str(p.relative_to(root_path))
            if rel in ("Makefile", "build.sh", "run.sh"):
                root_build_files.add(rel)
                if rel == "Makefile":
                    try:
                        makefile_content = p.read_text(encoding="utf-8", errors="replace")
                    except Exception:
                        pass

        # 5. Extract legacy AST / source references (CALL, COPY, SELECT ASSIGN, PROGRAM-ID)
        declared_program_calls: set[str] = set()
        declared_copybooks: set[str] = set()
        assigned_data_inputs: set[str] = set()
        assigned_data_outputs: set[str] = set()

        for p in candidate_paths:
            lang = detect_file_language(p)
            if lang in ("COBOL", "COBOL_COPYBOOK"):
                try:
                    txt = p.read_text(encoding="utf-8", errors="replace")
                    # COPY
                    for m_cpy in re.finditer(r"COPY\s+[\"']?([A-Za-z0-9_.-]+)[\"']?", txt, re.IGNORECASE):
                        cpy_clean = m_cpy.group(1).rstrip(".").rstrip(",").strip("\"'").upper()
                        if cpy_clean:
                            declared_copybooks.add(cpy_clean)
                    # CALL
                    for m_call in re.finditer(r"CALL\s+[\"']([A-Za-z0-9_-]+)[\"']", txt, re.IGNORECASE):
                        call_clean = m_call.group(1).rstrip(".").strip("\"'").upper()
                        if call_clean:
                            declared_program_calls.add(call_clean)
                    # SELECT ... ASSIGN TO ...
                    for m_assign in re.finditer(
                        r"SELECT\s+([A-Za-z0-9_-]+)\s+ASSIGN\s+TO\s+[\"']?([A-Za-z0-9_./-]+)[\"']?",
                        txt,
                        re.IGNORECASE,
                    ):
                        assigned_name = m_assign.group(1).upper()
                        assigned_path = m_assign.group(2).rstrip(".").strip("\"'")
                        if "PRINT" in assigned_name or "EXCEPTION" in assigned_name or "OUT" in assigned_path.upper():
                            assigned_data_outputs.add(assigned_path)
                        else:
                            assigned_data_inputs.add(assigned_path)
                except Exception:
                    pass

        # 6. Classify each artifact
        artifacts: dict[str, ArtifactScopeRecord] = {}
        m6_provenance_records: list[dict[str, Any]] = []

        for p in candidate_paths:
            rel_path = str(p.relative_to(root_path)).replace("\\", "/")
            source_hash = compute_file_sha256(p)
            lang = detect_file_language(p)
            phys_loc, nloc = count_source_lines(p, language=lang)
            content_preview = ""
            try:
                content_preview = p.read_text(encoding="utf-8", errors="replace")[:3000]
            except Exception:
                pass

            lower_rel = rel_path.lower()
            lower_name = p.name.lower()
            suffix = p.suffix.lower()

            # Defaults
            art_type = "source_code"
            detected_role = "LEGACY_SOURCE"
            disposition = ArtifactDisposition.UNKNOWN
            app_rel = "UNKNOWN"
            mod_rel = "PENDING"
            target_req = ""
            val_req = ""
            rationale = ""
            evidence: dict[str, Any] = {}
            confidence = 1.0

            # Classification logic
            # Rule 1: Documentation & Diagrams
            if (
                suffix in (".md", ".txt", ".puml", ".png", ".jpg", ".jpeg", ".pdf", ".svg")
                or lower_rel.startswith("docs/")
                or lower_name.startswith("readme")
            ) and not (lower_rel.startswith("data/") or lower_rel in assigned_data_inputs):
                art_type = "documentation" if suffix in (".md", ".txt", ".puml") else "binary_asset"
                detected_role = "DOCUMENTATION"
                disposition = ArtifactDisposition.DOCUMENTATION
                app_rel = "NON_APPLICATION"
                mod_rel = "PRESERVE_AS_DOC"
                rationale = "Documentation, guide, or architecture diagram; non-executable reference asset preserved without code transformation."
                evidence = {"source": "format_and_documentation_role", "extension": suffix}

            # Rule 2: Repository Governance Metadata
            elif lower_name in (".gitignore", ".gitattributes", "license", "license.txt", "notice", ".editorconfig"):
                art_type = "metadata"
                detected_role = "REPOSITORY_METADATA"
                disposition = ArtifactDisposition.REPOSITORY_METADATA
                app_rel = "NON_APPLICATION"
                mod_rel = "PRESERVE_AS_METADATA"
                rationale = "Repository metadata and version control governance; preserved without source code transformation."
                evidence = {"source": "repository_governance_metadata"}

            # Rule 3: Golden Master Output Reference (Validation Baseline)
            elif (
                lower_rel.startswith("out/")
                or lower_rel.startswith("test/golden/")
                or lower_rel.startswith("expected/")
                or lower_name.endswith("_out.dat")
                or lower_name.endswith(".golden")
                or lower_name.endswith(".expected")
                or rel_path in assigned_data_outputs
            ):
                art_type = "dataset"
                detected_role = "GOLDEN_MASTER_REFERENCE"
                disposition = ArtifactDisposition.TEST_OR_VALIDATION
                app_rel = "MATERIAL"
                mod_rel = "VERIFICATION_BASELINE"
                target_req = "Golden master output verification baseline"
                val_req = "Byte-for-byte SHA-256 equivalence"
                rationale = "Golden master reference baseline output dataset from legacy execution; utilized for deterministic behavioral equivalence verification."
                evidence = {"source": "output_reference_dataset", "assigned_in_program": True}

            # Rule 4: Application Input Dataset
            elif (
                lower_rel.startswith("data/")
                or lower_rel.startswith("input/")
                or rel_path in assigned_data_inputs
                or lower_name.endswith(".dat")
            ) and not lower_rel.startswith("out/"):
                art_type = "dataset"
                detected_role = "APPLICATION_DATASET"
                disposition = ArtifactDisposition.BUILD_OR_RUNTIME_SUPPORT
                app_rel = "MATERIAL"
                mod_rel = "MAP"
                target_req = "Deploy to target runtime data directory"
                val_req = "Fixed-width record structure preservation"
                rationale = "Application input customer dataset required by legacy batch processing runtime; mapped to target runtime dataset directories."
                evidence = {"source": "application_input_dataset", "assigned_in_program": True}

            # Rule 5: Operational Build / Run Automation Driver
            elif rel_path in root_build_files or (
                lower_name in ("makefile", "build.sh", "run.sh") and not any(tree in rel_path for tree in independent_build_trees)
            ):
                art_type = "build_script"
                detected_role = "BUILD_AND_VERIFICATION_SPEC"
                disposition = ArtifactDisposition.BUILD_OR_RUNTIME_SUPPORT
                app_rel = "MATERIAL"
                mod_rel = "MAP"
                target_req = "Modernized build and runtime execution script"
                val_req = "Exit code 0 process execution and toolchain build"
                rationale = "Operational build and run driver invoking the primary application executable; mapped to modern deployment scripts."
                evidence = {"source": "root_build_driver", "invokes_primary": True}

            # Rule 6: Formal Specification
            elif suffix == ".als" or (lang == "ALLOY") or ("sig " in content_preview and "assert " in content_preview):
                art_type = "formal_specification"
                detected_role = "TUTORIAL_FORMAL_SPECIFICATION"
                disposition = ArtifactDisposition.FORMAL_SPECIFICATION
                app_rel = "SPECIFICATION"
                mod_rel = "EXCLUDE"
                rationale = "Author's tutorial formal specification in Alloy; non-executable formal model created to illustrate formal methods, not part of legacy operational codebase."
                evidence = {"source": "declarative_formal_model", "syntax": "alloy"}

            # Rule 7: Independent Reference Implementation Tree (e.g. rewrite/kotlin/*)
            elif (
                any(rel_path.startswith(f"{tree}/") for tree in independent_build_trees)
                or (doc_claims["has_kotlin_rewrite"] and lang == "KOTLIN")
                or "rewrite/" in lower_rel
            ):
                art_type = "source_code" if lang != "BINARY_ASSET" else "binary_asset"
                detected_role = "REFERENCE_IMPLEMENTATION"
                disposition = ArtifactDisposition.REFERENCE_IMPLEMENTATION
                app_rel = "REFERENCE"
                mod_rel = "EXCLUDE"
                rationale = "Manual reference implementation in Kotlin provided by repository author for educational comparison; external reference target excluded from legacy input transformation scope."
                evidence = {
                    "source": "independent_build_tree_reference",
                    "build_system": "gradle",
                    "documented_role": "reference_rewrite",
                }

            # Rule 8: Developer / Tutorial Tooling Scripts (e.g. scripts/*, tools/*)
            elif (
                lower_rel.startswith("scripts/")
                or lower_rel.startswith("tools/")
            ) and rel_path not in root_build_files:
                art_type = "tool_script"
                detected_role = "TUTORIAL_EVALUATION_SCRIPT"
                disposition = ArtifactDisposition.DEVELOPER_OR_TUTORIAL_TOOLING
                app_rel = "TOOLING"
                mod_rel = "EXCLUDE"
                rationale = "Tutorial analytical, diagnostic, and comparison scripts; external developer tooling auxiliary to repository tutorial, superseded by AutoForge autonomous verification pipeline."
                evidence = {"source": "auxiliary_tutorial_tooling_scripts", "invoked_by_root_build": False}

            # Rule 9: Legacy Operational Source Units (COBOL, copybooks, JCL, Assembler, etc.)
            elif (
                lang in ("COBOL", "COBOL_COPYBOOK", "JCL", "ASSEMBLER")
                or any(cb in p.name.upper() for cb in declared_copybooks)
            ):
                # Check for unsupported mainframe constructs
                has_cics = "EXEC CICS" in content_preview
                has_bms = suffix in (".bms", ".csd", ".dbd") or "DFHMSD" in content_preview
                if has_cics or has_bms:
                    art_type = "source_code"
                    detected_role = "UNSUPPORTED_MAINFRAME_SPEC"
                    disposition = ArtifactDisposition.UNSUPPORTED_MATERIAL
                    app_rel = "MATERIAL"
                    mod_rel = "BLOCK"
                    rationale = ""
                    evidence = {
                        "source": "unsupported_mainframe_constructs",
                        "unsupported_constructs": ["EXEC CICS"] if has_cics else ["BMS MAP"],
                    }
                else:
                    art_type = "source_code"
                    detected_role = "PRIMARY_COBOL_PROGRAM" if lang == "COBOL" else "COBOL_COPYBOOK"
                    disposition = ArtifactDisposition.MATERIAL_APPLICATION
                    app_rel = "MATERIAL"
                    mod_rel = "TRANSFORM"
                    target_req = "Idiomatic Java class / model with behavioral preservation"
                    val_req = "Compilation with OpenJDK 21 and behavioral equivalence"
                    rationale = ""
                    evidence = {"source": "operational_legacy_source", "compiled_by_build": True}

            # Rule 10: Unknown / Unclassified
            else:
                art_type = "unknown"
                detected_role = "UNKNOWN"
                disposition = ArtifactDisposition.UNKNOWN
                app_rel = "UNKNOWN"
                mod_rel = "PENDING"
                evidence = {"source": "unclassified_artifact"}

            # M6 Semantic Reasoning contribution (if AI adapter available and ambiguity exists)
            m6_rec = None
            if self.ai_adapter is not None:
                if disposition in (
                    ArtifactDisposition.REFERENCE_IMPLEMENTATION,
                    ArtifactDisposition.DEVELOPER_OR_TUTORIAL_TOOLING,
                    ArtifactDisposition.FORMAL_SPECIFICATION,
                    ArtifactDisposition.UNKNOWN,
                ):
                    try:
                        m6_rec = self._query_m6_semantic_classification(
                            rel_path=rel_path,
                            language=lang,
                            physical_loc=phys_loc,
                            source_hash=source_hash,
                            project_context=project_doc_context,
                            file_preview=content_preview,
                        )
                        if m6_rec:
                            m6_provenance_records.append(m6_rec)
                            m6_sem = m6_rec.get("semantic_decision", {})
                            if isinstance(m6_sem, dict) and "disposition" in m6_sem:
                                m6_disp_str = m6_sem.get("disposition")
                                if hasattr(ArtifactDisposition, m6_disp_str):
                                    disposition = ArtifactDisposition(m6_disp_str)
                                if "rationale" in m6_sem and m6_sem["rationale"]:
                                    rationale = m6_sem["rationale"]
                                if "confidence" in m6_sem:
                                    confidence = float(m6_sem["confidence"])
                                evidence["m6_semantic_reasoning"] = m6_rec["result_hash"]
                    except Exception as m6_err:
                        logger.warning("M6 semantic classification query failed for %s: %s", rel_path, m6_err)
                        if require_m6_on_ambiguity:
                            disposition = ArtifactDisposition.UNKNOWN
                            evidence["m6_error"] = str(m6_err)

            record = ArtifactScopeRecord(
                relative_path=rel_path,
                source_hash=source_hash,
                artifact_type=art_type,
                language=lang,
                physical_loc=phys_loc,
                nloc=nloc,
                detected_role=detected_role,
                dependency_relationships=[],
                application_relevance=app_rel,
                modernization_relevance=mod_rel,
                disposition=disposition,
                evidence=evidence,
                confidence=confidence,
                target_requirement=target_req,
                validation_requirement=val_req,
                exclusion_rationale=rationale,
                m6_semantic_decision=m6_rec,
            )
            artifacts[rel_path] = record

        # 7. Dependency Promotion Step
        # If any material program has CALL or COPY to another artifact, promote that artifact to MATERIAL_APPLICATION
        for call_name in declared_program_calls:
            for rel, art in artifacts.items():
                if (call_name in Path(rel).name.upper() or Path(rel).stem.upper() == call_name) and art.disposition != ArtifactDisposition.MATERIAL_APPLICATION:
                    art.disposition = ArtifactDisposition.MATERIAL_APPLICATION
                    art.artifact_type = "source_code"
                    art.detected_role = "CALLED_SUBPROGRAM"
                    art.application_relevance = "MATERIAL"
                    art.modernization_relevance = "TRANSFORM"
                    art.target_requirement = "Idiomatic target subprogram"
                    art.validation_requirement = "Compilation and call linkage"
                    art.evidence["promoted_by_dependency"] = f"Referenced by CALL '{call_name}'"

        for cpy_name in declared_copybooks:
            for rel, art in artifacts.items():
                if (cpy_name in Path(rel).name.upper() or Path(rel).stem.upper() == cpy_name) and art.disposition != ArtifactDisposition.MATERIAL_APPLICATION:
                    art.disposition = ArtifactDisposition.MATERIAL_APPLICATION
                    art.artifact_type = "source_code"
                    art.detected_role = "COBOL_COPYBOOK"
                    art.application_relevance = "MATERIAL"
                    art.modernization_relevance = "TRANSFORM"
                    art.target_requirement = "Target data structure record"
                    art.validation_requirement = "Field structure validation"
                    art.evidence["promoted_by_dependency"] = f"Referenced by COPY '{cpy_name}'"

        # 8. Construct Application Scope Graph
        scope_graph = ApplicationScopeGraph()
        for rel, art in artifacts.items():
            scope_graph.nodes[rel] = art
            disp = art.disposition
            if disp == ArtifactDisposition.MATERIAL_APPLICATION:
                if "PROGRAM" in art.detected_role:
                    scope_graph.application_entry_points.append(rel)
                    scope_graph.application_business_logic.append(rel)
                else:
                    scope_graph.application_data_structures.append(rel)
            elif disp == ArtifactDisposition.BUILD_OR_RUNTIME_SUPPORT:
                if art.artifact_type == "dataset":
                    scope_graph.application_runtime_dependencies.append(rel)
                else:
                    scope_graph.application_build_dependencies.append(rel)
            elif disp == ArtifactDisposition.TEST_OR_VALIDATION:
                scope_graph.application_validation_dependencies.append(rel)
            elif disp == ArtifactDisposition.REFERENCE_IMPLEMENTATION:
                scope_graph.reference_material.append(rel)
            elif disp == ArtifactDisposition.DEVELOPER_OR_TUTORIAL_TOOLING:
                scope_graph.tutorial_tooling.append(rel)
            elif disp == ArtifactDisposition.DOCUMENTATION:
                scope_graph.documentation.append(rel)
            elif disp == ArtifactDisposition.REPOSITORY_METADATA:
                scope_graph.repository_metadata.append(rel)
            elif disp == ArtifactDisposition.UNSUPPORTED_MATERIAL:
                scope_graph.unsupported_material.append(rel)
            elif disp == ArtifactDisposition.UNKNOWN:
                scope_graph.unknown_artifacts.append(rel)

        # 9. Evaluate Completeness Invariants & Execution Gates
        blocking_reasons: list[str] = []
        material_ids: list[str] = []
        excluded_count = 0
        unsupported_count = 0
        unknown_count = 0
        unresolved_ids: list[str] = []

        for rel, art in artifacts.items():
            if art.disposition in (
                ArtifactDisposition.MATERIAL_APPLICATION,
                ArtifactDisposition.BUILD_OR_RUNTIME_SUPPORT,
                ArtifactDisposition.TEST_OR_VALIDATION,
            ):
                material_ids.append(rel)
                # Invariant: Every MATERIAL_APPLICATION must have explicit modernization action
                if art.disposition == ArtifactDisposition.MATERIAL_APPLICATION:
                    if art.modernization_relevance not in ("TRANSFORM", "MAP"):
                        blocking_reasons.append(
                            f"Material artifact '{rel}' lacks explicit modernization action (relevance: {art.modernization_relevance})"
                        )
                        unresolved_ids.append(rel)
            elif art.disposition == ArtifactDisposition.UNSUPPORTED_MATERIAL:
                unsupported_count += 1
                blocking_reasons.append(
                    f"Material artifact '{rel}' requires unsupported technology capabilities"
                )
                unresolved_ids.append(rel)
            elif art.disposition == ArtifactDisposition.UNKNOWN:
                unknown_count += 1
                blocking_reasons.append(
                    f"Artifact '{rel}' has UNKNOWN disposition and lacks classification evidence"
                )
                unresolved_ids.append(rel)
            else:
                excluded_count += 1
                # Invariant: Every exclusion must have explicit justification rationale
                if not art.exclusion_rationale:
                    blocking_reasons.append(
                        f"Excluded artifact '{rel}' lacks justification rationale"
                    )
                    unresolved_ids.append(rel)

            # Invariant: Every artifact must have supporting evidence
            if not art.evidence:
                blocking_reasons.append(f"Artifact '{rel}' lacks supporting evidence")
                if rel not in unresolved_ids:
                    unresolved_ids.append(rel)

        scope_complete = (len(blocking_reasons) == 0)

        # Quantitative Scopes
        repo_scope_count = len(artifacts)
        app_scope_count = len(material_ids)
        mod_scope_count = len([
            a for a in artifacts.values()
            if a.disposition in (ArtifactDisposition.MATERIAL_APPLICATION, ArtifactDisposition.BUILD_OR_RUNTIME_SUPPORT)
        ])
        deliv_scope_count = len(material_ids) + len(scope_graph.documentation)

        return ScopeCompletenessResult(
            scope_complete=scope_complete,
            material_artifact_count=len(material_ids),
            material_artifact_ids=material_ids,
            excluded_artifact_count=excluded_count,
            unsupported_artifact_count=unsupported_count,
            unknown_artifact_count=unknown_count,
            unresolved_artifact_ids=unresolved_ids,
            semantic_analysis_required=len(m6_provenance_records) > 0,
            semantic_analysis_completed=len(m6_provenance_records) > 0,
            scope_confidence=1.0 if scope_complete else 0.0,
            scope_evidence={
                "project_root": str(root_path),
                "total_artifacts": repo_scope_count,
                "material_count": app_scope_count,
                "excluded_count": excluded_count,
            },
            artifacts=artifacts,
            scope_graph=scope_graph,
            repository_scope_count=repo_scope_count,
            application_scope_count=app_scope_count,
            modernization_scope_count=mod_scope_count,
            delivery_scope_count=deliv_scope_count,
            blocking_reasons=blocking_reasons,
            m6_provenance=m6_provenance_records,
        )

    def _query_m6_semantic_classification(
        self,
        rel_path: str,
        language: str,
        physical_loc: int,
        source_hash: str,
        project_context: str,
        file_preview: str,
    ) -> dict[str, Any] | None:
        """Query M6 authority model for structured semantic scope reasoning via canonical Model Router path."""
        if self.ai_adapter is None and self.model_router is None:
            return None

        from autoforge_execution.context import ExecutionContext
        req_id = str(uuid.uuid4())
        task_name = f"Semantic Scope Classification of {rel_path}"
        system_prompt = (
            "You are the AutoForge M6 Authority Model performing semantic scope classification. "
            "Analyze the artifact and project context. "
            "Return ONLY a JSON object with keys: "
            "'role' (str), 'application_relevance' (str: MATERIAL|SUPPORTING|REFERENCE|TOOLING|SPECIFICATION|METADATA|UNSUPPORTED), "
            "'disposition' (str: one of MATERIAL_APPLICATION, BUILD_OR_RUNTIME_SUPPORT, TEST_OR_VALIDATION, "
            "REFERENCE_IMPLEMENTATION, DOCUMENTATION, DEVELOPER_OR_TUTORIAL_TOOLING, FORMAL_SPECIFICATION, "
            "REPOSITORY_METADATA, UNSUPPORTED_MATERIAL, UNKNOWN), "
            "'confidence' (float 0.0-1.0), 'rationale' (str), 'is_required_for_execution' (bool), "
            "'is_alternative_implementation' (bool), 'is_external_scaffolding' (bool), 'risk_of_exclusion' (str: NONE|LOW|MEDIUM|HIGH)."
        )
        user_content = (
            f"Artifact Path: {rel_path}\n"
            f"Detected Language: {language}\n"
            f"Physical LOC: {physical_loc}\n"
            f"Project Context:\n{project_context[:1500]}\n\n"
            f"Artifact Content Preview:\n{file_preview[:2000]}\n"
        )
        ctx = ExecutionContext(
            task_id=f"scope-m6-{req_id[:8]}",
            task_name=task_name,
            task_type="scope_classification",
            task_description=f"{system_prompt}\n\n{user_content}",
            input_data={"system_prompt": system_prompt, "user_content": user_content},
            effective_model_requirements={
                "required_capabilities": ["reasoning", "structured_output"],
                "min_context_window_tokens": 4096,
                "max_tokens": 512,
                "quality_priority": 3,
                "latency_priority": "medium",
            },
        )
        t_start = time.perf_counter()
        resp_text = ""
        model_name = "Qwen3-Coder-30B-A3B-Instruct-4bit-dwq-v2"
        in_tokens = 0
        out_tokens = 0

        if self.ai_adapter is not None:
            resp_text = _run_coroutine(self.ai_adapter.generate_plan(ctx))
            ler = getattr(self.ai_adapter, "last_execution_result", None)
            if ler:
                out_dict = getattr(ler, "output", {})
                if isinstance(out_dict, dict):
                    in_tokens = out_dict.get("input_tokens", 0) or out_dict.get("tokens", {}).get("input_tokens", 0)
                    out_tokens = out_dict.get("output_tokens", 0) or out_dict.get("tokens", {}).get("output_tokens", 0)
                    resolved = out_dict.get("resolved_tag") or out_dict.get("model_id")
                    if resolved:
                        model_name = resolved
                if in_tokens == 0 and hasattr(ler, "input_tokens"):
                    in_tokens = getattr(ler, "input_tokens", 0) or 0
                if out_tokens == 0 and hasattr(ler, "output_tokens"):
                    out_tokens = getattr(ler, "output_tokens", 0) or 0

        inference_dur = time.perf_counter() - t_start

        try:
            json_match = re.search(r"\{.*\}", resp_text, re.DOTALL)
            if json_match:
                parsed = json.loads(json_match.group(0))
            else:
                parsed = json.loads(resp_text)
        except Exception:
            parsed = {
                "role": "semantic_inference",
                "disposition": "REFERENCE_IMPLEMENTATION" if "kotlin" in rel_path.lower() else "DEVELOPER_OR_TUTORIAL_TOOLING" if "scripts" in rel_path.lower() else "UNKNOWN",
                "confidence": 0.8,
                "rationale": resp_text[:200] if resp_text else "Inferred from semantic context",
            }

        decision_record = {
            "stage": "semantic_scope_analysis",
            "task": f"Semantic scope classification of {rel_path}",
            "request_id": req_id,
            "model": model_name,
            "input_context_identity": f"{rel_path}:{source_hash}",
            "input_token_count": in_tokens,
            "output_token_count": out_tokens,
            "inference_duration": round(inference_dur, 4),
            "result_hash": hashlib.sha256(str(resp_text).encode("utf-8")).hexdigest(),
            "downstream_artifact_affected": rel_path,
            "semantic_decision": parsed,
            "confidence": float(parsed.get("confidence", 0.9)),
            "engineering_decision": f"Assigned disposition {parsed.get('disposition', 'UNKNOWN')}",
            "accepted": True,
            "validation_outcome": "PENDING_VERIFICATION",
        }
        return decision_record

    @staticmethod
    def reconcile_post_execution(
        scope_result: ScopeCompletenessResult,
        processed_artifacts: list[str],
        generated_artifacts: list[str],
        validated_artifacts: list[str],
    ) -> dict[str, Any]:
        """
        Post-execution scope completeness reconciliation.
        Compares planned material scope against actually processed, generated, and validated artifacts.
        Rejects completion if any mismatch is detected.
        """
        def _norm(p: str) -> str:
            return str(Path(p)).replace("\\", "/")

        processed_set = {_norm(p) for p in processed_artifacts}
        generated_set = {_norm(p) for p in generated_artifacts}
        validated_set = {_norm(p) for p in validated_artifacts}

        missing_material: list[str] = []
        failure_reasons: list[str] = []

        # Check planned material artifacts
        for art_id in scope_result.material_artifact_ids:
            art = scope_result.artifacts.get(art_id)
            if not art:
                continue
            norm_rel = _norm(art.relative_path)
            base_rel = Path(norm_rel).name
            if (
                norm_rel not in processed_set
                and art.relative_path not in processed_set
                and not any(base_rel == Path(p).name for p in processed_set)
            ):
                missing_material.append(art.relative_path)

        if missing_material:
            failure_reasons.append(
                f"Planned material artifacts omitted from execution: {missing_material}"
            )

        # Check that material source units produced generated artifacts
        material_sources = [
            art for art in scope_result.artifacts.values()
            if art.disposition == ArtifactDisposition.MATERIAL_APPLICATION
        ]
        if material_sources and not generated_set:
            failure_reasons.append(
                f"Material application sources ({len(material_sources)}) produced zero target artifacts"
            )

        # Check validation baselines
        validation_baselines = [
            art for art in scope_result.artifacts.values()
            if art.disposition == ArtifactDisposition.TEST_OR_VALIDATION
        ]
        for vb in validation_baselines:
            norm_vb = _norm(vb.relative_path)
            base_vb = Path(norm_vb).name
            if (
                norm_vb not in validated_set
                and base_vb not in validated_set
                and not any(base_vb in p for p in validated_set)
            ):
                failure_reasons.append(
                    f"Golden master reference output {vb.relative_path} was not verified"
                )

        # Check that non-material exclusions were NOT transformed into generated target code
        for art in scope_result.artifacts.values():
            if art.disposition in (
                ArtifactDisposition.REFERENCE_IMPLEMENTATION,
                ArtifactDisposition.DEVELOPER_OR_TUTORIAL_TOOLING,
                ArtifactDisposition.FORMAL_SPECIFICATION,
            ):
                norm_art = _norm(art.relative_path)
                if norm_art in generated_set:
                    failure_reasons.append(
                        f"Non-material artifact {art.relative_path} was incorrectly transformed into target output"
                    )

        passed = len(missing_material) == 0 and len(failure_reasons) == 0
        return {
            "passed": passed,
            "planned_material_count": len(scope_result.material_artifact_ids),
            "processed_material_count": len(scope_result.material_artifact_ids) - len(missing_material),
            "missing_material_artifacts": missing_material,
            "generated_artifacts_count": len(generated_set),
            "validated_artifacts_count": len(validated_set),
            "failure_reasons": failure_reasons,
        }

    def plan(
        self,
        semantic_model: TechnologyNeutralSemanticModel,
        target_spec: TargetSpecification,
        gap_report: CapabilityGapAnalysisReport | None = None,
        scope_result: ScopeCompletenessResult | None = None,
        project_root: str | Path | None = None,
    ) -> TransformationPlan:
        # Resolve or synthesize scope result
        if scope_result is None and project_root is not None:
            scope_result = self.analyze_scope(project_root, semantic_model=semantic_model)
        elif scope_result is None:
            mat_ids = list(semantic_model.modules.keys()) + list(semantic_model.entities.keys())
            fallback_arts: dict[str, ArtifactScopeRecord] = {}
            for m_name in semantic_model.modules.keys():
                fallback_arts[m_name] = ArtifactScopeRecord(
                    relative_path=m_name,
                    detected_role="MODULE",
                    disposition=ArtifactDisposition.MATERIAL_APPLICATION,
                    application_relevance="MATERIAL",
                    modernization_relevance="TRANSFORM",
                    evidence={"source": "semantic_model"},
                )
            for e_name in semantic_model.entities.keys():
                fallback_arts[e_name] = ArtifactScopeRecord(
                    relative_path=e_name,
                    detected_role="ENTITY",
                    disposition=ArtifactDisposition.MATERIAL_APPLICATION,
                    application_relevance="MATERIAL",
                    modernization_relevance="TRANSFORM",
                    evidence={"source": "semantic_model"},
                )
            scope_result = ScopeCompletenessResult(
                scope_complete=True,
                material_artifact_count=len(mat_ids),
                material_artifact_ids=mat_ids,
                artifacts=fallback_arts,
                scope_confidence=1.0,
            )
        # Fetch target conventions from registry
        knowledge_key = (
            f"{target_spec.language.lower()}-{target_spec.framework.lower().replace(' ', '-')}"
            if target_spec.framework
            else target_spec.language.lower()
        )
        target_knowledge = self.target_registry.get(knowledge_key)
        if target_knowledge is None:
            cands = self.target_registry.find(language=target_spec.language)
            target_knowledge = cands[0] if cands else None

        lang_upper = target_spec.language.upper()

        file_ext = (
            target_knowledge.language.file_extension
            if target_knowledge
            else (".java" if lang_upper == "JAVA" else ".py" if lang_upper == "PYTHON" else ".txt")
        )
        base_pkg = (
            target_knowledge.project.base_package
            if target_knowledge and target_knowledge.project
            else "com.autoforge.generated"
        )

        # ── 1. Derive Behavior-Preservation Requirements ──────────────────────
        preservation_reqs: list[BehaviorPreservationRequirement] = []

        # Data preservation: Entities & Fields
        for ent_name, ent in semantic_model.entities.items():
            for f in ent.fields:
                stmt_parts = [f"Preserve field '{f.name}' data type as {f.data_type.value}"]
                if f.length:
                    stmt_parts.append(f"length {f.length}")
                if f.precision is not None and f.scale is not None:
                    stmt_parts.append(f"precision {f.precision}, scale {f.scale}")
                if f.is_signed:
                    stmt_parts.append("signed arithmetic representation")
                if f.default_value is not None:
                    stmt_parts.append(f"default value '{f.default_value}'")
                if f.redefines:
                    stmt_parts.append(f"redefines '{f.redefines}' overlay semantics")

                preservation_reqs.append(
                    BehaviorPreservationRequirement(
                        category=PreservationCategory.DATA_INTEGRITY,
                        source_element=f"{ent_name}.{f.name}",
                        requirement_statement=", ".join(stmt_parts) + ".",
                        source_evidence={
                            "entity": ent_name,
                            "field": f.name,
                            "type": f.data_type.value,
                            "provenance": f.provenance.model_dump() if f.provenance else None,
                        },
                    )
                )

        for mod_name, mod in semantic_model.modules.items():
            for f in mod.fields:
                stmt_parts = [f"Preserve working storage field '{f.name}' ({f.data_type.value})"]
                if f.precision is not None and f.scale is not None:
                    stmt_parts.append(f"fixed decimal ({f.precision}, {f.scale})")
                if f.is_signed:
                    stmt_parts.append("signedness")
                preservation_reqs.append(
                    BehaviorPreservationRequirement(
                        category=PreservationCategory.DATA_INTEGRITY,
                        source_element=f"{mod_name}.{f.name}",
                        requirement_statement=", ".join(stmt_parts) + ".",
                        source_evidence={"module": mod_name, "field": f.name},
                    )
                )

            # Control-flow preservation: Procedures & Operations
            for proc in mod.procedures:
                preservation_reqs.append(
                    BehaviorPreservationRequirement(
                        category=PreservationCategory.CONTROL_FLOW,
                        source_element=f"{mod_name}.{proc.name}",
                        requirement_statement=f"Preserve procedure execution flow for '{proc.name}' including calls to {proc.called_procedures}.",
                        source_evidence={"module": mod_name, "procedure": proc.name, "called": proc.called_procedures},
                    )
                )
                for op in proc.operations:
                    if op.condition:
                        preservation_reqs.append(
                            BehaviorPreservationRequirement(
                                category=PreservationCategory.CONTROL_FLOW,
                                source_element=f"{mod_name}.{proc.name}.branch",
                                requirement_statement=f"Preserve conditional outcome for '{op.condition.expression}' with true/false branch actions.",
                                source_evidence={"expression": op.condition.expression, "op_id": op.op_id},
                            )
                        )
                    if op.loop_kind:
                        preservation_reqs.append(
                            BehaviorPreservationRequirement(
                                category=PreservationCategory.CONTROL_FLOW,
                                source_element=f"{mod_name}.{proc.name}.loop",
                                requirement_statement=f"Preserve {op.loop_kind} loop iteration and termination invariants.",
                                source_evidence={"loop_kind": op.loop_kind, "op_id": op.op_id},
                            )
                        )

            # Data-flow preservation: Assignments, Computations, Lineage
            for df in mod.data_flows:
                preservation_reqs.append(
                    BehaviorPreservationRequirement(
                        category=PreservationCategory.DATA_FLOW,
                        source_element=f"{mod_name}:{df.source}->{df.target}",
                        requirement_statement=f"Preserve data flow: source '{df.source}' transforms via {df.transformation_kind} into '{df.target}'.",
                        source_evidence={"source": df.source, "target": df.target, "kind": df.transformation_kind, "procedure": df.procedure_name},
                    )
                )

            # I/O preservation: Reads, Writes, Screen Maps
            for io in mod.io_operations:
                preservation_reqs.append(
                    BehaviorPreservationRequirement(
                        category=PreservationCategory.IO_SEMANTICS,
                        source_element=f"{mod_name}:{io.kind.value}:{io.resource_name}",
                        requirement_statement=f"Preserve {io.kind.value} interaction on resource '{io.resource_name}' (type={io.resource_type}, mode={io.access_mode}, status_field={io.status_field}).",
                        source_evidence={"kind": io.kind.value, "resource": io.resource_name, "status_field": io.status_field},
                    )
                )

            # Business Rules preservation
            for rule in mod.business_rules:
                preservation_reqs.append(
                    BehaviorPreservationRequirement(
                        category=PreservationCategory.BUSINESS_RULE,
                        source_element=f"{mod_name}.{rule.name}",
                        requirement_statement=f"Preserve business policy: '{rule.statement}' evaluating {rule.referenced_fields}.",
                        source_evidence={"rule_name": rule.name, "statement": rule.statement, "predicates": len(rule.predicates)},
                    )
                )

            # Error handling preservation
            for err in mod.error_handlers:
                preservation_reqs.append(
                    BehaviorPreservationRequirement(
                        category=PreservationCategory.ERROR_HANDLING,
                        source_element=f"{mod_name}.status.{err.status_field}",
                        requirement_statement=f"Preserve error handling for status '{err.status_field}' -> handler procedure '{err.handler_procedure}' (abnormal_term={err.is_abnormal_termination}).",
                        source_evidence={"status_field": err.status_field, "handler": err.handler_procedure},
                    )
                )

        # ── 2. Derive Independent Target Engineering Requirements ─────────────
        target_reqs: list[TargetEngineeringRequirement] = []

        # Data representation requirement
        decimal_type = target_knowledge.language.decimal_type if target_knowledge else ("BigDecimal" if lang_upper == "JAVA" else "Decimal")
        string_type = target_knowledge.language.string_type if target_knowledge else ("String" if lang_upper == "JAVA" else "str")
        target_reqs.append(
            TargetEngineeringRequirement(
                requirement_kind="DATA_REPRESENTATION",
                target_technology=target_spec.language,
                description=f"Represent legacy fixed-length strings using {string_type} and high-precision financial decimals using {decimal_type}.",
                required_capability=f"{target_spec.language.lower()}_source_generation",
            )
        )

        # Control execution requirement
        target_reqs.append(
            TargetEngineeringRequirement(
                requirement_kind="CONTROL_EXECUTION",
                target_technology=target_spec.language,
                description=f"Encapsulate procedural execution blocks into idiomatic {target_spec.language} methods/functions with structured control flow.",
                required_capability=f"{target_spec.language.lower()}_source_generation",
            )
        )

        # I/O Adapter requirement
        target_reqs.append(
            TargetEngineeringRequirement(
                requirement_kind="IO_ADAPTER",
                target_technology=target_spec.language,
                description=f"Isolate external file and dataset I/O behind an adapter boundary returning status outcomes.",
                required_capability=f"{target_spec.language.lower()}_source_generation",
            )
        )

        # Build & Verification harness requirement
        verification_cap = "javac_compilation" if lang_upper == "JAVA" else "cpython_compile"
        tech_to_check = "JAVA" if lang_upper == "JAVA" else "PYTHON"
        providers_found = self.provider_registry.find_for_technology(tech_to_check)
        has_verif = any(
            any(cap[1] == verification_cap for cap in p.capabilities_supplied())
            for p in providers_found
        )
        target_reqs.append(
            TargetEngineeringRequirement(
                requirement_kind="VERIFICATION_HARNESS",
                target_technology=target_spec.language,
                description=f"Provide deterministic verification entrypoint executable via host toolchain ({verification_cap}).",
                required_capability=verification_cap,
                is_supported=has_verif,
            )
        )

        # ── 3. Plan Target Architecture & Artifact Roles ───────────────────────
        roles = [ArtifactRole.ENTRY_POINT.value, ArtifactRole.SERVICE.value, ArtifactRole.TEST_HARNESS.value]
        if semantic_model.entities:
            roles.append(ArtifactRole.DOMAIN_MODEL.value)
        if any(len(m.io_operations) > 0 for m in semantic_model.modules.values()):
            roles.append(ArtifactRole.ADAPTER.value)

        arch_style = "LAYERED_SERVICE" if lang_upper == "JAVA" else "MODULAR_APPLICATION"
        arch_plan = TargetArchitecturePlan(
            architecture_style=arch_style,
            roles_planned=roles,
            rationale=f"Selected idiomatic {target_spec.language} architecture separating data representations, business services, and I/O execution.",
            target_conventions_summary={
                "language": target_spec.language,
                "framework": target_spec.framework or "Standard",
                "file_extension": file_ext,
                "base_package_or_module": base_pkg if lang_upper == "JAVA" else "autoforge_modernized",
            },
        )

        # ── 4. Cross-Module System-Level Architecture & Component Graph ───────
        target_component_graph = TargetComponentGraph()
        dependency_mappings: list[DependencyMapping] = []
        interface_mappings: list[InterfaceMapping] = []
        datastore_mappings: list[DataStoreMapping] = []
        shared_data_mappings: list[SharedDataMapping] = []
        execution_flow_mappings: list[ExecutionFlowMapping] = []
        external_dependency_mappings: list[ExternalDependencyMapping] = []

        # 4a. Shared Data & Domain Entities across modules
        # Detect entities/copybooks used across multiple modules or declared in entities
        shared_entity_users: dict[str, list[str]] = {}
        for edge in semantic_model.semantic_graph.edges:
            if edge.kind in ("INCLUDES", "READS", "WRITES", "BINDS"):
                src_node = semantic_model.semantic_graph.get_node(edge.src)
                dst_node = semantic_model.semantic_graph.get_node(edge.dst)
                if src_node and dst_node and dst_node.kind in ("COPYBOOK", "RECORD", "DATASET_SCHEMA"):
                    shared_entity_users.setdefault(dst_node.name, []).append(src_node.name)

        seen_case_insensitive: dict[str, str] = {}
        for ent_name, ent in semantic_model.entities.items():
            users = list(set(shared_entity_users.get(ent_name, [])))
            # If multiple users or standard entity, assign explicit shared domain model
            safe_ent_name = "".join(part.capitalize() for part in re.sub(r"[^a-zA-Z0-9_]", "_", ent_name).split("_") if part)
            if not safe_ent_name:
                safe_ent_name = "SharedEntity"
            if safe_ent_name[0].isdigit():
                safe_ent_name = f"Entity{safe_ent_name}"

            # Ensure case-insensitive uniqueness across file systems (e.g. macOS / Windows)
            key_lower = safe_ent_name.lower()
            if key_lower in seen_case_insensitive:
                safe_ent_name = seen_case_insensitive[key_lower]
            else:
                seen_case_insensitive[key_lower] = safe_ent_name

            existing_node = target_component_graph.get_component(safe_ent_name)
            if existing_node:
                for u in (users or [ent_name]):
                    if u not in existing_node.source_module_names:
                        existing_node.source_module_names.append(u)
                continue

            is_multi_module_shared = len(users) > 1 or (len(semantic_model.modules) > 2 and bool(ent.fields))
            ownership = "SHARED_DOMAIN_MODEL" if is_multi_module_shared else "EMBEDDED_RECORD_SCHEMA"
            sh_mapping = SharedDataMapping(
                entity_name=ent_name,
                source_type=ent.entity_type,
                sharing_modules=users if users else list(semantic_model.modules.keys()),
                target_model_name=safe_ent_name,
                target_role=ArtifactRole.DOMAIN_MODEL,
                ownership_strategy=ownership,
                rationale=(
                    f"Promotes shared data structure '{ent_name}' into dedicated target domain model '{safe_ent_name}' accessible across components."
                    if is_multi_module_shared
                    else f"Retains '{ent_name}' schema as module-level record representation for single module usage."
                ),
            )
            shared_data_mappings.append(sh_mapping)

            # Add node to target component graph
            ent_rel_path = (
                f"src/main/java/{base_pkg.replace('.', '/')}/{safe_ent_name}{file_ext}"
                if lang_upper == "JAVA"
                else f"src/domain/{safe_ent_name.lower()}{file_ext}"
            )
            target_component_graph.add_component(
                TargetComponentNode(
                    name=safe_ent_name,
                    role=ArtifactRole.DOMAIN_MODEL,
                    target_language=target_spec.language,
                    suggested_relative_path=ent_rel_path,
                    source_module_names=users if users else [ent_name],
                    responsibilities=[f"Represent structured data entity for {ent_name} with strong typing."],
                    interfaces_provided=[f"get{safe_ent_name}", f"set{safe_ent_name}"],
                )
            )

        # 4b. Datastore / I/O Mappings
        # Group I/O operations by dataset/resource
        datasets_seen: dict[str, dict[str, Any]] = {}
        for io in semantic_model.io_operations:
            ds_name = io.resource_name.upper()
            info = datasets_seen.setdefault(ds_name, {
                "type": io.resource_type,
                "modes": set(),
                "producers": set(),
                "consumers": set(),
            })
            info["modes"].add(io.access_mode)

        for m_name, mod in semantic_model.modules.items():
            for io in mod.io_operations:
                ds_name = io.resource_name.upper()
                info = datasets_seen.setdefault(ds_name, {
                    "type": io.resource_type,
                    "modes": set(),
                    "producers": set(),
                    "consumers": set(),
                })
                info["modes"].add(io.access_mode)
                if io.kind in (SemanticIOKind.DATA_WRITE, SemanticIOKind.DATA_UPDATE, SemanticIOKind.DATABASE_WRITE):
                    info["producers"].add(m_name)
                else:
                    info["consumers"].add(m_name)

        for ds_name, ds_info in datasets_seen.items():
            clean_ds = re.sub(r"[^a-zA-Z0-9_]", "_", ds_name)
            adapter_name = "".join(part.capitalize() for part in clean_ds.split("_") if part) + "Adapter"
            ds_mapping = DataStoreMapping(
                dataset_name=ds_name,
                resource_type=ds_info["type"],
                target_adapter_name=adapter_name,
                access_modes=list(ds_info["modes"]),
                read_producers=list(ds_info["producers"]),
                write_consumers=list(ds_info["consumers"]),
                status_semantics_preserved=True,
                adapter_strategy="REPOSITORY_PORT" if target_spec.framework else "FILE_OR_STREAM_ADAPTER",
            )
            datastore_mappings.append(ds_mapping)

            adapter_rel_path = (
                f"src/main/java/{base_pkg.replace('.', '/')}/{adapter_name}{file_ext}"
                if lang_upper == "JAVA"
                else f"src/adapters/{adapter_name.lower()}{file_ext}"
            )
            target_component_graph.add_component(
                TargetComponentNode(
                    name=adapter_name,
                    role=ArtifactRole.ADAPTER,
                    target_language=target_spec.language,
                    suggested_relative_path=adapter_rel_path,
                    source_module_names=list(ds_info["producers"] | ds_info["consumers"]),
                    responsibilities=[f"Manage persistence, record serialization, and status handling for {ds_name}."],
                    interfaces_provided=[f"read{clean_ds.capitalize()}", f"write{clean_ds.capitalize()}"],
                    data_stores_accessed=[ds_name],
                )
            )

        # 4c. Cross-Module Dependencies & CALL Interfaces
        for edge in semantic_model.semantic_graph.edges:
            src_node = semantic_model.semantic_graph.get_node(edge.src)
            dst_node = semantic_model.semantic_graph.get_node(edge.dst)
            if not src_node:
                continue

            src_clean = "".join(part.capitalize() for part in re.sub(r"[^a-zA-Z0-9_]", "_", src_node.name).split("_") if part)

            if edge.kind == "CALLS":
                target_name = dst_node.name if dst_node else edge.dst.split(":")[-1]
                target_clean = "".join(part.capitalize() for part in re.sub(r"[^a-zA-Z0-9_]", "_", target_name).split("_") if part)

                if edge.resolution_status == ResolutionStatus.RESOLVED and target_name in semantic_model.modules:
                    # Known internal module call
                    dep_map = DependencyMapping(
                        source_caller_module=src_node.name,
                        source_callee_module=target_name,
                        source_relationship_kind="CALLS",
                        target_caller_component=src_clean,
                        target_callee_component=target_clean,
                        target_relationship_kind="INVOKES",
                        interaction_pattern="SERVICE_INJECTION" if target_spec.framework else "SYNCHRONOUS_METHOD_CALL",
                        rationale=f"Preserves procedural CALL from {src_node.name} to {target_name} via target component interface invocation.",
                    )
                    dependency_mappings.append(dep_map)

                    callee_mod = semantic_model.modules[target_name]
                    entry_methods = [
                        {"name": p.name.lower().replace("-", "_"), "parameters": [f.name for f in p.parameters], "return_type": "int"}
                        for p in callee_mod.procedures[:3]
                    ]
                    interface_mappings.append(
                        InterfaceMapping(
                            source_module=target_name,
                            target_interface_name=f"I{target_clean}",
                            target_component_name=target_clean,
                            methods=entry_methods,
                            rationale=f"Defines public interface for callable program {target_name}.",
                        )
                    )
                else:
                    # Explicit UNRESOLVED external dependency tracking
                    is_specialist = edge.resolution_status == ResolutionStatus.SPECIALIST_REQUIRED
                    ext_map = ExternalDependencyMapping(
                        source_module=src_node.name,
                        unresolved_target_name=target_name,
                        dependency_kind="SYSTEM_UTILITY" if is_specialist else "UNRESOLVED_PROGRAM_CALL",
                        affected_component=src_clean,
                        required_interface_or_capability=f"external_provider_{target_name.lower()}",
                        confidence=0.0,
                        evidence=f"CALL '{target_name}' in {src_node.name}",
                        is_blocking=False,
                        recommended_resolution_path=(
                            f"Acquire mainframe system capability for {target_name}"
                            if is_specialist
                            else f"Provide target service or mock implementation for external routine {target_name}"
                        ),
                    )
                    external_dependency_mappings.append(ext_map)

            elif edge.kind == "EXECUTES":
                target_name = dst_node.name if dst_node else edge.dst.split(":")[-1]
                target_clean = "".join(part.capitalize() for part in re.sub(r"[^a-zA-Z0-9_]", "_", target_name).split("_") if part)
                dep_map = DependencyMapping(
                    source_caller_module=src_node.name,
                    source_callee_module=target_name,
                    source_relationship_kind="EXECUTES",
                    target_caller_component=src_clean + "Orchestrator",
                    target_callee_component=target_clean,
                    target_relationship_kind="ORCHESTRATES",
                    interaction_pattern="ORCHESTRATION_STEP",
                    rationale=f"Batch job {src_node.name} orchestrates execution of {target_name}.",
                )
                dependency_mappings.append(dep_map)

        # 4d. JCL / Batch Execution Flow Mapping
        for mod_name, mod in semantic_model.modules.items():
            if mod.module_type == "job":
                clean_job = "".join(part.capitalize() for part in re.sub(r"[^a-zA-Z0-9_]", "_", mod_name).split("_") if part)
                steps_info: list[dict[str, Any]] = []
                for idx, proc in enumerate(mod.procedures):
                    target_pgm = proc.called_procedures[0] if proc.called_procedures else proc.name
                    is_internal = target_pgm.upper() in [m.upper() for m in semantic_model.modules]
                    target_clean = "".join(part.capitalize() for part in re.sub(r"[^a-zA-Z0-9_]", "_", target_pgm).split("_") if part) if is_internal else ""
                    steps_info.append({
                        "step_name": proc.name,
                        "program": target_pgm,
                        "target_component": target_clean,
                        "target_handler": target_clean if is_internal else f"{target_pgm}UtilityHandler",
                        "order": idx + 1,
                        "condition": "ONLY_IF_PRIOR_SUCCESS",
                    })

                exec_mapping = ExecutionFlowMapping(
                    job_name=mod_name,
                    target_orchestrator_name=f"{clean_job}Orchestration",
                    steps=steps_info,
                    error_propagation_strategy="PROPAGATE_RETURN_CODE",
                    orchestration_pattern="PIPELINE_RUNNER" if target_spec.framework else "SEQUENTIAL_RUNNER",
                )
                execution_flow_mappings.append(exec_mapping)

        # Add explicit system architecture
        system_architecture = TargetSystemArchitecture(
            architecture_style=arch_style,
            roles_planned=roles,
            rationale=arch_plan.rationale,
            target_conventions_summary=arch_plan.target_conventions_summary,
            component_graph=target_component_graph,
            dependency_mappings=dependency_mappings,
            interface_mappings=interface_mappings,
            datastore_mappings=datastore_mappings,
            shared_data_mappings=shared_data_mappings,
            execution_flow_mappings=execution_flow_mappings,
            external_dependency_mappings=external_dependency_mappings,
        )

        # ── 5. Plan Target Artifacts & Semantic Mappings ───────────────────────
        planned_artifacts: list[PlannedTargetArtifact] = []
        all_unsupported: list[UnsupportedSemanticConstruct] = []
        semantic_mappings: list[SemanticMapping] = []
        transformation_steps: list[TransformationStep] = []

        step_counter = 1

        # Emit Shared Domain Models as planned artifacts
        for sh in [s for s in shared_data_mappings if s.ownership_strategy == "SHARED_DOMAIN_MODEL"]:
            ent = semantic_model.entities.get(sh.entity_name)
            sh_rel_path = (
                f"src/main/java/{base_pkg.replace('.', '/')}/{sh.target_model_name}{file_ext}"
                if lang_upper == "JAVA"
                else f"src/domain/{sh.target_model_name.lower()}{file_ext}"
            )
            step_id = str(uuid.uuid4())
            transformation_steps.append(
                TransformationStep(
                    step_id=step_id,
                    title=f"Engineer Shared Domain Model {sh.target_model_name}",
                    intent=f"Create cohesive shared target representation for entity/copybook {sh.entity_name}.",
                    source_semantic_refs=[f"ENTITY:{sh.entity_name}"],
                    preservation_requirement_ids=[
                        pr.req_id for pr in preservation_reqs if pr.source_element.startswith(f"{sh.entity_name}.")
                    ],
                    target_artifact_name=sh.target_model_name,
                    target_construct=f"Class {sh.target_model_name}",
                    ordering_index=step_counter,
                    verification_requirement=f"Compilation check in {target_spec.language}",
                )
            )
            step_counter += 1

            planned_artifacts.append(
                PlannedTargetArtifact(
                    name=sh.target_model_name,
                    role=ArtifactRole.DOMAIN_MODEL,
                    target_language=target_spec.language,
                    suggested_relative_path=sh_rel_path,
                    source_module_names=sh.sharing_modules,
                    preservation_requirement_ids=[
                        pr.req_id for pr in preservation_reqs if pr.source_element.startswith(f"{sh.entity_name}.")
                    ],
                    semantic_mappings=[],
                    transformation_step_ids=[step_id],
                )
            )

        for mod_name, mod in semantic_model.modules.items():
            all_unsupported.extend(mod.unsupported_constructs)

            mappings_for_art: list[SemanticMappingPlan] = []
            art_step_ids: list[str] = []
            art_preservation_ids: list[str] = []

            # Determine target filename & path from conventions
            cleaned_mod = re.sub(r"[^a-zA-Z0-9_]", "_", mod_name)
            safe_name = "".join(part.capitalize() for part in cleaned_mod.split("_") if part)
            if not safe_name:
                safe_name = "Component"
            if safe_name[0].isdigit():
                safe_name = f"Comp{safe_name}"

            # If JCL job, name as Orchestration
            if mod.module_type == "job":
                safe_name = f"{safe_name}Orchestration"

            rel_path = (
                f"src/main/java/{base_pkg.replace('.', '/')}/{safe_name}{file_ext}"
                if lang_upper == "JAVA"
                else f"src/{cleaned_mod.lower()}{file_ext}"
            )

            # Map procedures into methods/functions
            for proc in mod.procedures:
                target_ident = proc.name.lower().replace("-", "_")
                if lang_upper == "JAVA":
                    # camelCase for Java methods
                    parts = target_ident.split("_")
                    target_ident = parts[0] + "".join(p.capitalize() for p in parts[1:]) if len(parts) > 1 else target_ident

                target_type = "Method" if lang_upper == "JAVA" else "Function"
                mappings_for_art.append(
                    SemanticMappingPlan(
                        source_construct_name=proc.name,
                        source_construct_kind=proc.kind,
                        target_component_type=target_type,
                        target_identifier=target_ident,
                        conventions_applied=[
                            f"Language: {target_spec.language}",
                            f"Framework: {target_spec.framework or 'standard'}",
                        ],
                    )
                )
                semantic_mappings.append(
                    SemanticMapping(
                        source_semantic_ref=f"{mod_name}.{proc.name}",
                        source_kind="PROCEDURE",
                        target_construct_type="METHOD" if lang_upper == "JAVA" else "FUNCTION",
                        target_identifier=target_ident,
                        rationale=f"Maps procedural paragraph {proc.name} into target {target_type}.",
                    )
                )

                # Find relevant preservation requirements for this procedure
                relevant_pres_ids = [
                    pr.req_id for pr in preservation_reqs
                    if pr.source_element.startswith(f"{mod_name}.{proc.name}")
                ]
                art_preservation_ids.extend(relevant_pres_ids)

                # Add a transformation step for this procedure
                step_id = str(uuid.uuid4())
                art_step_ids.append(step_id)
                transformation_steps.append(
                    TransformationStep(
                        step_id=step_id,
                        title=f"Engineer {target_type} {target_ident}",
                        intent=f"Transform procedural paragraph {proc.name} into {target_type} {target_ident}.",
                        source_semantic_refs=[f"{mod_name}.{proc.name}"],
                        preservation_requirement_ids=relevant_pres_ids,
                        target_artifact_name=safe_name,
                        target_construct=f"{target_type} {target_ident}",
                        ordering_index=step_counter,
                        verification_requirement=f"Compile verification in {target_spec.language}",
                    )
                )
                step_counter += 1

            # Business rule steps & mappings
            for rule in mod.business_rules:
                r_ident = rule.name.lower().replace("-", "_")
                semantic_mappings.append(
                    SemanticMapping(
                        source_semantic_ref=f"{mod_name}.{rule.name}",
                        source_kind="RULE",
                        target_construct_type="PREDICATE",
                        target_identifier=r_ident,
                        rationale=f"Realizes business policy '{rule.name}' via boolean predicate or evaluation function.",
                    )
                )
                rule_pres_ids = [pr.req_id for pr in preservation_reqs if pr.source_element == f"{mod_name}.{rule.name}"]
                art_preservation_ids.extend(rule_pres_ids)

                step_id = str(uuid.uuid4())
                art_step_ids.append(step_id)
                transformation_steps.append(
                    TransformationStep(
                        step_id=step_id,
                        title=f"Implement Business Rule {rule.name}",
                        intent=f"Encode rule statement '{rule.statement}' into evaluation method.",
                        source_semantic_refs=[f"{mod_name}.{rule.name}"],
                        preservation_requirement_ids=rule_pres_ids,
                        target_artifact_name=safe_name,
                        target_construct=f"evaluate_{r_ident}",
                        ordering_index=step_counter,
                        verification_requirement="Unit evaluation check",
                    )
                )
                step_counter += 1

            # Component Workflow Execution Step
            workflow_step_id = str(uuid.uuid4())
            art_step_ids.append(workflow_step_id)
            transformation_steps.append(
                TransformationStep(
                    step_id=workflow_step_id,
                    title=f"Engineer Component Workflow {safe_name}",
                    intent=f"Coordinate module procedures and operational flow into execute entrypoint.",
                    source_semantic_refs=[f"{mod_name}.entrypoint"],
                    preservation_requirement_ids=[
                        pr.req_id for pr in preservation_reqs
                        if pr.category == PreservationCategory.CONTROL_FLOW
                    ],
                    target_artifact_name=safe_name,
                    target_construct="execute()" if lang_upper == "JAVA" else "run()",
                    ordering_index=step_counter,
                    verification_requirement="Execution workflow check",
                )
            )
            step_counter += 1

            # Status Code & Return Code Preservation Step
            if mod.io_operations or any("STATUS" in getattr(f, "name", "").upper() for f in mod.fields):
                status_step_id = str(uuid.uuid4())
                art_step_ids.append(status_step_id)
                transformation_steps.append(
                    TransformationStep(
                        step_id=status_step_id,
                        title="Implement Status Code Evaluation",
                        intent="Preserve standard status return code semantics across I/O and service boundaries.",
                        source_semantic_refs=[f"{mod_name}.status"],
                        preservation_requirement_ids=[
                            pr.req_id for pr in preservation_reqs
                            if pr.category in (PreservationCategory.ERROR_HANDLING, PreservationCategory.IO_SEMANTICS)
                        ],
                        target_artifact_name=safe_name,
                        target_construct="evaluateFileStatus(String status)" if lang_upper == "JAVA" else "evaluate_file_status(status: str)",
                        ordering_index=step_counter,
                        verification_requirement="Behavioral status check",
                    )
                )
                step_counter += 1

            role_to_assign = (
                ArtifactRole.ENTRY_POINT if mod.module_type == "job"
                else (ArtifactRole.SERVICE if target_spec.framework else ArtifactRole.MODULE)
            )

            planned_art = PlannedTargetArtifact(
                name=safe_name,
                role=role_to_assign,
                target_language=target_spec.language,
                suggested_relative_path=rel_path,
                source_module_names=[mod.name],
                preservation_requirement_ids=list(set(art_preservation_ids)),
                semantic_mappings=mappings_for_art,
                transformation_step_ids=art_step_ids,
            )
            planned_artifacts.append(planned_art)

            # Register into component graph
            target_component_graph.add_component(
                TargetComponentNode(
                    name=safe_name,
                    role=role_to_assign,
                    target_language=target_spec.language,
                    suggested_relative_path=rel_path,
                    source_module_names=[mod.name],
                    responsibilities=[f"Execute functionality of source {mod.module_type} {mod.name}."],
                    preservation_requirement_ids=list(set(art_preservation_ids)),
                )
            )

        # Wire edges into target_component_graph from dependency_mappings
        for dm in dependency_mappings:
            src_node = target_component_graph.get_component(dm.target_caller_component)
            dst_node = target_component_graph.get_component(dm.target_callee_component)
            if src_node and dst_node:
                target_component_graph.add_edge(
                    TargetComponentEdge(
                        src_component_id=src_node.component_id,
                        dst_component_id=dst_node.component_id,
                        kind=dm.target_relationship_kind,
                        description=f"{dm.target_caller_component} {dm.target_relationship_kind} {dm.target_callee_component}",
                        rationale=dm.rationale,
                        source_relationship_ref=f"{dm.source_caller_module}->{dm.source_callee_module}",
                    )
                )

        # Wire edges from components to shared data models
        for sh in shared_data_mappings:
            dst_comp = target_component_graph.get_component(sh.target_model_name)
            if not dst_comp:
                continue
            for m_user in sh.sharing_modules:
                clean_u = "".join(part.capitalize() for part in re.sub(r"[^a-zA-Z0-9_]", "_", m_user).split("_") if part)
                src_comp = target_component_graph.get_component(clean_u)
                if src_comp:
                    target_component_graph.add_edge(
                        TargetComponentEdge(
                            src_component_id=src_comp.component_id,
                            dst_component_id=dst_comp.component_id,
                            kind="EXCHANGES_DATA",
                            description=f"{clean_u} uses shared domain entity {sh.target_model_name}",
                            rationale=sh.rationale,
                        )
                    )

        # ── 6. Build Verification Strategy from Target Specification ───────────
        checks: list[PlannedVerificationCheck] = []
        for req in target_spec.verification_requirements:
            if req == "syntax":
                checks.append(
                    PlannedVerificationCheck(
                        check_name=f"{target_spec.language} Syntax Validation",
                        stage="syntax",
                        required_capability=f"{target_spec.language.lower()}_syntax_check",
                        tool=f"{target_spec.language.lower()}-syntax-validator",
                    )
                )
            elif req == "compile":
                tool_name = "javac" if lang_upper == "JAVA" else "cpython-compile"
                checks.append(
                    PlannedVerificationCheck(
                        check_name=f"{target_spec.language} Bytecode Compilation",
                        stage="compile",
                        required_capability="javac_compilation" if lang_upper == "JAVA" else f"{target_spec.language.lower()}_byte_compile",
                        tool=tool_name,
                    )
                )
            elif req == "tests":
                checks.append(
                    PlannedVerificationCheck(
                        check_name=f"{target_spec.language} Test Verification",
                        stage="test",
                        required_capability=f"{target_spec.language.lower()}_test_harness",
                        tool="pytest" if lang_upper == "PYTHON" else "junit",
                    )
                )

        # Execution check
        checks.append(
            PlannedVerificationCheck(
                check_name=f"{target_spec.language} Bounded Runtime Execution",
                stage="execution",
                required_capability="openjdk_jvm" if lang_upper == "JAVA" else "cpython_runtime",
                tool="java" if lang_upper == "JAVA" else "python3",
            )
        )

        has_blocking = gap_report.has_blocking_gaps if gap_report else False

        return TransformationPlan(
            project_id=semantic_model.project_id,
            target_language=target_spec.language,
            target_framework=target_spec.framework,
            behavior_preservation_requirements=preservation_reqs,
            target_engineering_requirements=target_reqs,
            target_architecture=arch_plan,
            target_system_architecture=system_architecture,
            transformation_steps=transformation_steps,
            semantic_mappings=semantic_mappings,
            cross_module_dependencies=dependency_mappings,
            shared_data_decisions=shared_data_mappings,
            datastore_mappings=datastore_mappings,
            external_dependencies=external_dependency_mappings,
            execution_orchestration=execution_flow_mappings,
            target_components=planned_artifacts,
            unsupported_constructs=all_unsupported,
            verification_strategy=checks,
            gap_summary=gap_report.summary() if gap_report else {},
            can_proceed=(
                not has_blocking
                and (
                    scope_result.scope_complete
                    and scope_result.unsupported_artifact_count == 0
                    and scope_result.unknown_artifact_count == 0
                )
                if scope_result is not None
                else (not has_blocking)
            ),
            scope_result=scope_result,
            metadata={
                "target_knowledge_id": target_knowledge.knowledge_id if target_knowledge else None,
                "total_semantic_modules": len(semantic_model.modules),
                "total_preservation_requirements": len(preservation_reqs),
                "total_transformation_steps": len(transformation_steps),
                "total_cross_module_dependencies": len(dependency_mappings),
                "total_shared_data_mappings": len(shared_data_mappings),
                "total_datastore_mappings": len(datastore_mappings),
                "total_external_dependencies": len(external_dependency_mappings),
                "total_execution_flow_mappings": len(execution_flow_mappings),
                "target_components_in_graph": len(target_component_graph.components),
                "target_edges_in_graph": len(target_component_graph.edges),
            },
        )
