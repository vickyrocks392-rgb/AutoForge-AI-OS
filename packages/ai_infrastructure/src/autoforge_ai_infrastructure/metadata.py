"""AI infrastructure metadata models.

The Capability Registry is the authoritative AI infrastructure **metadata**
registry (ARCHITECTURE.md §17.1). Everything here is descriptive data:

- :class:`ProviderMetadata` — a provider independent of any implementation.
- :class:`ModelMetadata`    — a model independent of its provider adapter.
- :class:`CapabilityMetadata` — first-class capabilities.
- :class:`DeploymentMetadata` — where/how a model can execute
  (local / cloud / hybrid / distributed / edge / cluster).
- :class:`RoutingRequest` / :class:`ModelQuery` — selection-side contracts.

No concrete vendor appears anywhere in this module: providers are open,
string-identified entities registered at runtime. ``CapabilityIds`` offers
illustrative constants matching ARCHITECTURE.md §"Supported Features" but the
capability space is deliberately an *open set*.
"""

from __future__ import annotations

import uuid
from enum import Enum
from typing import Any

from pydantic import Field, model_validator

from autoforge_models.base import AutoForgeBaseModel


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class ProviderType(str, Enum):
    """Provider classification (MODEL_ROUTER.md §Supported Provider Types)."""

    CLOUD = "cloud"
    LOCAL_RUNTIME = "local_runtime"
    SELF_HOSTED = "self_hosted"


class ProviderStatus(str, Enum):
    """Health of a provider as observed/declared by operators."""

    AVAILABLE = "available"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"


class DeploymentMode(str, Enum):
    """Deployment classification (ARCHITECTURE.md §Deployment Characteristics).

    All six deployment types from Architecture v1.0 are representable; Phase 7
    routing semantics distinguish LOCAL (first-class, offline-capable) from
    everything remote.
    """

    LOCAL = "local"
    CLOUD = "cloud"
    HYBRID = "hybrid"
    DISTRIBUTED = "distributed"
    EDGE = "edge"
    CLUSTER = "cluster"


#: Modes that can execute without network access to remote infrastructure.
LOCAL_EXECUTABLE_MODES: frozenset[DeploymentMode] = frozenset(
    {DeploymentMode.LOCAL}
)


class ModelStatus(str, Enum):
    """Model lifecycle status (MODEL_ROUTER.md §Model Registry)."""

    ACTIVE = "active"
    DEGRADED = "degraded"
    DEPRECATED = "deprecated"
    RETIRED = "retired"


class Modality(str, Enum):
    """Supported input/output modality."""

    TEXT = "text"
    IMAGE = "image"
    AUDIO = "audio"
    VIDEO = "video"


class CapabilityIds:
    """Illustrative capability identifiers (open set — not an enum).

    Mirrors the examples in ARCHITECTURE.md §Supported Features and the
    Phase 7 brief. Custom capabilities may be registered freely.
    """

    TEXT_GENERATION = "text_generation"
    CODE_GENERATION = "code_generation"
    REASONING = "reasoning"
    STRUCTURED_OUTPUT = "structured_output"
    EMBEDDINGS = "embeddings"
    VISION = "vision"
    TOOL_USE = "tool_use"
    LONG_CONTEXT = "long_context_processing"


# ---------------------------------------------------------------------------
# Value objects
# ---------------------------------------------------------------------------


class CostSpec(AutoForgeBaseModel):
    """Provider-neutral cost abstraction.

    Costs are expressed per **million** tokens for readability. ``None``
    means billing information is unknown/not applicable (e.g. free local
    inference) — unknown cost sorts as the cheapest option because it cannot
    be billed.
    """

    cost_per_million_input_tokens: float | None = Field(
        default=None, ge=0.0, description="Input cost per 1M tokens; None = unknown/free."
    )
    cost_per_million_output_tokens: float | None = Field(
        default=None, ge=0.0, description="Output cost per 1M tokens; None = unknown/free."
    )

    @property
    def is_known(self) -> bool:
        """Whether any billing information exists."""
        return (
            self.cost_per_million_input_tokens is not None
            or self.cost_per_million_output_tokens is not None
        )

    def estimate(
        self,
        input_tokens: int = 1_000,
        output_tokens: int = 1_000,
    ) -> float | None:
        """Estimated monetary cost for a token workload; None if unknown.

        Partially known specs estimate only the known component.
        """
        if not self.is_known:
            return None
        total: float = 0.0
        if self.cost_per_million_input_tokens is not None:
            total += self.cost_per_million_input_tokens * input_tokens / 1_000_000
        if self.cost_per_million_output_tokens is not None:
            total += self.cost_per_million_output_tokens * output_tokens / 1_000_000
        return total


