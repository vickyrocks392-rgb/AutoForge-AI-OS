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
    GapFinding, FixRecommendation, BusinessRuleReference,
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

# Knowledge Layer (G.3)
from autoforge_modernization.knowledge import (
    TechnologyFamily, ClaimKind, TechnologyRelationshipKind,
    KnowledgeClaim, TechnologyRelationship, ModernizationPath,
    DialectInfo, TechnologyKnowledge, TechnologyKnowledgeLayer,
)
# Analysis Engine (G.3)
from autoforge_modernization.analysis import (
    TechnologyAnalysisStage1, ArchitectureAnalysisStage2,
    DataAnalysisStage3, BusinessBehaviorAnalysisStage4,
    CapabilityGapStage5, ModernizationOption,
    EstimationSummary, AnalysisReport, LegacyAnalysisEngine,
)
# Transformation Engine (G.3)
from autoforge_modernization.transformation import (
    TransformationStatus, TransformationType,
    TransformationRecord, TransformationEngine,
)

from autoforge_modernization.pipeline import (
    ModernizationPipeline, PipelineResult,
    PipelineStatus, PipelineWaveResult,
)


from autoforge_modernization.g3_transform_strategies import G3TransformationStrategies
from autoforge_modernization.dependency_graph import (
    DependencyGraph, GraphNode, GraphEdge, EdgeKind,
    build_from_cobol, build_from_jcl, build_from_sql,
)
from autoforge_modernization.transformation_engine import (
    TransformationEngine, TransformationResult,
)
from autoforge_modernization.rag_integration import RAGClient, RAGCallRecord
from autoforge_modernization.ollama_integration import OllamaClient, OllamaCallRecord
from autoforge_modernization.dag_scheduler import DAGScheduler, ScheduledTask
from autoforge_modernization.capability_stubs import (
    CapabilityMode, CapabilityResult, CapabilityDetector,
    CICSCapability, BMSCapability, IMSCapability,
    VSAMCapability, PLICapability, AssemblerCapability,
)
from autoforge_modernization.metrics_forensics import MetricsForensics, StageTimer

# Generalized Autonomous Capability Expansion
from autoforge_modernization.capabilities import (
    CapabilityClass,
    CapabilityState as ExpansionCapabilityState,
    CapabilityRequirement,
    QualifiedCapability,
    VerifiedTechnologyProvider,
    ProviderRegistry,
    CapabilityRequirementGraph,
    CapabilityGapAnalyzer,
    AutonomousAcquisitionEngine,
)
from autoforge_modernization.discovery import (
    ProjectTechnologyDiscoveryEngine,
    ProjectTechnologyInventory,
    DetectedTechnologySummary,
    EvidenceProvider,
)
from autoforge_modernization.semantic import (
    TechnologyNeutralSemanticModel,
    SemanticModule,
    SemanticProcedure,
    SemanticField,
    SemanticOperation,
    SemanticBusinessRule,
    SemanticModelExtractor,
)
from autoforge_modernization.target import (
    TargetSpecification,
    TargetCapabilityDeriver,
)
from autoforge_modernization.composition import (
    TransformationPlan,
    GenericTransformationPlanner,
    DynamicCapabilityWorkflow,
    CompositionWorkflowReport,
)


