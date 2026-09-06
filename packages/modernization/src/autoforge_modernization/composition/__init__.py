"""AutoForge Dynamic Capability Composition Architecture."""

from autoforge_modernization.composition.generator import (
    GeneratedArtifact,
    GenericTargetArtifactGenerator,
)
from autoforge_modernization.composition.planner import (
    ArtifactRole,
    BehaviorPreservationRequirement,
    GenericTransformationPlanner,
    PlannedTargetArtifact,
    PlannedTargetComponent,
    PlannedVerificationCheck,
    PreservationCategory,
    SemanticMapping,
    SemanticMappingPlan,
    TargetArchitecturePlan,
    TargetEngineeringRequirement,
    TransformationPlan,
    TransformationStep,
)
from autoforge_modernization.composition.repair import (
    AutonomousTargetRepairCycle,
)
from autoforge_modernization.composition.verifier import (
    TargetToolchainVerifier,
    TargetVerificationResult,
)
from autoforge_modernization.composition.workflow import (
    CompositionWorkflowReport,
    DynamicCapabilityWorkflow,
    WorkflowStageResult,
)

__all__ = [
    "PreservationCategory",
    "BehaviorPreservationRequirement",
    "TargetEngineeringRequirement",
    "SemanticMappingPlan",
    "SemanticMapping",
    "TransformationStep",
    "ArtifactRole",
    "PlannedTargetArtifact",
    "PlannedTargetComponent",
    "TargetArchitecturePlan",
    "PlannedVerificationCheck",
    "TransformationPlan",
    "GenericTransformationPlanner",
    "GeneratedArtifact",
    "GenericTargetArtifactGenerator",
    "TargetToolchainVerifier",
    "TargetVerificationResult",
    "AutonomousTargetRepairCycle",
    "WorkflowStageResult",
    "CompositionWorkflowReport",
    "DynamicCapabilityWorkflow",
]
