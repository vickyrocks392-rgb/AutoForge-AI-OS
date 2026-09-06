"""AutoForge Dynamic Capability Composition Architecture."""

from autoforge_modernization.composition.generator import (
    GeneratedArtifact,
    GenericTargetArtifactGenerator,
)
from autoforge_modernization.composition.planner import (
    GenericTransformationPlanner,
    PlannedTargetComponent,
    PlannedVerificationCheck,
    SemanticMappingPlan,
    TransformationPlan,
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
    "SemanticMappingPlan",
    "PlannedTargetComponent",
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
