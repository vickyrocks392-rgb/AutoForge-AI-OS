"""Exception taxonomy for the AutoForge Orchestration Platform (Phase 18)."""

from __future__ import annotations

from typing import Any


class OrchestrationError(Exception):
    """Base error for all orchestration platform failures."""

    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}


class WorkflowStateError(OrchestrationError):
    """Invalid workflow/state transition or inconsistent execution state."""


class StageStateError(OrchestrationError):
    """Invalid stage state transition."""


class WorkerAssignmentError(OrchestrationError):
    """Capability-driven worker assignment could not resolve a worker."""


class ModelRoutingError(OrchestrationError):
    """Model/node routing failed for a stage."""


class RectificationLimitError(OrchestrationError):
    """A bounded rectification/autonomy limit was exhausted."""


class HITLGateError(OrchestrationError):
    """HITL gate request/decision error."""


class DeploymentUnavailableError(OrchestrationError):
    """Deployment is explicitly unavailable for the requested target."""


class PersistenceError(OrchestrationError):
    """Durable execution state could not be stored or restored."""


class SecurityBoundaryError(OrchestrationError):
    """A verification command or artifact path violated a security boundary."""