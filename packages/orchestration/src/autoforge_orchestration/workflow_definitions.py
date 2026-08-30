"""Phase 18 canonical workflow definitions.

Defines the deterministic stage DAGs for both the Greenfield engineering
pipeline and the Legacy Modernization pipeline, mapping each
``StageKind`` to the correct existing workforce worker type and capabilities.

No workers are created here — workers are looked up from the existing
``WORKER_REGISTRY``. No capabilities are invented — they mirror what the
23-worker workforce actually declares.
"""

from __future__ import annotations

from autoforge_ai_infrastructure.metadata import CapabilityIds

from autoforge_orchestration.models import (
    HITLGateSpec,
    RunMode,
    StageDefinition,
    StageKind,
    WorkflowDefinition,
)

# ── StageKind → Worker type mapping (uses the EXISTING 23-worker workforce) ──

STAGE_KIND_TO_WORKER_TYPE: dict[StageKind, str] = {
    # Greenfield
    StageKind.IDEA: "research_engineer",
    StageKind.INTENT: "planning_engineer",
    StageKind.RESEARCH: "research_engineer",
    StageKind.PLANNING: "planning_engineer",
    StageKind.ARCHITECTURE: "architecture_engineer",
    StageKind.DESIGN: "architecture_engineer",
    StageKind.IMPLEMENTATION: "backend_engineer",
    StageKind.TESTING: "qa_engineer",
    StageKind.EVALUATION: "qa_engineer",
    StageKind.DIAGNOSIS: "documentation_engineer",
    StageKind.REPAIR: "backend_engineer",
    StageKind.REIMPLEMENTATION: "backend_engineer",
    StageKind.RETEST: "qa_engineer",
    StageKind.REVIEW: "qa_engineer",
    StageKind.ARTIFACT: "documentation_engineer",
    StageKind.DEPLOYMENT: "devops_engineer",
    # Legacy modernization
    StageKind.LEGACY_DISCOVERY: "legacy_systems_research_engineer",
    StageKind.LEGACY_ARCHAEOLOGY: "legacy_code_archaeologist",
    StageKind.ARCHITECTURE_RECONSTRUCTION: "legacy_architecture_analyst",
    StageKind.BUSINESS_RULES_EXTRACTION: "business_rules_analyst",
    StageKind.DEPENDENCY_ANALYSIS: "dependency_impact_analyst",
    StageKind.MODERNIZATION_ARCHITECTURE: "modernization_architect",
    StageKind.MIGRATION_IMPLEMENTATION: "migration_engineer",
    StageKind.EQUIVALENCE_VALIDATION: "qa_engineer",
    StageKind.LEGACY_VALIDATION: "qa_engineer",
        StageKind.CUTOVER: "devops_engineer",
}

# ── StageKind → Required capabilities mapping ──────────────────────────────

