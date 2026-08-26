"""Contracts of the AI Infrastructure Platform.

Interface-first architecture (Phase 7 brief §10): every component depends on
the abstractions below; concrete implementations are injected, typically at
the composition root.

Ports that decouple this platform from other packages:

- :class:`RuntimeCheckpointPort` — the Runtime State Manager's checkpoint
  boundary. Durable checkpoints remain owned by the Runtime; this platform
  never creates a second checkpoint system.
- :class:`CanonicalEventSink` — the canonical event boundary
  (``autoforge_event_platform.adapter.CanonicalEventBus`` satisfies it
  structurally). Only frozen ``autoforge_events`` types are published.
- :class:`ModelExecutor` — the provider-neutral execution seam where real
  provider adapters plug in (future provider integration).
"""

from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from enum import Enum
from typing import Any, Protocol, runtime_checkable

from autoforge_events.base import BaseEvent

from autoforge_ai_infrastructure.metadata import (
    CapabilityMetadata,
    DeploymentMetadata,
    ModelMetadata,
    ModelQuery,
    ProviderMetadata,
    ProviderStatus,
)


# ---------------------------------------------------------------------------
# Capability Registry contract
# ---------------------------------------------------------------------------


class CapabilityRegistryPort(ABC):
    """Authoritative AI infrastructure metadata registry.

    Metadata ONLY: it never routes, never executes, never retries and never
    performs failover (ARCHITECTURE.md §Capability Registry).
    """

    # -- capabilities -------------------------------------------------------
    @abstractmethod
    def register_capability(self, capability: CapabilityMetadata) -> None:
        """Register a capability definition."""

    @abstractmethod
    def get_capability(self, capability_id: str) -> CapabilityMetadata | None: ...

    @abstractmethod
    def list_capabilities(self) -> list[CapabilityMetadata]: ...

    # -- providers ----------------------------------------------------------
    @abstractmethod
    def register_provider(self, provider: ProviderMetadata) -> None: ...

    @abstractmethod
    def get_provider(self, provider_id: str) -> ProviderMetadata | None: ...

    @abstractmethod
    def list_providers(self) -> list[ProviderMetadata]: ...

    @abstractmethod
    def set_provider_status(
        self,
        provider_id: str,
        status: ProviderStatus,
        *,
        reason: str = "",
    ) -> ProviderMetadata:
        """Update provider health; raises UnknownEntityError if absent."""

    # -- models -------------------------------------------------------------
    @abstractmethod
    def register_model(
        self,
        model: ModelMetadata,
        *,
        strict_capabilities: bool = True,
    ) -> None:
        """Register a model. With ``strict_capabilities`` every declared
        capability must already be registered (typo protection)."""

    @abstractmethod
    def get_model(self, model_id: str) -> ModelMetadata | None: ...

    @abstractmethod
    def update_model_status(self, model_id: str, status: Any) -> ModelMetadata: ...

    # -- deployments --------------------------------------------------------
    @abstractmethod
    def register_deployment(self, deployment: DeploymentMetadata) -> None: ...

    @abstractmethod
    def get_deployments(self, model_id: str) -> list[DeploymentMetadata]: ...

    # -- querying -----------------------------------------------------------
    @abstractmethod
    def query_models(self, query: ModelQuery) -> list[ModelMetadata]:
        """Return models satisfying ALL hard constraints, ordered by id."""

    @abstractmethod
    def models_with_capability(self, capability_id: str) -> list[ModelMetadata]:
        """Every registered model (any status) declaring a capability."""


# ---------------------------------------------------------------------------
# Routing policy contract
# ---------------------------------------------------------------------------


class RoutingPolicy(ABC):
    """Explicit, injectable model-selection strategy."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Stable policy identifier recorded on every routing decision."""

    @abstractmethod
    def score(
        self,
        model: ModelMetadata,
        provider: ProviderMetadata | None,
        request: Any,
    ) -> float:
        """Deterministic score for a candidate against a routing request.

        Higher is better. Must be a pure function of its inputs so routing
        behaviour is reproducible and testable.
        """

    def describe(self) -> str:
        return f"RoutingPolicy({self.name})"


# ---------------------------------------------------------------------------
# Failure classification contract
# ---------------------------------------------------------------------------


class FailureClassification(str, Enum):
    """Outcome of classifying an execution failure."""

    RETRYABLE = "retryable"
    NON_RETRYABLE = "non_retryable"


class FailureClassifier(ABC):
    """Classifies execution failures for retry/failover decisions."""

    @abstractmethod
    def classify(self, error: BaseException) -> FailureClassification: ...


# ---------------------------------------------------------------------------
# Execution seam
# ---------------------------------------------------------------------------


@runtime_checkable
class ModelExecutor(Protocol):
    """Provider-neutral execution boundary.

    Real provider adapters implement this protocol and are bound per provider
    in :class:`autoforge_ai_infrastructure.execution.ExecutorRegistry`.
    """

    async def execute(
        self,
        request: Any,
        target: Any,
    ) -> Any:
        """Execute ``request`` against ``target`` (model+provider binding)."""
        ...


# ---------------------------------------------------------------------------
# Cross-package ports
# ---------------------------------------------------------------------------


@runtime_checkable
class RuntimeCheckpointPort(Protocol):
    """Structural port over the Runtime State Manager's checkpoint API.

    Method shapes mirror ``autoforge_runtime.RuntimeStateManager``; string
    parameters accept runtime enum *values* (composition adapts enums).
    """

    def create_checkpoint(
        self,
        project_id: uuid.UUID,
        checkpoint_type: str,
        label: str | None = None,
        description: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> uuid.UUID: ...

    def restore_checkpoint(
        self,
        checkpoint_id: uuid.UUID,
        restore_type: str = "full",
    ) -> Any: ...

    def get_checkpoint_history(self, project_id: uuid.UUID) -> list[Any]: ...


@runtime_checkable
class CanonicalEventSink(Protocol):
    """Structural port for publishing canonical domain events."""

    def publish(self, event: BaseEvent) -> Any: ...
