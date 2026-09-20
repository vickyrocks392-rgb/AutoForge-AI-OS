"""AutoForge Code Migration / Refactoring Power Engine (18-COMMERCIAL-D)."""

from autoforge_power_engines.migration.spec import (
    CustomerMigrationSpecification,
    MigrationType,
    RiskTolerance,
    ApprovalPolicy,
    VerificationPolicy,
)
from autoforge_power_engines.migration.inventory import (
    CodebaseInventoryEngine,
    CodebaseInventory,
    FileInventoryRecord,
    FileClassification,
)
from autoforge_power_engines.migration.analysis import (
    SourceAnalyzer,
    SourceAnalysisReport,
    CodeEntity,
    DependencyReference,
    DatabaseInteraction,
)
from autoforge_power_engines.migration.risk import (
    MigrationRiskClassifier,
    MigrationRiskAssessment,
    MigrationRiskLevel,
)
from autoforge_power_engines.migration.approval import (
    ApprovalManager,
    ApprovalRequest,
    ApprovalStatus,
)
from autoforge_power_engines.migration.plan import (
    MigrationPlanner,
    MigrationPlan,
    TransformationUnit,
    TransformationUnitType,
)
from autoforge_power_engines.migration.safety import (
    safe_extract_archive,
    validate_path_confinement,
    is_sensitive_path,
    scan_for_secrets,
    sanitize_prompt_context,
    SafeExecutionRunner,
    SafeExecutionResult,
    SecurityViolationError,
)
from autoforge_power_engines.migration.strategy import (
    MigrationStrategy,
    CobolToJavaSpringStrategy,
    PythonModernizationStrategy,
    MigrationStrategyRegistry,
)
from autoforge_power_engines.migration.transformation import (
    TransformationPipeline,
    TransformationRecord,
)
from autoforge_power_engines.migration.equivalence import (
    BehaviorEquivalenceEngine,
    BehaviorEquivalenceReport,
    TestCaseVector,
    VectorComparisonResult,
    EquivalenceLevel,
    EquivalenceVerdict,
)
from autoforge_power_engines.migration.verifier import (
    VerificationEngine,
    UnitVerificationReport,
    VerificationCheck,
    VerificationStatus,
)
from autoforge_power_engines.migration.repair import (
    BoundedRepairEngine,
    BoundedRepairReport,
    RepairAttemptRecord,
)
from autoforge_power_engines.migration.completeness import (
    CompletenessAuditor,
    MigrationCompletenessManifest,
    CompletenessManifestEntry,
    UnitCompletenessStatus,
)
from autoforge_power_engines.migration.telemetry import (
    MigrationTelemetryCollector,
    PerformanceMetrics,
    MigrationUnitTrace,
    mask_secrets,
)
from autoforge_power_engines.migration.generator import (
    StandaloneCustomerMigrationGenerator,
)
from autoforge_power_engines.migration.engine import (
    CodeMigrationPowerEngine,
)

__all__ = [
    "CustomerMigrationSpecification",
    "MigrationType",
    "RiskTolerance",
    "ApprovalPolicy",
    "VerificationPolicy",
    "CodebaseInventoryEngine",
    "CodebaseInventory",
    "FileInventoryRecord",
    "FileClassification",
    "SourceAnalyzer",
    "SourceAnalysisReport",
    "CodeEntity",
    "DependencyReference",
    "DatabaseInteraction",
    "MigrationRiskClassifier",
    "MigrationRiskAssessment",
    "MigrationRiskLevel",
    "ApprovalManager",
    "ApprovalRequest",
    "ApprovalStatus",
    "MigrationPlanner",
    "MigrationPlan",
    "TransformationUnit",
    "TransformationUnitType",
    "safe_extract_archive",
    "validate_path_confinement",
    "is_sensitive_path",
    "scan_for_secrets",
    "sanitize_prompt_context",
    "SafeExecutionRunner",
    "SafeExecutionResult",
    "SecurityViolationError",
    "MigrationStrategy",
    "CobolToJavaSpringStrategy",
    "PythonModernizationStrategy",
    "MigrationStrategyRegistry",
    "TransformationPipeline",
    "TransformationRecord",
    "BehaviorEquivalenceEngine",
    "BehaviorEquivalenceReport",
    "TestCaseVector",
    "VectorComparisonResult",
    "EquivalenceLevel",
    "EquivalenceVerdict",
    "VerificationEngine",
    "UnitVerificationReport",
    "VerificationCheck",
    "VerificationStatus",
    "BoundedRepairEngine",
    "BoundedRepairReport",
    "RepairAttemptRecord",
    "CompletenessAuditor",
    "MigrationCompletenessManifest",
    "CompletenessManifestEntry",
    "UnitCompletenessStatus",
    "MigrationTelemetryCollector",
    "PerformanceMetrics",
    "MigrationUnitTrace",
    "mask_secrets",
    "StandaloneCustomerMigrationGenerator",
    "CodeMigrationPowerEngine",
]