STAGE_KIND_TO_CAPABILITIES: dict[StageKind, list[str]] = {
    StageKind.IDEA: [CapabilityIds.TEXT_GENERATION, CapabilityIds.REASONING],
    StageKind.INTENT: [CapabilityIds.TEXT_GENERATION, CapabilityIds.REASONING],
    StageKind.RESEARCH: [CapabilityIds.TEXT_GENERATION, CapabilityIds.REASONING],
    StageKind.PLANNING: [CapabilityIds.TEXT_GENERATION, CapabilityIds.REASONING,
                          CapabilityIds.STRUCTURED_OUTPUT],
    StageKind.ARCHITECTURE: [CapabilityIds.TEXT_GENERATION, CapabilityIds.REASONING],
    StageKind.DESIGN: [CapabilityIds.TEXT_GENERATION, CapabilityIds.REASONING],
    StageKind.IMPLEMENTATION: [CapabilityIds.TEXT_GENERATION, CapabilityIds.CODE_GENERATION,
                               CapabilityIds.STRUCTURED_OUTPUT],
    StageKind.TESTING: [CapabilityIds.TEXT_GENERATION, CapabilityIds.CODE_GENERATION,
                        CapabilityIds.REASONING],
    StageKind.EVALUATION: [CapabilityIds.TEXT_GENERATION, CapabilityIds.STRUCTURED_OUTPUT],
    StageKind.DIAGNOSIS: [CapabilityIds.TEXT_GENERATION, CapabilityIds.REASONING],
    StageKind.REPAIR: [CapabilityIds.TEXT_GENERATION, CapabilityIds.CODE_GENERATION,
                       CapabilityIds.STRUCTURED_OUTPUT],
    StageKind.REIMPLEMENTATION: [CapabilityIds.TEXT_GENERATION, CapabilityIds.CODE_GENERATION,
                                 CapabilityIds.STRUCTURED_OUTPUT],
    StageKind.RETEST: [CapabilityIds.TEXT_GENERATION, CapabilityIds.CODE_GENERATION],
    StageKind.REVIEW: [CapabilityIds.TEXT_GENERATION, CapabilityIds.REASONING],
    StageKind.ARTIFACT: [CapabilityIds.TEXT_GENERATION, CapabilityIds.STRUCTURED_OUTPUT],
    StageKind.DEPLOYMENT: [CapabilityIds.TEXT_GENERATION, CapabilityIds.REASONING],
    # Legacy
    StageKind.LEGACY_DISCOVERY: [CapabilityIds.TEXT_GENERATION],
    StageKind.LEGACY_ARCHAEOLOGY: [CapabilityIds.TEXT_GENERATION],
    StageKind.ARCHITECTURE_RECONSTRUCTION: [CapabilityIds.TEXT_GENERATION,
                                            CapabilityIds.REASONING],
    StageKind.BUSINESS_RULES_EXTRACTION: [CapabilityIds.TEXT_GENERATION],
    StageKind.DEPENDENCY_ANALYSIS: [CapabilityIds.TEXT_GENERATION,
                                    CapabilityIds.REASONING],
    StageKind.MODERNIZATION_ARCHITECTURE: [CapabilityIds.TEXT_GENERATION,
                                          CapabilityIds.REASONING,
                                          CapabilityIds.STRUCTURED_OUTPUT],
    StageKind.MIGRATION_IMPLEMENTATION: [CapabilityIds.TEXT_GENERATION,
                                         CapabilityIds.CODE_GENERATION],
    StageKind.EQUIVALENCE_VALIDATION: [CapabilityIds.TEXT_GENERATION,
                                       CapabilityIds.REASONING],
    StageKind.LEGACY_VALIDATION: [CapabilityIds.TEXT_GENERATION,
                                  CapabilityIds.REASONING],
    StageKind.CUTOVER: [CapabilityIds.TEXT_GENERATION, CapabilityIds.REASONING],
}


def _worker_for_stage(stage_kind: StageKind) -> str:
    return STAGE_KIND_TO_WORKER_TYPE[stage_kind]


def _caps_for_stage(stage_kind: StageKind) -> list[str]:
    return STAGE_KIND_TO_CAPABILITIES.get(stage_kind, [CapabilityIds.TEXT_GENERATION])


# ── Greenfield workflow definition ──────────────────────────────────────────

GREENFIELD_STAGE_ORDER: list[StageKind] = [
    StageKind.IDEA,
    StageKind.INTENT,
    StageKind.RESEARCH,
    StageKind.PLANNING,
    StageKind.ARCHITECTURE,
    StageKind.DESIGN,
    StageKind.IMPLEMENTATION,
    StageKind.TESTING,
    StageKind.EVALUATION,
    StageKind.REVIEW,
    StageKind.ARTIFACT,
    StageKind.DEPLOYMENT,
]


