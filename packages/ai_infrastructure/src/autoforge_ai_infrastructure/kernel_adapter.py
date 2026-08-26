"""Adapters implementing the Kernel's frozen service ABCs.

The Kernel depends on contract ABCs in
:mod:`autoforge_kernel.interfaces` (:class:`ModelRouter`,
:class:`ExecutionContinuityManager`). These adapters make the AI
Infrastructure Platform injectable into the Kernel through those contracts
without the Kernel ever knowing this platform exists.

This is a dependency-inversion boundary: ``autoforge_kernel`` defines the
interfaces; this package (and the composition root) supplies implementations.
"""

from __future__ import annotations

import uuid
from typing import Any

from autoforge_models.enums import ModelProvider
from autoforge_models.model_profile import ModelProfile

from autoforge_kernel.interfaces import (
    ExecutionContinuityManager,
    ModelRouter,
)

from autoforge_ai_infrastructure.errors import NoEligibleModelError
from autoforge_ai_infrastructure.interfaces import CapabilityRegistryPort
from autoforge_ai_infrastructure.metadata import RoutingRequest
from autoforge_ai_infrastructure.router import ModelRouterService


def routing_request_from_task(task: dict[str, Any]) -> RoutingRequest:
    """Translate a Kernel task dict into a :class:`RoutingRequest`.

    Accepted task keys (provider-agnostic):
        ``required_capabilities`` / ``capabilities``,
        ``min_context_window_tokens``,
        ``offline_only``,
        ``excluded_providers`` / ``exclude_provider``.
    When neither a capability nor a context requirement is present the safest
    universal default (text generation) is used so a missing signal degrades
    predictably rather than raising on every intake.
    """
    caps = frozenset(
        task.get("required_capabilities") or task.get("capabilities") or []
    )
    min_ctx = task.get("min_context_window_tokens")
    exclusions = frozenset(task.get("excluded_providers") or [])
    single = task.get("exclude_provider")
    if single:
        exclusions = exclusions | {single}
    if not caps and min_ctx is None:
        caps = frozenset({"text_generation"})
    return RoutingRequest(
        required_capabilities=caps,
        min_context_window_tokens=min_ctx,
        offline_only=bool(task.get("offline_only", False)),
        allowed_deployment_modes=(
            frozenset(task["allowed_deployment_modes"])
            if task.get("allowed_deployment_modes")
            else None
        ),
        excluded_provider_ids=exclusions,
    )


def _provider_enum(model_id: str, registry: CapabilityRegistryPort) -> ModelProvider:
    """Map a registered model to the Kernel's coarse provider enum.

    LOCAL runtime models map to ``ModelProvider.LOCAL``; everything else
    (cloud/self-hosted) maps to ``ModelProvider.CUSTOM``. The Kernel should
    not depend on provider identity beyond this coarse distinction.
    """
    model = registry.get_model(model_id)
    if model is not None and model.is_locally_executable:
        return ModelProvider.LOCAL
    return ModelProvider.CUSTOM


class KernelModelRouter(ModelRouter):
    """Implementation of the Kernel's ``ModelRouter`` ABC over this platform."""

    def __init__(
        self,
        router: ModelRouterService,
        registry: CapabilityRegistryPort,
    ) -> None:
        self._router = router
        self._registry = registry

    async def select_model(
        self,
        task: dict[str, Any],
        exclude_provider: str | None = None,
    ) -> ModelProfile:
        request = routing_request_from_task(task)
        if exclude_provider:
            decision = self._router.route_excluding_providers(
                request, frozenset({exclude_provider})
            )
        else:
            decision = self._router.route(request)
        candidate = decision.selected
        model = candidate.model
        return ModelProfile(
            name=model.display_name,
            provider=_provider_enum(model.model_id, self._registry),
            model_name=model.model_id,
            max_context_length=model.context_window_tokens,
            default_max_tokens=model.max_output_tokens or 4096,
            supports_streaming=False,
            supports_functions=bool("tool_use" in model.capabilities),
            is_active=model.status.value == "active",
            cost_per_input_token=(
                model.cost.cost_per_million_input_tokens / 1_000_000
                if model.cost.cost_per_million_input_tokens is not None
                else None
            ),
            cost_per_output_token=(
                model.cost.cost_per_million_output_tokens / 1_000_000
                if model.cost.cost_per_million_output_tokens is not None
                else None
            ),
            tags=sorted(model.capabilities),
            metadata={
                "ai_infrastructure": True,
                "policy": decision.policy_name,
                "deployment_modes": [m.value for m in model.deployment_modes],
                "provider_id": model.provider_id,
                "rationale": decision.rationale,
            },
        )

    async def get_model_capabilities(self, model_id: str) -> dict[str, Any]:
        model = self._registry.get_model(model_id)
        if model is None:
            raise NoEligibleModelError(
                f"Model '{model_id}' not registered",
                details={"model_id": model_id},
            )
        return {
            "model_id": model.model_id,
            "provider_id": model.provider_id,
            "capabilities": sorted(model.capabilities),
            "context_window_tokens": model.context_window_tokens,
            "deployment_modes": [m.value for m in model.deployment_modes],
            "locally_executable": model.is_locally_executable,
            "status": model.status.value,
        }

    async def get_provider_health(self) -> dict[str, Any]:
        health: dict[str, Any] = {}
        for provider in self._registry.list_providers():
            health[provider.provider_id] = {
                "status": provider.status.value,
                "available": provider.is_available,
                "local_capable": provider.is_local_capable,
            }
        return health


