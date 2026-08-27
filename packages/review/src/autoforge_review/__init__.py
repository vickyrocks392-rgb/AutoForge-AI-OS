"""AutoForge Review Platform — Phase 11.

Autonomous Quality, Review Loops & Quality Gates.

The Review Platform is a QUALITY CONTROL subsystem (section 3). It consumes
evidence produced by previous stages (Phase 10 Execution) and produces
structured findings and quality-gate decisions. It is NOT a kernel,
workflow engine, execution engine, artifact manager, or agent runtime.

Public API
----------
Engine:
    ReviewEngine, QualityGate
Loop:
    ReviewLoop
Reviews & Reviewers:
    SpecializedReviewer, ArchitectureReviewer, CodeReviewer,
    SecurityReviewer, PerformanceReviewer, DocumentationReviewer
    , ReviewContext, REVIEWER_REGISTRY
Policies:
    ReviewPolicy, default_review_policy
AI seam:
    AIReviewTask, AIReviewResult, ReviewAIProvider,
    AIInfrastructureReviewAdapter, ProposedFinding
Models:
    ReviewRequest, ReviewEvidence, ReviewResult, ReviewFinding,
    QualityGateResult, ReviewDecision, RepairRequest, ReviewCycleRecord,
    ReviewLoopResult, ReviewLoopStatus
    Severity, FindingClassification, FindingKind, ReviewCategory
    FindingProvenance, AISourceMetadata
Checks:
    RuleCheck, all ``check_*`` functions, FORBIDDEN_FRAMEWORKS
Events:
    ReviewEvents, ReviewEventSinkProtocol
Errors:
    ReviewError, ReviewValidationError, ReviewPolicyRejectedError,
    ReviewNotRunError, ReviewAiUnavailableError, ReviewLoopError
"""

from __future__ import annotations

from autoforge_review.checks import (
    FORBIDDEN_FRAMEWORKS,
    RuleCheck,
    check_architecture_import,
    check_bare_exceptions,
    check_build_success,
    check_complexity,
    check_dangerous_execution,
    check_execution_time,
    check_forbidden_imports,
    check_path_traversal,
    check_readme_sections,
    check_required_files,
    check_secret_leak,
    check_test_results,
    check_timeout,
)
from autoforge_review.ai_reviewer import (
    AIReviewResult,
    AIReviewTask,
    AIInfrastructureReviewAdapter,
    ProposedFinding,
    ReviewAIProvider,
)
from autoforge_review.errors import (
    ReviewAiUnavailableError,
    ReviewError,
    ReviewLoopError,
    ReviewNotRunError,
    ReviewPolicyRejectedError,
    ReviewValidationError,
)
from autoforge_review.events import ReviewEventSinkProtocol, ReviewEvents
from autoforge_review.models import (
    AISourceMetadata,
    FindingClassification,
    FindingKind,
    FindingProvenance,
    GateStatus,
    QualityGateResult,
    RepairRequest,
    ReviewCategory,
    ReviewCycleRecord,
    ReviewDecision,
    ReviewEvidence,
    ReviewFinding,
    ReviewLoopResult,
    ReviewLoopStatus,
    ReviewRequest,
    ReviewResult,
    Severity,
    is_at_least,
    severity_rank,
)
from autoforge_review.policies import ReviewPolicy, default_review_policy
from autoforge_review.reviewers import (
    ArchitectureReviewer,
    CodeReviewer,
    DocumentationReviewer,
    PerformanceReviewer,
    REVIEWER_REGISTRY,
    ReviewContext,
    SecurityReviewer,
    SpecializedReviewer,
)

# Engine / Loop imported lazily to avoid circular imports at package import time.
from autoforge_review.engine import ReviewEngine
from autoforge_review.loop import ReviewLoop
from autoforge_review.engine import QualityGate

__version__ = "0.1.0"

__all__ = [
    # Engine
    "ReviewEngine",
    "QualityGate",
    "ReviewLoop",
    # Reviewers
    "SpecializedReviewer",
    "ReviewContext",
    "ArchitectureReviewer",
    "CodeReviewer",
    "SecurityReviewer",
    "PerformanceReviewer",
    "DocumentationReviewer",
    "REVIEWER_REGISTRY",
    # Policies
    "ReviewPolicy",
    "default_review_policy",
    # AI seam
    "AIReviewTask",
    "AIReviewResult",
    "ReviewAIProvider",
    "AIInfrastructureReviewAdapter",
    "ProposedFinding",
    # Models
    "ReviewRequest",
    "ReviewEvidence",
    "ReviewResult",
    "ReviewFinding",
    "QualityGateResult",
    "GateStatus",
    "ReviewDecision",
    "RepairRequest",
    "ReviewCycleRecord",
    "ReviewLoopResult",
    "ReviewLoopStatus",
    "Severity",
    "FindingClassification",
    "FindingKind",
    "ReviewCategory",
    "FindingProvenance",
    "AISourceMetadata",
    "is_at_least",
    "severity_rank",
    # Checks
    "RuleCheck",
    "FORBIDDEN_FRAMEWORKS",
    "check_architecture_import",
    "check_bare_exceptions",
    "check_build_success",
    "check_complexity",
    "check_dangerous_execution",
    "check_execution_time",
    "check_forbidden_imports",
    "check_path_traversal",
    "check_readme_sections",
    "check_required_files",
    "check_secret_leak",
    "check_test_results",
    "check_timeout",
    # Events
    "ReviewEvents",
    "ReviewEventSinkProtocol",
    # Errors
    "ReviewError",
    "ReviewValidationError",
    "ReviewPolicyRejectedError",
    "ReviewNotRunError",
    "ReviewAiUnavailableError",
    "ReviewLoopError",
]
