"""Gate C -- Canonical engineering-lifecycle taxonomy (Phase C1).

A faithful, dependency-free extraction of the O-1 engineering lifecycle
*taxonomy*:

* ``StageStatus``   -- ``autoforge_orchestration.models:97-121``
* ``StageKind``     -- ``autoforge_orchestration.models:63-94``
* the deterministic transition table and predicates
  -- ``autoforge_orchestration.states:13-107``
* the stage state error -- ``autoforge_orchestration.errors:21-22``
* stage retry/rectification defaults -- ``autoforge_orchestration.models:169-170``

Why this exists
---------------
O-1 owns the only explicit, deterministic engineering *stage* state machine in
the platform. O-2 (``DefaultOrchestrationEngine``) has no stage taxonomy: it
advances through ``ExecutableWorkflow.loops`` and keys every decision off the
four loop outcome strings. The taxonomy is genuinely unique and is pure table
lookup -- no I/O, no model call, no state.

O-1 quarantine
--------------
This module imports **nothing** from ``autoforge_orchestration``. It copies the
*definitions* rather than re-exporting them, so the canonical path can never
reach the O-1 orchestrator through it. ``test_lifecycle_taxonomy_contract.py``
proves this by AST scan and by asserting ``autoforge_orchestration`` is absent
from ``sys.modules`` after importing this module.

Placement
---------
Placed in ``autoforge_composition`` for the same reason as the B2
``ExecutionOutcome`` contract: this package owns canonical boundary adaptation.
It imports only the Python standard library, so any layer may reuse it.

Semantic fidelity
-----------------
Names, enum values, transition edges, terminality predicates and the exact
``StageStateError.details`` payload are reproduced verbatim. Nothing is renamed
and no edge is added or removed; equivalence against the live O-1 definitions is
asserted in the test module.
"""

from __future__ import annotations

from enum import Enum
from typing import Any

__all__ = [
    "LifecycleContractError",
    "StageStateError",
    "StageStatus",
    "StageKind",
    "DEFAULT_STAGE_MAX_ATTEMPTS",
    "DEFAULT_STAGE_MAX_RECTIFICATIONS",
    "O1_ORCHESTRATOR_MAX_ATTEMPTS_PER_STAGE",
    "get_allowed_stage_transitions",
    "is_stage_terminal",
    "is_stage_successful_terminal",
    "is_stage_failed_terminal",
    "validate_stage_transition",
    "transition_stage",
]


# ── Errors ──────────────────────────────────────────────────────────────────
# O-1 mapping:  OrchestrationError -> LifecycleContractError
#               StageStateError   -> StageStateError (name kept byte-identical;
#                                    only the base class is re-homed, because
#                                    O-1's base would require importing
#                                    autoforge_orchestration).


class LifecycleContractError(Exception):
    """Base error for canonical lifecycle contract violations.

    Mirrors ``autoforge_orchestration.errors.OrchestrationError``: same
    constructor signature and the same ``.message`` / ``.details`` attributes,
    so consumers written against O-1 behave identically.
    """

    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}


class StageStateError(LifecycleContractError):
    """Invalid stage state transition."""


# ── Taxonomy ────────────────────────────────────────────────────────────────


class StageStatus(str, Enum):
    """Explicit engineering-stage lifecycle states.

        PENDING  -> READY | BLOCKED | SKIPPED | CANCELLED
        READY    -> RUNNING | BLOCKED | CANCELLED
        RUNNING  -> SUCCEEDED | FAILED | RETRYING | WAITING_FOR_HITL | CANCELLED
        RETRYING -> RUNNING | FAILED | CANCELLED
        WAITING_FOR_HITL -> RUNNING | FAILED | CANCELLED
        BLOCKED  -> READY | CANCELLED
        FAILED   -> RETRYING | CANCELLED   (caller checks bounds before re-entry)
        SUCCEEDED / SKIPPED / CANCELLED (terminal)
    """

    PENDING = "pending"
    READY = "ready"
    RUNNING = "running"
    BLOCKED = "blocked"
    WAITING_FOR_HITL = "waiting_for_hitl"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SKIPPED = "skipped"
    CANCELLED = "cancelled"
    RETRYING = "retrying"


class StageKind(str, Enum):
    """Canonical pipeline stage kinds (GREENFIELD + LEGACY modernization)."""

    # Greenfield
    IDEA = "idea"
    INTENT = "intent"
    RESEARCH = "research"
    PLANNING = "planning"
    ARCHITECTURE = "architecture"
    DESIGN = "design"
    IMPLEMENTATION = "implementation"
    TESTING = "testing"
    EVALUATION = "evaluation"
    DIAGNOSIS = "diagnosis"
    REPAIR = "repair"
    REIMPLEMENTATION = "reimplementation"
    RETEST = "retesting"
    REVIEW = "review"
    ARTIFACT = "artifact"
    DEPLOYMENT = "deployment"

    # Legacy modernization
    LEGACY_DISCOVERY = "legacy_discovery"
    LEGACY_ARCHAEOLOGY = "legacy_archaeology"
    ARCHITECTURE_RECONSTRUCTION = "architecture_reconstruction"
    BUSINESS_RULES_EXTRACTION = "business_rules_extraction"
    DEPENDENCY_ANALYSIS = "dependency_analysis"
    MODERNIZATION_ARCHITECTURE = "modernization_architecture"
    MIGRATION_IMPLEMENTATION = "migration_implementation"
    EQUIVALENCE_VALIDATION = "equivalence_validation"
    LEGACY_VALIDATION = "legacy_validation"
    CUTOVER = "cutover"


