"""Capability Registry — authoritative AI infrastructure metadata.

Thread-safe in-memory implementation of
:class:`autoforge_ai_infrastructure.interfaces.CapabilityRegistryPort`.

Design rules (ARCHITECTURE.md §Capability Registry):

- Metadata only. It never selects models, executes requests, retries,
  performs failover or evaluates runtime failures.
- Providers, models and capabilities can be added, removed, upgraded or
  deprecated without architectural changes elsewhere.
- Query results are deterministically ordered (by identifier) so routing
  behaviour is reproducible.
"""

from __future__ import annotations

import threading
from typing import Any

from autoforge_ai_infrastructure.errors import (
    DuplicateRegistrationError,
    UnknownEntityError,
)
from autoforge_ai_infrastructure.interfaces import CapabilityRegistryPort
from autoforge_ai_infrastructure.metadata import (
    CapabilityMetadata,
    DeploymentMetadata,
    ModelMetadata,
    ModelQuery,
    ProviderMetadata,
    ProviderStatus,
)


class InMemoryCapabilityRegistry(CapabilityRegistryPort):
    """In-memory metadata registry with strict duplicate protection."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._capabilities: dict[str, CapabilityMetadata] = {}
        self._providers: dict[str, ProviderMetadata] = {}
        self._models: dict[str, ModelMetadata] = {}
        self._deployments: dict[str, list[DeploymentMetadata]] = {}

    # -- capabilities --------------------------------------------------------

    def register_capability(self, capability: CapabilityMetadata) -> None:
        with self._lock:
            if capability.capability_id in self._capabilities:
                raise DuplicateRegistrationError(
                    f"Capability '{capability.capability_id}' already registered",
                    details={"capability_id": capability.capability_id},
                )
            self._capabilities[capability.capability_id] = capability

    def get_capability(self, capability_id: str) -> CapabilityMetadata | None:
        with self._lock:
            return self._capabilities.get(capability_id)

    def list_capabilities(self) -> list[CapabilityMetadata]:
        with self._lock:
            return [self._capabilities[k] for k in sorted(self._capabilities)]

    # -- providers -----------------------------------------------------------

    def register_provider(self, provider: ProviderMetadata) -> None:
        with self._lock:
            if provider.provider_id in self._providers:
                raise DuplicateRegistrationError(
                    f"Provider '{provider.provider_id}' already registered",
                    details={"provider_id": provider.provider_id},
                )
            self._providers[provider.provider_id] = provider

    def get_provider(self, provider_id: str) -> ProviderMetadata | None:
        with self._lock:
            return self._providers.get(provider_id)

    def list_providers(self) -> list[ProviderMetadata]:
        with self._lock:
            return [self._providers[k] for k in sorted(self._providers)]

    def set_provider_status(
        self,
        provider_id: str,
        status: ProviderStatus,
        *,
        reason: str = "",
    ) -> ProviderMetadata:
        """Record a provider health transition (observable, never silent)."""
        with self._lock:
            current = self._providers.get(provider_id)
            if current is None:
                raise UnknownEntityError(
                    f"Provider '{provider_id}' is not registered",
                    details={"provider_id": provider_id},
                )
            health = dict(current.health)
            transitions = list(health.get("status_transitions", []))
            transitions.append({"status": status.value, "reason": reason})
            health["status_transitions"] = transitions
            updated = current.model_copy(
                update={"status": status, "health": health}
            )
            self._providers[provider_id] = updated
            return updated

    # -- models --------------------------------------------------------------

    def register_model(
        self,
        model: ModelMetadata,
        *,
        strict_capabilities: bool = True,
    ) -> None:
        with self._lock:
            if model.model_id in self._models:
                raise DuplicateRegistrationError(
                    f"Model '{model.model_id}' already registered",
                    details={"model_id": model.model_id},
                )
            if model.provider_id not in self._providers:
                raise UnknownEntityError(
                    f"Model '{model.model_id}' references unknown provider "
                    f"'{model.provider_id}'",
                    details={
                        "model_id": model.model_id,
                        "provider_id": model.provider_id,
                    },
                )
            if strict_capabilities:
                unknown = model.capabilities - set(self._capabilities)
                if unknown:
                    raise UnknownEntityError(
                        f"Model '{model.model_id}' declares unregistered "
                        f"capabilities: {sorted(unknown)}",
                        details={
                            "model_id": model.model_id,
                            "unknown_capabilities": sorted(unknown),
                        },
                    )
            self._models[model.model_id] = model

    def get_model(self, model_id: str) -> ModelMetadata | None:
        with self._lock:
            return self._models.get(model_id)

    def update_model_status(self, model_id: str, status: Any) -> ModelMetadata:
        """Transition a model's lifecycle status; returns the new metadata."""
        with self._lock:
            current = self._models.get(model_id)
            if current is None:
                raise UnknownEntityError(
                    f"Model '{model_id}' is not registered",
                    details={"model_id": model_id},
                )
            updated = current.model_copy(update={"status": status})
            self._models[model_id] = updated
            return updated

    # -- deployments ---------------------------------------------------------

    def register_deployment(self, deployment: DeploymentMetadata) -> None:
        with self._lock:
            if deployment.model_id not in self._models:
                raise UnknownEntityError(
                    f"Deployment references unregistered model "
                    f"'{deployment.model_id}'",
                    details={"model_id": deployment.model_id},
                )
            entries = self._deployments.setdefault(deployment.model_id, [])
            for existing in entries:
                if existing.mode == deployment.mode:
                    raise DuplicateRegistrationError(
                        f"Deployment mode '{deployment.mode.value}' already "
                        f"registered for model '{deployment.model_id}'",
                        details={
                            "model_id": deployment.model_id,
                            "mode": deployment.mode.value,
                        },
                    )
            entries.append(deployment)
            entries.sort(key=lambda d: d.mode.value)

    def get_deployments(self, model_id: str) -> list[DeploymentMetadata]:
        with self._lock:
            return list(self._deployments.get(model_id, []))

    # -- querying ------------------------------------------------------------

    def query_models(self, query: ModelQuery) -> list[ModelMetadata]:
        """Return every model matching all hard constraints, ordered by
        ``model_id`` for deterministic routing."""
        with self._lock:
            candidates = list(self._models.values())

        matched: list[ModelMetadata] = []
        for model in candidates:
            provider = self._providers.get(model.provider_id)

            # Provider-level availability gates selection entirely.
            if provider is None or not provider.is_available:
                continue
            if model.status not in query.allowed_statuses:
                continue
            if model.provider_id in query.excluded_provider_ids:
                continue
            if model.model_id in query.excluded_model_ids:
                continue
            if not model.supports_all(query.required_capabilities):
                continue
            if (
                query.min_context_window_tokens is not None
                and model.context_window_tokens < query.min_context_window_tokens
            ):
                continue
            if query.allowed_deployment_modes is not None and not (
                model.deployment_modes & query.allowed_deployment_modes
            ):
                continue
            if (
                query.max_input_cost_per_million_tokens is not None
                and model.cost.cost_per_million_input_tokens is not None
                and model.cost.cost_per_million_input_tokens
                > query.max_input_cost_per_million_tokens
            ):
                continue
            if (
                query.max_output_cost_per_million_tokens is not None
                and model.cost.cost_per_million_output_tokens is not None
                and model.cost.cost_per_million_output_tokens
                > query.max_output_cost_per_million_tokens
            ):
                continue
            matched.append(model)

        matched.sort(key=lambda m: m.model_id)
        return matched

    def models_with_capability(self, capability_id: str) -> list[ModelMetadata]:
        with self._lock:
            candidates = list(self._models.values())
        matched = [m for m in candidates if capability_id in m.capabilities]
        matched.sort(key=lambda m: m.model_id)
        return matched

    # -- observability -------------------------------------------------------

    def snapshot_counts(self) -> dict[str, int]:
        """Registry census for observability/health reporting."""
        with self._lock:
            return {
                "capabilities": len(self._capabilities),
                "providers": len(self._providers),
                "models": len(self._models),
                "deployments": sum(len(v) for v in self._deployments.values()),
            }