def _greenfield_stage_defs() -> list[StageDefinition]:
    """Build greenfield stage definitions in linear dependency order."""
    stages: list[StageDefinition] = []
    prev: StageKind | None = None
    for kind in GREENFIELD_STAGE_ORDER:
        deps = [prev.value] if prev else []
        worker_type = _worker_for_stage(kind)
        caps = _caps_for_stage(kind)

        stage = StageDefinition(
            stage_id=kind.value,
            name=kind.name.replace("_", " ").title(),
            kind=kind,
            description=f"Greenfield {kind.value} stage",
            worker_type=worker_type,
            required_capabilities=caps,
            dependencies=deps,
            model_requirements={"reasoning_required": True},
            verification_commands=[],
            required_files=[],
            review_required=False,
            artifact_types=[],
            acceptance_criteria=[
                f"Output artifacts for {kind.value} stage must be produced",
                "Stage must transition to SUCCEEDED via evaluation",
            ],
            max_attempts=3,
            max_rectifications=2,
            execution_timeout_seconds=300.0,
            deployment_target=None,
            deployment_strategy="copy",
        )
        stages.append(stage)
        prev = kind
    return stages


GREENFIELD_WORKFLOW_DEFINITION = WorkflowDefinition(
    workflow_id="greenfield",
    name="Greenfield Autonomous Engineering",
    mode=RunMode.GREENFIELD,
    stages=_greenfield_stage_defs(),
    version="1.0.0",
)


# ── Legacy modernization workflow definition ────────────────────────────────

LEGACY_STAGE_ORDER: list[StageKind] = [
    StageKind.LEGACY_DISCOVERY,
    StageKind.LEGACY_ARCHAEOLOGY,
    StageKind.ARCHITECTURE_RECONSTRUCTION,
    StageKind.BUSINESS_RULES_EXTRACTION,
    StageKind.DEPENDENCY_ANALYSIS,
    StageKind.MODERNIZATION_ARCHITECTURE,
    StageKind.MIGRATION_IMPLEMENTATION,
    StageKind.TESTING,
    StageKind.EQUIVALENCE_VALIDATION,
    StageKind.LEGACY_VALIDATION,
    StageKind.CUTOVER,
]


def _legacy_stage_defs() -> list[StageDefinition]:
    """Build legacy modernization stage definitions in linear order."""
    stages: list[StageDefinition] = []
    prev: StageKind | None = None
    for kind in LEGACY_STAGE_ORDER:
        deps = [prev.value] if prev else []
        worker_type = _worker_for_stage(kind)
        caps = _caps_for_stage(kind)

        hitl_gate: HITLGateSpec | None = None
        if kind == StageKind.MODERNIZATION_ARCHITECTURE:
            hitl_gate = HITLGateSpec(
                gate_id="legacy-modernization-arch-approval",
                reason="Modernization architecture requires human review before migration",
                risk_level="high",
                description="Approve the modernization architecture before migration",
                decision_hint="Review architecture plan and approve or reject",
            )
        elif kind == StageKind.CUTOVER:
            hitl_gate = HITLGateSpec(
                gate_id="legacy-cutover-approval",
                reason="Cutover is an irreversible production operation",
                risk_level="critical",
                description="Authorize live cutover",
                decision_hint="Confirm all validation gates have passed before cutover",
            )

        stage = StageDefinition(
            stage_id=kind.value,
            name=kind.name.replace("_", " ").title(),
            kind=kind,
            description=f"Legacy modernization {kind.value} stage",
            worker_type=worker_type,
            required_capabilities=caps,
            dependencies=deps,
            model_requirements={"reasoning_required": True},
            verification_commands=[],
            required_files=[],
            review_required=(kind in {StageKind.MIGRATION_IMPLEMENTATION,
                                       StageKind.EQUIVALENCE_VALIDATION}),
            artifact_types=[],
            acceptance_criteria=[
                f"Output artifacts for {kind.value} stage must be produced",
            ],
            max_attempts=3,
            max_rectifications=2,
            execution_timeout_seconds=600.0,
            deployment_target=None,
            deployment_strategy="copy",
        )
        if hitl_gate:
            stage = stage.model_copy(update={"hitl_gate": hitl_gate})
        stages.append(stage)
        prev = kind
    return stages


LEGACY_WORKFLOW_DEFINITION = WorkflowDefinition(
    workflow_id="legacy_modernization",
    name="Legacy Modernization Pipeline",
    mode=RunMode.LEGACY_MODERNIZATION,
    stages=_legacy_stage_defs(),
    version="1.0.0",
)
