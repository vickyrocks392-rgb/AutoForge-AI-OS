"""AutoForge Dynamic Capability Composition Architecture."""

from autoforge_modernization.composition.planner import (
    GenericTransformationPlanner,
    PlannedTargetComponent,
    PlannedVerificationCheck,
    SemanticMappingPlan,
    TransformationPlan,
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
    "WorkflowStageResult",
    "CompositionWorkflowReport",
    "DynamicCapabilityWorkflow",
]
