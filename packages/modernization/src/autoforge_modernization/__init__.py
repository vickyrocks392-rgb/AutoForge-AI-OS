"""
AutoForge Modernization Engine — Phase 18-G Foundation.
"""
# Errors
from autoforge_modernization.errors import (
    ModernizationError, CapabilityError, UnknownTechnologyError,
    UnsupportedTechnologyError, ToolRequiredError,
    CapabilityGapError, UnverifiedToolError, UnresolvedCapabilityGapError,
    PlanningGateError, AmbiguousRequirementError, UnresolvedBusinessIntentError,
    ContradictoryBusinessRuleError, UnapprovedFindingError,
    CheckpointError, CorruptedCheckpointError, InvalidCheckpointError,
    SizingError, LOCAccountingError, DataPlaneError, ClientDataLeakError,
    LockdownViolationError, TransformationError, TransformationBlockedError,
)
# Jobs / Phase / State
from autoforge_modernization.jobs import (
    ModernizationPhase, JobStatus, GateState,
    OperatingMode, LockdownState, ModernizationJob,
)
# Capability Registry
from autoforge_modernization.capability_registry import (
    CapabilityState, CapabilityLevel,
    TechnologyCapability, TechnologyCapabilityRegistry,
)
# Specialist Tooling
from autoforge_modernization.tooling import (
    ToolPurpose, ToolCapability, ToolDeterminism, InstallationState,
    SpecialistTool, SpecialistToolingInventory,
)
# Capability Gap
from autoforge_modernization.capability_gap import (
    GapState, GapSeverity, CapabilityGap, CapabilityGapReport,
)
# Business / Requirements / Rules
from autoforge_modernization.business import (
    RequirementSource, RequirementStatus,
    RecommendationAction, GapSeverity, ApprovalState,
    Requirement, CurrentBehavior, BusinessIntent, TargetBehavior,
    GapFinding, FixRecommendation,
)
# Planning Gate
from autoforge_modernization.planning_gate import (
    GateConditionKind, GateConditionStatus, GateCondition,
    GateDecision, GateDecisionRecord,
)
# Strategy / Migration Plan
from autoforge_modernization.strategy import (
    MigrationStrategy, PlanStatus, StrategyJustification,
    MigrationUnitSpec, MigrationPlan,
)
# Migration Units / Waves
from autoforge_modernization.units import (
    UnitStatus, WaveStatus, MigrationUnit, MigrationWave,
)
# Sizing / LOC
from autoforge_modernization.sizing import (
    LOCCountingMethod, LOCMetrics,
)
# Throughput
from autoforge_modernization.throughput import (
    ThroughputMetric, ThroughputSegment,
    ThroughputObservation, ThroughputProfile,
)
# Estimation / ETA
from autoforge_modernization.estimation import (
    EstimationAssumption, DurationEstimate, ProjectEstimate,
)
# Market / Benchmarks
from autoforge_modernization.market import (
    BenchmarkType, PricingModel, ProjectComplexity, Geography,
    MarketBenchmark, MarketInputs, MarketEstimate,
)
# Lockdown / Data Plane
from autoforge_modernization.lockdown import (
    DataPlane, DataPlaneBoundary,
)
# Research Plane
from autoforge_modernization.research_plane import (
    ResearchType, ResearchStatus, ResearchQuery, ResearchPlaneConfig,
)
# Context Budget
from autoforge_modernization.context_budget import (
    ChunkingStrategy, ContextOptimization,
    ContextBudget, ContextUsageRecord,
)
# Observability
from autoforge_modernization.observability import (
    ModernizationDashboardJob, ModernizationDashboardTime,
    ModernizationDashboardProgress, ModernizationDashboardHealth,
    ModernizationDashboardCheckpoint, ModernizationDashboard,
    ModernizationEventType, ModernizationEvent,
)
# Checkpoints
from autoforge_modernization.checkpoints import (
    CheckpointType, CheckpointState,
    ModernizationCheckpoint, CheckpointedProgress,
)
# RAG Boundary
from autoforge_modernization.rag_boundary import (
    ModernizationRAGRetrievalEngine, RAGIntegrationScope,
)
# Provenance
from autoforge_modernization.provenance import (
    ProvenanceStage, ProvenanceLink, ModernizationProvenanceChain,
)


__all__ = [
    # Errors
    "ModernizationError", "CapabilityError", "UnknownTechnologyError",
    "UnsupportedTechnologyError", "ToolRequiredError",
    "CapabilityGapError", "UnverifiedToolError", "UnresolvedCapabilityGapError",
    "PlanningGateError", "AmbiguousRequirementError", "UnresolvedBusinessIntentError",
    "ContradictoryBusinessRuleError", "UnapprovedFindingError",
    "CheckpointError", "CorruptedCheckpointError", "InvalidCheckpointError",
    "SizingError", "LOCAccountingError", "DataPlaneError", "ClientDataLeakError",
    "LockdownViolationError", "TransformationError", "TransformationBlockedError",
    # Jobs
    "ModernizationPhase", "JobStatus", "GateState",
    "OperatingMode", "LockdownState", "ModernizationJob",
    # Capability
    "CapabilityState", "CapabilityLevel", "TechnologyCapability",
    "TechnologyCapabilityRegistry",
    # Tooling
    "ToolPurpose", "ToolCapability", "ToolDeterminism", "InstallationState",
    "SpecialistTool", "SpecialistToolingInventory",
    # Gap
    "GapState", "GapSeverity", "CapabilityGap", "CapabilityGapReport",
    # Business
    "RequirementSource", "RequirementStatus",
    "RecommendationAction", "GapSeverity", "ApprovalState",
    "Requirement", "CurrentBehavior", "BusinessIntent", "TargetBehavior",
    "GapFinding", "FixRecommendation",
    # Gate
    "GateConditionKind", "GateConditionStatus", "GateCondition",
    "GateDecision", "GateDecisionRecord",
    # Strategy
    "MigrationStrategy", "PlanStatus", "StrategyJustification",
    "MigrationUnitSpec", "MigrationPlan",
    # Units
    "UnitStatus", "WaveStatus", "MigrationUnit", "MigrationWave",
    # Sizing
    "LOCCountingMethod", "LOCMetrics",
    # Throughput
    "ThroughputMetric", "ThroughputSegment",
    "ThroughputObservation", "ThroughputProfile",
    # Estimation
    "EstimationAssumption", "DurationEstimate", "ProjectEstimate",
    # Market
    "BenchmarkType", "PricingModel", "ProjectComplexity", "Geography",
    "MarketBenchmark", "MarketInputs", "MarketEstimate",
    # Lockdown
    "DataPlane", "DataPlaneBoundary",
    # Research
    "ResearchType", "ResearchStatus", "ResearchQuery", "ResearchPlaneConfig",
    # Context
    "ChunkingStrategy", "ContextOptimization",
    "ContextBudget", "ContextUsageRecord",
    # Observability
    "ModernizationDashboardJob", "ModernizationDashboardTime",
    "ModernizationDashboardProgress", "ModernizationDashboardHealth",
    "ModernizationDashboardCheckpoint", "ModernizationDashboard",
    "ModernizationEventType", "ModernizationEvent",
    # Checkpoints
    "CheckpointType", "CheckpointState",
    "ModernizationCheckpoint", "CheckpointedProgress",
    # RAG
    "ModernizationRAGRetrievalEngine", "RAGIntegrationScope",
    # Provenance
    "ProvenanceStage", "ProvenanceLink", "ModernizationProvenanceChain",
]
