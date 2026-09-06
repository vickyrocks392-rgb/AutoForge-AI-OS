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

import uuid
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field

from autoforge_modernization.capabilities.gap_analyzer import (
    CapabilityGapAnalysisReport,
)
from autoforge_modernization.semantic.model import (
    SemanticModule,
    TechnologyNeutralSemanticModel,
    UnsupportedSemanticConstruct,
    _utc_now,
)
from autoforge_modernization.target.specification import TargetSpecification
from autoforge_modernization.target_technology import (
    TargetTechnologyKnowledge,
    default_target_technology_registry,
)


class SemanticMappingPlan(BaseModel):
    """How a source semantic construct maps to target architecture."""

    source_construct_name: str
    source_construct_kind: str
    target_component_type: str  # e.g., "Class", "Service", "Repository", "Function"
    target_identifier: str
    conventions_applied: list[str] = Field(default_factory=list)


class PlannedTargetComponent(BaseModel):
    """A target file/artifact to be generated."""

    component_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str
    component_type: str  # entity, service, controller, batch_job, repository
    target_language: str
    suggested_relative_path: str
    source_module_names: list[str] = Field(default_factory=list)
    semantic_mappings: list[SemanticMappingPlan] = Field(default_factory=list)


class PlannedVerificationCheck(BaseModel):
    """A planned verification stage on target code."""

    check_name: str
    stage: str  # syntax, compile, test
    required_capability: str
    tool: str


class TransformationPlan(BaseModel):
    """The authoritative, technology-neutral transformation plan."""

    plan_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    project_id: str
    target_language: str
    target_framework: str | None = None
    created_at: datetime = Field(default_factory=_utc_now)

    target_components: list[PlannedTargetComponent] = Field(default_factory=list)
    unsupported_constructs: list[UnsupportedSemanticConstruct] = Field(default_factory=list)
    verification_strategy: list[PlannedVerificationCheck] = Field(default_factory=list)
    gap_summary: dict[str, Any] = Field(default_factory=dict)
    can_proceed: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict)


class GenericTransformationPlanner:
    """Plans transformation from a technology-neutral semantic model to target specification."""

    def __init__(self) -> None:
        self.target_registry = default_target_technology_registry()

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

        file_ext = (
            target_knowledge.language.file_extension
            if target_knowledge
            else ".txt"
        )
        base_pkg = (
            target_knowledge.project.base_package
            if target_knowledge and target_knowledge.project
            else "com.autoforge.generated"
        )

        planned_components: list[PlannedTargetComponent] = []
        all_unsupported: list[UnsupportedSemanticConstruct] = []

        # Iterate over semantic modules in the neutral model
        for mod_name, mod in semantic_model.modules.items():
            all_unsupported.extend(mod.unsupported_constructs)

            # Map module procedures into semantic mappings
            mappings: list[SemanticMappingPlan] = []
            for proc in mod.procedures:
                target_ident = proc.name.lower().replace("-", "_")
                mappings.append(
                    SemanticMappingPlan(
                        source_construct_name=proc.name,
                        source_construct_kind=proc.kind,
                        target_component_type="Method" if target_spec.language.upper() == "JAVA" else "Function",
                        target_identifier=target_ident,
                        conventions_applied=[
                            f"Language: {target_spec.language}",
                            f"Framework: {target_spec.framework or 'standard'}",
                        ],
                    )
                )

            # Determine target filename & path from conventions
            safe_name = mod_name.replace("-", "_").title().replace("_", "")
            rel_path = (
                f"src/main/java/{base_pkg.replace('.', '/')}/{safe_name}{file_ext}"
                if target_spec.language.upper() == "JAVA"
                else f"src/{mod_name.lower().replace('-', '_')}{file_ext}"
            )

            planned_components.append(
                PlannedTargetComponent(
                    name=safe_name,
                    component_type="Service" if target_spec.framework else "Module",
                    target_language=target_spec.language,
                    suggested_relative_path=rel_path,
                    source_module_names=[mod.name],
                    semantic_mappings=mappings,
                )
            )

        # Build verification strategy from target specification
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
                tool_name = "javac" if target_spec.language.upper() == "JAVA" else "cpython-compile"
                checks.append(
                    PlannedVerificationCheck(
                        check_name=f"{target_spec.language} Bytecode Compilation",
                        stage="compile",
                        required_capability="javac_compilation" if target_spec.language.upper() == "JAVA" else f"{target_spec.language.lower()}_byte_compile",
                        tool=tool_name,
                    )
                )
            elif req == "tests":
                checks.append(
                    PlannedVerificationCheck(
                        check_name=f"{target_spec.language} Test Verification",
                        stage="test",
                        required_capability=f"{target_spec.language.lower()}_test_harness",
                        tool="pytest" if target_spec.language.upper() == "PYTHON" else "junit",
                    )
                )

        has_blocking = gap_report.has_blocking_gaps if gap_report else False

        return TransformationPlan(
            project_id=semantic_model.project_id,
            target_language=target_spec.language,
            target_framework=target_spec.framework,
            target_components=planned_components,
            unsupported_constructs=all_unsupported,
            verification_strategy=checks,
            gap_summary=gap_report.summary() if gap_report else {},
            can_proceed=not has_blocking,
            metadata={
                "target_knowledge_id": target_knowledge.knowledge_id if target_knowledge else None,
                "total_semantic_modules": len(semantic_model.modules),
            },
        )
