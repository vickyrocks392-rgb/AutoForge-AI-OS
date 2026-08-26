"""AutoForge AI Infrastructure Platform — Phase 7.

Implements the canonical Phase 7 specification from ``architecture/ROADMAP.md``:

    Goal:            Implement provider abstraction.
    Specification:   Capability Registry · Model Router · Execution Continuity Manager
    Validation:      Provider switching · Failover · Offline mode · Local-first behaviour
    Outcome:         AI Infrastructure Frozen

Component map (see ``architecture/ARCHITECTURE.md`` §17/§17.1):

    - :mod:`autoforge_ai_infrastructure.metadata`   provider/model/capability/deployment metadata
    - :mod:`autoforge_ai_infrastructure.registry`   Capability Registry (metadata only; never routes)
    - :mod:`autoforge_ai_infrastructure.policies`   explicit, injectable routing policies
    - :mod:`autoforge_ai_infrastructure.router`     Model Router (selection only; no retries/failover)
    - :mod:`autoforge_ai_infrastructure.execution`  provider-neutral model execution boundary
    - :mod:`autoforge_ai_infrastructure.continuity` Execution Continuity Manager (retry, failover,
                                                    context preservation, checkpoint recovery)
    - :mod:`autoforge_ai_infrastructure.events`     canonical event factory (existing vocabulary only)
    - :mod:`autoforge_ai_infrastructure.kernel_adapter`
                                                    adapters implementing the Kernel's frozen ABCs

Architectural constraints honoured:

    - Provider agnostic: no concrete vendor is coupled into the architecture.
    - Local-first: local deployment is a first-class routing target.
    - Interface-first with dependency injection at the composition root.
    - Durable checkpoints remain owned by the Runtime State Manager; this
      platform depends only on an injected checkpoint port.
    - No competing Context Engine: preserved execution context carries only
      the execution state needed to resume (ADR-003 stays authoritative for
      model-context assembly).
"""

from __future__ import annotations

from autoforge_ai_infrastructure.continuity import (
    ContinuityOutcome,
    DefaultFailureClassifier,
    ExecutionContinuityService,
    PreservedExecutionContext,
    RetryPolicy,
)
from autoforge_ai_infrastructure.errors import (
    AIInfrastructureError,
    CheckpointRecoveryError,
    DuplicateRegistrationError,
        ExecutionFailedError,
    ExecutorNotBoundError,
    ExecutionTimeoutError,
    FailoverExhaustedError,
    MalformedRoutingRequestError,
    ModelUnavailableError,
    NoEligibleModelError,
    ProviderUnavailableError,
    RetryExhaustedError,
    UnsupportedCapabilityError,
    UnknownEntityError,
)
from autoforge_ai_infrastructure.events import AIInfrastructureEvents
from autoforge_ai_infrastructure.execution import (
    ExecutionRequest,
    ExecutionResult,
    ExecutionTarget,
    ExecutorRegistry,
    RoutedModelExecutor,
    execute_attempt,
)
from autoforge_ai_infrastructure.interfaces import (
    CanonicalEventSink,
    CapabilityRegistryPort,
    FailureClassification,
    FailureClassifier,
    ModelExecutor,
    RoutingPolicy,
    RuntimeCheckpointPort,
)
from autoforge_ai_infrastructure.kernel_adapter import (
    KernelContinuityManager,
    KernelModelRouter,
)
from autoforge_ai_infrastructure.metadata import (
    AttemptRecord,
    CapabilityIds,
    CapabilityMetadata,
    CostSpec,
    DeploymentMetadata,
    DeploymentMode,
    LatencyProfile,
    ModelMetadata,
    ModelQuery,
    ModelStatus,
    Modality,
    ProviderMetadata,
    ProviderStatus,
    ProviderType,
    ResourceConstraints,
    RoutingRequest,
)
from autoforge_ai_infrastructure.policies import (
    AvailabilityFirstRoutingPolicy,
    BUILTIN_POLICIES,
    CapabilityFirstRoutingPolicy,
    CostOptimizingRoutingPolicy,
    LatencySensitiveRoutingPolicy,
    LocalFirstRoutingPolicy,
    QualityFirstRoutingPolicy,
)
from autoforge_ai_infrastructure.reference_catalog import install_reference_catalog
from autoforge_ai_infrastructure.registry import InMemoryCapabilityRegistry
from autoforge_ai_infrastructure.router import (
    CandidateScore,
    ModelRouterService,
    RoutingDecision,
)

__all__ = [
    # errors
    "AIInfrastructureError",
    "CheckpointRecoveryError",
    "DuplicateRegistrationError",
        "ExecutionFailedError",
    "ExecutorNotBoundError",
    "ExecutionTimeoutError",
    "FailoverExhaustedError",
    "MalformedRoutingRequestError",
    "ModelUnavailableError",
    "NoEligibleModelError",
    "ProviderUnavailableError",
    "RetryExhaustedError",
    "UnsupportedCapabilityError",
    "UnknownEntityError",
    # registry
    "InMemoryCapabilityRegistry",
    "CapabilityRegistryPort",
    # metadata
    "AttemptRecord",
    "CapabilityIds",
    "CapabilityMetadata",
    "CostSpec",
    "DeploymentMetadata",
    "DeploymentMode",
    "LatencyProfile",
    "ModelMetadata",
    "ModelQuery",
    "ModelStatus",
    "Modality",
    "ProviderMetadata",
    "ProviderStatus",
    "ProviderType",
    "ResourceConstraints",
    "RoutingRequest",
    # router
    "CandidateScore",
    "ModelRouterService",
    "RoutingDecision",
    "RoutingPolicy",
    # policies
    "BUILTIN_POLICIES",
    "CapabilityFirstRoutingPolicy",
    "CostOptimizingRoutingPolicy",
    "LatencySensitiveRoutingPolicy",
    "LocalFirstRoutingPolicy",
    "QualityFirstRoutingPolicy",
    # execution
    "ExecutionRequest",
    "ExecutionResult",
    "ExecutionTarget",
    "ExecutorRegistry",
    "ModelExecutor",
    "RoutedModelExecutor",
    "execute_attempt",
    # continuity
    "ContinuityOutcome",
    "ExecutionContinuityService",
    "FailureClassification",
    "FailureClassifier",
    "PreservedExecutionContext",
    "RetryPolicy",
    # events
    "AIInfrastructureEvents",
    "CanonicalEventSink",
    # kernel adapters
    "KernelContinuityManager",
    "KernelModelRouter",
    # catalog
    "install_reference_catalog",
    # ports
    "RuntimeCheckpointPort",
]

__version__ = "0.1.0"