# ── Retry / rectification bounds ────────────────────────────────────────────
# O-1 ``StageDefinition`` defaults (models.py:169-170). These bound re-entry
# into a stage; they are NOT a general retry policy -- that already exists and
# is consumed by the canonical Workflows path
# (``autoforge_workflows.models.RetryPolicy`` + ``autoforge_workflows.retry``,
# driven from ``autoforge_workflows.engine:456-459``), which O-2 reaches through
# worker dispatch. These constants exist so a canonical stage-level caller can
# bound re-entry without importing O-1's definition objects.

DEFAULT_STAGE_MAX_ATTEMPTS = 2
DEFAULT_STAGE_MAX_RECTIFICATIONS = 2

# O-1 additionally bounds attempts from the *engine* configuration
# (``OrchestrationConfig.max_attempts_per_stage = 3``, orchestrator.py:170).
# Recorded as provenance only; O-2 does not consume it.
O1_ORCHESTRATOR_MAX_ATTEMPTS_PER_STAGE = 3


# ── Deterministic transition table ──────────────────────────────────────────
# Verbatim from autoforge_orchestration/states.py:13-59.

_STAGE_TRANSITIONS: dict[StageStatus, frozenset[StageStatus]] = {
    StageStatus.PENDING: frozenset({
        StageStatus.READY,
        StageStatus.BLOCKED,
        StageStatus.SKIPPED,
        StageStatus.CANCELLED,
    }),
    StageStatus.READY: frozenset({
        StageStatus.RUNNING,
        StageStatus.BLOCKED,
        StageStatus.CANCELLED,
    }),
    StageStatus.RUNNING: frozenset({
        StageStatus.SUCCEEDED,
        StageStatus.FAILED,
        StageStatus.RETRYING,
        StageStatus.WAITING_FOR_HITL,
        StageStatus.CANCELLED,
    }),
    StageStatus.RETRYING: frozenset({
        StageStatus.RUNNING,
        StageStatus.FAILED,
        StageStatus.CANCELLED,
    }),
    StageStatus.WAITING_FOR_HITL: frozenset({
        StageStatus.RUNNING,
        StageStatus.FAILED,
        StageStatus.CANCELLED,
    }),
    StageStatus.BLOCKED: frozenset({
        StageStatus.READY,
        StageStatus.CANCELLED,
    }),
    StageStatus.FAILED: frozenset({
        StageStatus.RETRYING,
        StageStatus.CANCELLED,
    }),
    StageStatus.SUCCEEDED: frozenset(),      # terminal
    StageStatus.SKIPPED: frozenset(),        # terminal
    StageStatus.CANCELLED: frozenset(),      # terminal
}

_TERMINAL_STATES: frozenset[StageStatus] = frozenset({
    StageStatus.SUCCEEDED,
    StageStatus.SKIPPED,
    StageStatus.CANCELLED,
})


def validate_stage_transition(
    current: StageStatus,
    target: StageStatus,
    *,
    stage_id: str | None = None,
) -> None:
    """Validate a StageStatus transition; raise StageStateError on violation."""
    allowed = _STAGE_TRANSITIONS.get(current, frozenset())
    if target not in allowed:
        label = f" (stage_id={stage_id!r})" if stage_id else ""
        raise StageStateError(
            f"Invalid stage transition: {current.value!r} -> {target.value!r}{label}",
            details={
                "current": current.value,
                "target": target.value,
                "allowed": sorted(s.value for s in allowed),
                "stage_id": stage_id,
            },
        )


def get_allowed_stage_transitions(current: StageStatus) -> frozenset[StageStatus]:
    """Return the states reachable in one step from ``current``."""
    return _STAGE_TRANSITIONS.get(current, frozenset())


def is_stage_terminal(status: StageStatus) -> bool:
    """True when no further transition is possible."""
    return status in _TERMINAL_STATES


def is_stage_successful_terminal(status: StageStatus) -> bool:
    """True only for SUCCEEDED -- the terminal state that represents success."""
    return status == StageStatus.SUCCEEDED


def is_stage_failed_terminal(status: StageStatus, attempt: int, max_attempts: int) -> bool:
    """A stage is terminally failed when FAILED AND the retry budget is spent.

    This is the boundedness predicate: once ``attempt >= max_attempts`` the
    FAILED state is terminal and no further re-entry is permitted. It is what
    prevents an unbounded remediation loop.
    """
    return status == StageStatus.FAILED and attempt >= max_attempts


def transition_stage(
    stage_id: str,
    current: StageStatus,
    target: StageStatus,
) -> StageStatus:
    """Apply a validated transition; returns the new status."""
    validate_stage_transition(current, target, stage_id=stage_id)
    return target
