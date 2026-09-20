"""
AutoForge AI — Workload Containerization + Sandboxing Subsystem (Phase 18-I).

Provides defense-in-depth isolation, lifecycle orchestration, policy validation,
and guaranteed cleanup for untrusted and semi-trusted generated workloads.
"""

from autoforge_execution.sandbox.models import (
    CleanupPolicy,
    CleanupReport,
    CleanupStatus,
    FilesystemPolicy,
    NetworkMode,
    NetworkPolicy,
    PreparedWorkload,
    ProcessPolicy,
    ResourceLimits,
    ResourceUsage,
    SecretPolicy,
    SecurityProfile,
    TerminationReason,
    VerificationState,
    WorkloadLifecycleState,
    WorkloadResult,
    WorkloadSpec,
)
from autoforge_execution.sandbox.policies import (
    PolicyValidator,
    PolicyViolationError,
)
from autoforge_execution.sandbox.reaper import (
    WorkloadReaper,
)
from autoforge_execution.sandbox.lifecycle import (
    SandboxLifecycleManager,
    StateTransition,
)
from autoforge_execution.sandbox.provider import (
    ContainerSandboxProvider,
    DockerSandboxProvider,
    LocalRestrictedSandboxProvider,
    PodmanSandboxProvider,
    SandboxProvider,
    SandboxRuntimeUnavailableError,
)
from autoforge_execution.sandbox.manager import (
    WorkloadSandboxManager,
)
from autoforge_execution.sandbox.environment_adapter import (
    SandboxedWorkspaceEnvironment,
)

__all__ = [
    # Models & Policies
    "CleanupPolicy",
    "CleanupReport",
    "CleanupStatus",
    "FilesystemPolicy",
    "NetworkMode",
    "NetworkPolicy",
    "PreparedWorkload",
    "ProcessPolicy",
    "ResourceLimits",
    "ResourceUsage",
    "SecretPolicy",
    "SecurityProfile",
    "TerminationReason",
    "VerificationState",
    "WorkloadLifecycleState",
    "WorkloadResult",
    "WorkloadSpec",
    # Policies & Validation
    "PolicyValidator",
    "PolicyViolationError",
    # Reaper
    "WorkloadReaper",
    # Lifecycle
    "SandboxLifecycleManager",
    "StateTransition",
    # Providers
    "ContainerSandboxProvider",
    "PodmanSandboxProvider",
    "DockerSandboxProvider",
    "LocalRestrictedSandboxProvider",
    "SandboxProvider",
    "SandboxRuntimeUnavailableError",
    # Manager
    "WorkloadSandboxManager",
    # Adapter
    "SandboxedWorkspaceEnvironment",
]