__all__ = [
    "ModernizationError",
    "CapabilityError",
    "UnknownTechnologyError",
    "UnsupportedTechnologyError",
    "ToolRequiredError",
    "CapabilityGapError",
    "UnverifiedToolError",
    "UnresolvedCapabilityGapError",
    "PlanningGateError",
    "AmbiguousRequirementError",
    "UnresolvedBusinessIntentError",
    "ContradictoryBusinessRuleError",
    "UnapprovedFindingError",
    "CheckpointError",
    "CorruptedCheckpointError",
    "InvalidCheckpointError",
    "SizingError",
    "LOCAccountingError",
    "DataPlaneError",
    "ClientDataLeakError",
    "LockdownViolationError",
    "TransformationError",
    "TransformationBlockedError",
    "ModernizationPhase",
    "JobStatus",
    "GateState",
    "OperatingMode",
    "LockdownState",
    "ModernizationJob",
    "CapabilityState",
    "CapabilityLevel",
    "TechnologyCapability",
    "TechnologyCapabilityRegistry",
    "ToolPurpose",
    "ToolCapability",
    "ToolDeterminism",
    "InstallationState",
    "SpecialistTool",
    "SpecialistToolingInventory",
    "GapState",
    "GapSeverity",
    "CapabilityGap",
    "CapabilityGapReport",
    "RequirementSource",
    "RequirementStatus",
    "RecommendationAction",
    "ApprovalState",
    "Requirement",
    "CurrentBehavior",
    "BusinessIntent",
    "TargetBehavior",
    "GapFinding",
    "FixRecommendation",
    "BusinessRuleReference",
    "GateConditionKind",
    "GateConditionStatus",
    "GateCondition",
    "GateDecision",
    "GateDecisionRecord",
    "MigrationStrategy",
    "PlanStatus",
    "StrategyJustification",
    "MigrationUnitSpec",
    "MigrationPlan",
    "UnitStatus",
    "WaveStatus",
    "MigrationUnit",
    "MigrationWave",
    "LOCCountingMethod",
    "LOCMetrics",
    "ThroughputMetric",
    "ThroughputSegment",
    "ThroughputObservation",
    "ThroughputProfile",
    "EstimationAssumption",
    "DurationEstimate",
    "ProjectEstimate",
    "BenchmarkType",
    "PricingModel",
    "ProjectComplexity",
    "Geography",
    "MarketBenchmark",
    "MarketInputs",
    "MarketEstimate",
    "DataPlane",
    "DataPlaneBoundary",
    "ResearchType",
    "ResearchStatus",
    "ResearchQuery",
    "ResearchPlaneConfig",
    "ChunkingStrategy",
    "ContextOptimization",
    "ContextBudget",
    "ContextUsageRecord",
    "ModernizationDashboardJob",
    "ModernizationDashboardTime",
    "ModernizationDashboardProgress",
    "ModernizationDashboardHealth",
    "ModernizationDashboardCheckpoint",
    "ModernizationDashboard",
    "ModernizationEventType",
    "ModernizationEvent",
    "CheckpointType",
    "CheckpointState",
    "ModernizationCheckpoint",
    "CheckpointedProgress",
    "ModernizationRAGRetrievalEngine",
    "RAGIntegrationScope",
    "ProvenanceStage",
    "ProvenanceLink",
    "ModernizationProvenanceChain",
    "TechnologyFamily",
    "ClaimKind",
    "TechnologyRelationshipKind",
    "KnowledgeClaim",
    "TechnologyRelationship",
    "ModernizationPath",
    "DialectInfo",
    "TechnologyKnowledge",
    "TechnologyKnowledgeLayer",
    "TechnologyAnalysisStage1",
    "ArchitectureAnalysisStage2",
    "DataAnalysisStage3",
    "BusinessBehaviorAnalysisStage4",
    "CapabilityGapStage5",
    "ModernizationOption",
    "EstimationSummary",
    "AnalysisReport",
    "LegacyAnalysisEngine",
    "TransformationStatus",
    "TransformationType",
    "TransformationRecord",
    "TransformationEngine",
    "ModernizationPipeline",
    "PipelineResult",
    "PipelineStatus",
    "PipelineWaveResult",
    # G.3 LLM integration
    "G3LLMIntegration",
    "LLMWorkloadMetrics",
    "LLMConclusionRecord",
    "LLMTaskKind",
    "check_ollama_health",
    # G.3 transformation strategies
    "G3TransformationStrategies",
    # G.3 dependency graph
    "DependencyGraph", "GraphNode", "GraphEdge", "EdgeKind",
    "build_from_cobol", "build_from_jcl", "build_from_sql",
    # G.3 transformation engine (real)
    "TransformationResult",
    # G.3 RAG integration
    "RAGClient", "RAGCallRecord",
    # G.3 Ollama integration
    "OllamaClient", "OllamaCallRecord",
    # G.3 DAG scheduler
    "DAGScheduler", "ScheduledTask",
    # G.3 capability stubs
    "CapabilityMode", "CapabilityResult", "CapabilityDetector",
    "CICSCapability", "BMSCapability", "IMSCapability",
    "VSAMCapability", "PLICapability", "AssemblerCapability",
    # G.3 metrics forensics
    "MetricsForensics", "StageTimer",
    # Generalized Autonomous Capability Expansion
    "CapabilityClass",
    "ExpansionCapabilityState",
    "CapabilityRequirement",
    "QualifiedCapability",
    "VerifiedTechnologyProvider",
    "ProviderRegistry",
    "CapabilityRequirementGraph",
    "CapabilityGapAnalyzer",
    "AutonomousAcquisitionEngine",
    "ProjectTechnologyDiscoveryEngine",
    "ProjectTechnologyInventory",
    "DetectedTechnologySummary",
    "EvidenceProvider",
    "TechnologyNeutralSemanticModel",
    "SemanticModule",
    "SemanticProcedure",
    "SemanticField",
    "SemanticOperation",
    "SemanticBusinessRule",
    "SemanticModelExtractor",
    "TargetSpecification",
    "TargetCapabilityDeriver",
    "TransformationPlan",
    "GenericTransformationPlanner",
    "DynamicCapabilityWorkflow",
    "CompositionWorkflowReport",
]