class KernelContinuityManager(ExecutionContinuityManager):
    """Implementation of the Kernel's ``ExecutionContinuityManager`` ABC over
    the Execution Continuity Service."""

    def __init__(self, service: Any) -> None:
        self._service = service
        self._checkpoints = getattr(service, "_checkpoints", None)

    async def retry(self, task_id: uuid.UUID, context: dict[str, Any]) -> dict[str, Any]:
        preserved = self._service.get_preserved_context(task_id)
        if preserved is not None:
            try:
                result = await self._service.resume(task_id)
                return {
                    "success": True,
                    "resumed": True,
                    "model_id": result.model_id,
                    "provider_id": result.provider_id,
                    "attempts": result.attempts,
                    "failovers": result.failovers,
                }
            except Exception as exc:
                return {
                    "success": False,
                    "resumed": True,
                    "error_type": type(exc).__name__,
                    "error": str(exc)[:512],
                }
        return {
            "success": False,
            "resumed": False,
            "error": "no preserved context for execution",
        }

    async def failover(
        self, task_id: uuid.UUID, failed_provider: str
    ) -> dict[str, Any]:
        preserved = self._service.get_preserved_context(task_id)
        if preserved is None:
            return {
                "success": False,
                "error": "no preserved context for execution",
            }
        try:
            result = await self._service.resume(task_id)
            return {
                "success": True,
                "switched_from": failed_provider,
                "model_id": result.model_id,
                "provider_id": result.provider_id,
                "failovers": result.failovers,
            }
        except Exception as exc:
            return {
                "success": False,
                "switched_from": failed_provider,
                "error_type": type(exc).__name__,
                "error": str(exc)[:512],
            }

    async def restore_checkpoint(self, checkpoint_id: uuid.UUID) -> dict[str, Any]:
        if self._checkpoints is None:
            return {
                "success": False,
                "error": "runtime checkpoint port not configured",
            }
        try:
            result = self._checkpoints.restore_checkpoint(checkpoint_id, "full")
            return {
                "success": True,
                "checkpoint_id": str(checkpoint_id),
                "runtime_result": result,
            }
        except Exception as exc:
            return {
                "success": False,
                "checkpoint_id": str(checkpoint_id),
                "error_type": type(exc).__name__,
                "error": str(exc)[:512],
            }

    async def recover(self, failure_context: dict[str, Any]) -> dict[str, Any]:
        execution_id = failure_context.get("execution_id")
        if execution_id is not None:
            try:
                execution_uuid = uuid.UUID(str(execution_id))
            except (ValueError, TypeError):
                execution_uuid = None
            if execution_uuid is not None:
                return await self.retry(execution_uuid, failure_context)
        project_id = failure_context.get("project_id")
        if project_id is not None:
            try:
                outcome = self._service.recover_from_checkpoint(
                    uuid.UUID(str(project_id))
                )
                return {"success": True, "checkpoint_recovery": outcome}
            except Exception as exc:
                return {
                    "success": False,
                    "error_type": type(exc).__name__,
                    "error": str(exc)[:512],
                }
        return {
            "success": False,
            "error": "recovery requires execution_id or project_id",
        }