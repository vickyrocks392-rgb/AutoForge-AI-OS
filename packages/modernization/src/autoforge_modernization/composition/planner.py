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

from enum import Enum
import re
import uuid
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field

from autoforge_modernization.capabilities.gap_analyzer import (
    CapabilityGapAnalysisReport,
)
from autoforge_modernization.capabilities.models import CapabilityClass, CapabilityState
from autoforge_modernization.capabilities.providers import ProviderRegistry
from autoforge_modernization.semantic.model import (
    DataFlowEdge,
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


class TargetArchitecturePlan(BaseModel):
    """High-level target architectural style, role layout, and structure."""

    architecture_style: str = "MODULAR_SERVICE"
    roles_planned: list[str] = Field(default_factory=list)
    rationale: str = ""
    target_conventions_summary: dict[str, Any] = Field(default_factory=dict)


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
    transformation_steps: list[TransformationStep] = Field(default_factory=list)
    semantic_mappings: list[SemanticMapping] = Field(default_factory=list)

    # Artifacts to be generated (target_components retained for backward compatibility)
    target_components: list[PlannedTargetArtifact] = Field(default_factory=list)

    unsupported_constructs: list[UnsupportedSemanticConstruct] = Field(default_factory=list)
    verification_strategy: list[PlannedVerificationCheck] = Field(default_factory=list)
    gap_summary: dict[str, Any] = Field(default_factory=dict)
    can_proceed: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict)


class GenericTransformationPlanner:
    """Plans transformation from a technology-neutral semantic model to target specification."""

    def __init__(self, provider_registry: ProviderRegistry | None = None) -> None:
        self.target_registry = default_target_technology_registry()
        self.provider_registry = provider_registry or ProviderRegistry()

    def plan(
        self,
        semantic_model: TechnologyNeutralSemanticModel,
        target_spec: TargetSpecification,
        gap_report: CapabilityGapAnalysisReport | None = None,
    ) -> TransformationPlan:
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

        arch_plan = TargetArchitecturePlan(
            architecture_style="LAYERED_SERVICE" if lang_upper == "JAVA" else "MODULAR_APPLICATION",
            roles_planned=roles,
            rationale=f"Selected idiomatic {target_spec.language} architecture separating data representations, business services, and I/O execution.",
            target_conventions_summary={
                "language": target_spec.language,
                "framework": target_spec.framework or "Standard",
                "file_extension": file_ext,
                "base_package_or_module": base_pkg if lang_upper == "JAVA" else "autoforge_modernized",
            },
        )

        # ── 4. Plan Target Artifacts & Semantic Mappings ───────────────────────
        planned_artifacts: list[PlannedTargetArtifact] = []
        all_unsupported: list[UnsupportedSemanticConstruct] = []
        semantic_mappings: list[SemanticMapping] = []
        transformation_steps: list[TransformationStep] = []

        step_counter = 1

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

            # File Status Evaluation Step (Bounded CardDemo rule)
            status_step_id = str(uuid.uuid4())
            art_step_ids.append(status_step_id)
            transformation_steps.append(
                TransformationStep(
                    step_id=status_step_id,
                    title="Implement Bounded File Status Evaluation",
                    intent="Preserve status return code semantics (00->0, 10->16, other->12).",
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

            planned_artifacts.append(
                PlannedTargetArtifact(
                    name=safe_name,
                    role=ArtifactRole.SERVICE if target_spec.framework else ArtifactRole.MODULE,
                    target_language=target_spec.language,
                    suggested_relative_path=rel_path,
                    source_module_names=[mod.name],
                    preservation_requirement_ids=list(set(art_preservation_ids)),
                    semantic_mappings=mappings_for_art,
                    transformation_step_ids=art_step_ids,
                )
            )

        # ── 5. Build Verification Strategy from Target Specification ───────────
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
            transformation_steps=transformation_steps,
            semantic_mappings=semantic_mappings,
            target_components=planned_artifacts,
            unsupported_constructs=all_unsupported,
            verification_strategy=checks,
            gap_summary=gap_report.summary() if gap_report else {},
            can_proceed=not has_blocking,
            metadata={
                "target_knowledge_id": target_knowledge.knowledge_id if target_knowledge else None,
                "total_semantic_modules": len(semantic_model.modules),
                "total_preservation_requirements": len(preservation_reqs),
                "total_transformation_steps": len(transformation_steps),
            },
        )