class ResourceConstraints(AutoForgeBaseModel):
    """Hardware footprint metadata for local deployment decisions.

    Exists so an 8 GB RAM laptop constraint is representable: the registry
    records what a model needs; operators decide what their machine has.
    """

    min_memory_mb: int | None = Field(
        default=None, ge=0, description="Minimum RAM required to run."
    )
    recommended_memory_mb: int | None = Field(
        default=None, ge=0, description="Recommended RAM."
    )
    requires_gpu: bool = Field(
        default=False, description="Whether a GPU is mandatory."
    )


class LatencyProfile(AutoForgeBaseModel):
    """Observed/declared latency characteristics."""

    typical_latency_ms: int | None = Field(
        default=None, ge=0, description="Typical end-to-end response latency."
    )
    p95_latency_ms: int | None = Field(
        default=None, ge=0, description="95th percentile latency."
    )


# ---------------------------------------------------------------------------
# Registry entries
# ---------------------------------------------------------------------------


class CapabilityMetadata(AutoForgeBaseModel):
    """A first-class capability (text generation, vision, tool use, ...)."""

    capability_id: str = Field(..., min_length=1, max_length=128)
    display_name: str = Field(..., min_length=1, max_length=256)
    description: str = Field(default="", max_length=2048)
    metadata: dict[str, Any] = Field(default_factory=dict)


class AuthRequirements(AutoForgeBaseModel):
    """Authentication requirements of a provider.

    Requirements are *names* only (e.g. ``"api_key"``, ``"none"``); secrets
    never live in metadata.
    """

    requirements: frozenset[str] = Field(default_factory=frozenset)

    @property
    def requires_credentials(self) -> bool:
        return self.requirements != frozenset({"none"}) and len(self.requirements) > 0


class ProviderMetadata(AutoForgeBaseModel):
    """A provider, independent of any adapter implementation."""

    provider_id: str = Field(..., min_length=1, max_length=128)
    display_name: str = Field(..., min_length=1, max_length=256)
    provider_type: ProviderType = Field(...)
    status: ProviderStatus = Field(default=ProviderStatus.AVAILABLE)
    endpoint: str | None = Field(default=None, max_length=2048)
    auth: AuthRequirements = Field(default_factory=AuthRequirements)
    supported_capabilities: frozenset[str] = Field(default_factory=frozenset)
    deployment_modes: frozenset[DeploymentMode] = Field(default_factory=frozenset)
    rate_limit_requests_per_minute: int | None = Field(default=None, ge=1)
    rate_limit_tokens_per_minute: int | None = Field(default=None, ge=1)
    health: dict[str, Any] = Field(
        default_factory=dict,
        description="Free-form health/observability metadata.",
    )

    @property
    def is_available(self) -> bool:
        return self.status == ProviderStatus.AVAILABLE

    @property
    def is_local_capable(self) -> bool:
        return bool(self.deployment_modes & LOCAL_EXECUTABLE_MODES)


class ModelMetadata(AutoForgeBaseModel):
    """A model, independent of its provider implementation."""

    model_id: str = Field(..., min_length=1, max_length=128)
    display_name: str = Field(..., min_length=1, max_length=256)
    provider_id: str = Field(..., min_length=1, max_length=128)
    family: str | None = Field(default=None, max_length=128)
    version: str | None = Field(default=None, max_length=64)
    status: ModelStatus = Field(default=ModelStatus.ACTIVE)
    context_window_tokens: int = Field(..., ge=1)
    max_output_tokens: int | None = Field(default=None, ge=1)
    capabilities: frozenset[str] = Field(default_factory=frozenset)
    input_modalities: frozenset[Modality] = Field(
        default_factory=lambda: frozenset({Modality.TEXT})
    )
    output_modalities: frozenset[Modality] = Field(
        default_factory=lambda: frozenset({Modality.TEXT})
    )
    cost: CostSpec = Field(default_factory=CostSpec)
    latency: LatencyProfile = Field(default_factory=LatencyProfile)
    throughput_tokens_per_second: float | None = Field(default=None, gt=0.0)
    #: Quality tier 1..4 (MODEL_ROUTER.md §Model Registry); 4 = strongest.
    quality_tier: int = Field(default=2, ge=1, le=4)
    reliability: float = Field(default=1.0, ge=0.0, le=1.0)
    deployment_modes: frozenset[DeploymentMode] = Field(default_factory=frozenset)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @property
    def is_locally_executable(self) -> bool:
        return bool(self.deployment_modes & LOCAL_EXECUTABLE_MODES)

    def supports_all(self, capability_ids: frozenset[str] | set[str]) -> bool:
        return capability_ids <= self.capabilities


class DeploymentMetadata(AutoForgeBaseModel):
    """Where/how a specific model can be deployed."""

    model_id: str = Field(..., min_length=1, max_length=128)
    mode: DeploymentMode = Field(...)
    environment: str | None = Field(
        default=None,
        max_length=256,
        description="Named environment, e.g. '8gb_ram_laptop'.",
    )
    resource_constraints: ResourceConstraints = Field(
        default_factory=ResourceConstraints
    )
    runtime_hints: dict[str, Any] = Field(
        default_factory=dict,
        description="Deployment hints (quantisation, runtime flags...).",
    )


# ---------------------------------------------------------------------------
# Selection-side contracts
# ---------------------------------------------------------------------------


class RoutingRequest(AutoForgeBaseModel):
    """What the caller needs from the Model Router."""

    required_capabilities: frozenset[str] = Field(default_factory=frozenset)
    min_context_window_tokens: int | None = Field(default=None, ge=1)
    #: Hard deployment restriction; None means any mode is acceptable.
    allowed_deployment_modes: frozenset[DeploymentMode] | None = Field(default=None)
    #: Convenience flag: restricts selection to locally executable candidates.
    offline_only: bool = Field(default=False)
    max_input_cost_per_million_tokens: float | None = Field(default=None, ge=0.0)
    max_output_cost_per_million_tokens: float | None = Field(default=None, ge=0.0)
    excluded_provider_ids: frozenset[str] = Field(default_factory=frozenset)
    excluded_model_ids: frozenset[str] = Field(default_factory=frozenset)
    #: Reference workload used by cost-aware policies (defaults 1k/1k tokens).
    reference_input_tokens: int = Field(default=1_000, ge=0)
    reference_output_tokens: int = Field(default=1_000, ge=0)
    quality_priority: int | None = Field(default=None, ge=1, le=5)
    latency_priority: str | None = Field(default=None)
    reliability_minimum: float | None = Field(default=None, ge=0.0, le=1.0)
    preferred_capabilities: frozenset[str] = Field(default_factory=frozenset)

    @model_validator(mode="after")
    def _validate(self) -> "RoutingRequest":
        if not self.required_capabilities and self.min_context_window_tokens is None:
            raise ValueError(
                "routing request must require at least one capability or a "
                "minimum context window"
            )
        return self

    def effective_allowed_deployment_modes(
        self,
    ) -> frozenset[DeploymentMode] | None:
        """The deployment-mode restriction AFTER applying offline mode.

        ``offline_only`` is a hard constraint: it restricts selection to
        locally executable modes regardless of any explicitly allowed modes.
        Returns ``None`` when no deployment restriction applies.
        """
        if self.offline_only:
            return LOCAL_EXECUTABLE_MODES
        return self.allowed_deployment_modes


class ModelQuery(AutoForgeBaseModel):
    """Hard-constraint query evaluated by the Capability Registry."""

    required_capabilities: frozenset[str] = Field(default_factory=frozenset)
    min_context_window_tokens: int | None = Field(default=None, ge=1)
    allowed_deployment_modes: frozenset[DeploymentMode] | None = Field(default=None)
    allowed_statuses: frozenset[ModelStatus] = Field(
        default_factory=lambda: frozenset({ModelStatus.ACTIVE})
    )
    excluded_provider_ids: frozenset[str] = Field(default_factory=frozenset)
    excluded_model_ids: frozenset[str] = Field(default_factory=frozenset)
    max_input_cost_per_million_tokens: float | None = Field(default=None, ge=0.0)
    max_output_cost_per_million_tokens: float | None = Field(default=None, ge=0.0)


# ---------------------------------------------------------------------------
# Continuity data shapes
# ---------------------------------------------------------------------------


class AttemptRecord(AutoForgeBaseModel):
    """One execution attempt observation (immutable audit entry).

    Preserved across retries/failovers as part of execution context so any
    observer can reconstruct exactly what happened without re-running.
    """

    execution_id: uuid.UUID = Field(...)
    model_id: str = Field(..., min_length=1)
    provider_id: str = Field(..., min_length=1)
    attempt_number: int = Field(..., ge=1)
    error: BaseException | None = Field(
        default=None,
        description="The raised error, if the attempt failed.",
    )
    classification: str = Field(
        default="not_attempted",
        description="FailureClassification value ('retryable'/'non_retryable'), "
        "or 'not_attempted' for successful attempts.",
    )
    succeeded: bool = Field(default=False)
    followed_by_failover: bool = Field(default=False)

    #: Holds an arbitrary exception object; only ``summary()`` ever
    #: serializes it (to a JSON-safe shape).
    model_config = {
        "extra": "forbid",
        "populate_by_name": True,
        "frozen": True,
        "arbitrary_types_allowed": True,
    }

    def summary(self) -> dict[str, Any]:
        """JSON-safe summary for event metadata and reports."""
        return {
            "execution_id": str(self.execution_id),
            "model_id": self.model_id,
            "provider_id": self.provider_id,
            "attempt_number": self.attempt_number,
            "succeeded": self.succeeded,
            "classification": self.classification,
            "error_type": type(self.error).__name__ if self.error else None,
            "error_message": str(self.error)[:512] if self.error else None,
            "followed_by_failover": self.followed_by_failover,
        }


