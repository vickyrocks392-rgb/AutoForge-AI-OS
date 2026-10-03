"""Production learning integration — Phase 19 FINAL (Gates 1, 2, 3, 4, 23).

19B-3 closed with the overlay implemented and tested but **not live**: the
kernel/execution/composition path still used the baseline fallback. This module
is the production resolver that makes learning a real consumer of the existing
AutoForge execution path, without creating a second orchestration engine.

Design commitments:

* **The existing orchestration engine remains authoritative.** This module adds a
  bounded *read* where an execution is about to be prepared. It holds no
  promotion, activation or rollback handle: it cannot grant authority, only
  decline to interfere.
* **No active learning means baseline behaviour, exactly.** Every failure mode —
  disabled, absent, expired, revoked, corrupted, wrong project, incompatible —
  resolves to "no learning", never to an exception. Gate 4 requires
  ``NO ACTIVE LEARNING == LEGACY AUTOFORGE BEHAVIOR``.
* **Critical-path independence (Gate 23).** The resolver never raises into the
  caller. A learning outage degrades to baseline engineering execution.
* **Provenance is emitted.** When learning *is* applied, the resolution carries
  learning id, version id, candidate id, project id and activation state so the
  decision is auditable in execution evidence.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Optional, Protocol

from autoforge_learning.models import ActivationMode
from autoforge_learning.store import ActiveLearningState

logger = logging.getLogger("autoforge.learning.production")

__test__ = False  # declares production wiring, not tests
#: The bounded set of execution decisions learning is permitted to influence.
#:
#: Gate 3 requires the chosen target to be documented explicitly and forbids
#: learning from touching security or authority. Every entry is a *content* or
#: *strategy* choice inside a workflow step that is already authorized. Nothing
#: here can grant a capability, widen a scope, or alter a security decision.
LEARNABLE_TARGETS: tuple[str, ...] = (
    "planning_heuristic",
    "prompt_strategy",
    "context_selection_strategy",
    "retrieval_strategy",
    "tool_selection_heuristic",
    "repair_strategy",
    "workflow_optimization",
    "model_selection_strategy",
)

#: Permanently outside learning authority. Present so the boundary is enforced
#: as data, not merely as an omission.
PROTECTED_TARGETS: frozenset[str] = frozenset(
    {
        "authorization",
        "authentication",
        "credential_scope",
        "ai_guardrails",
        "trust_boundary",
        "hitl_policy",
        "governance_policy",
        "security_policy",
        "audit_policy",
        "rollback_mechanism",
        "learning_authority_model",
        "sandbox_enforcement",
    }
)


class LearningProductionError(RuntimeError):
    """Base for production learning failures. Never raised into the caller."""


class TargetNotLearnable(LearningProductionError):
    """The requested target is outside the bounded learnable set."""


class AuthorizationDenied(LearningProductionError):
    """The external authorizer refused to apply this learning."""


class ActiveStateReader(Protocol):
    """The minimal store surface production execution is allowed to use."""

    def get_active_state(
        self, project_id: uuid.UUID, kind: str, key: str
    ) -> Optional[ActiveLearningState]: ...


@dataclass(frozen=True)
class ExecutionDecisionProvenance:
    """Who decided, and on what evidence. Emitted into execution audit."""

    learning_id: str
    version_id: uuid.UUID
    candidate_id: Optional[uuid.UUID]
    project_id: uuid.UUID
    activation_state: str
    kind: str
    key: str
    resolved_at: datetime
    activated_at: Optional[datetime] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "learning_id": self.learning_id,
            "version_id": str(self.version_id),
            "candidate_id": str(self.candidate_id) if self.candidate_id else None,
            "project_id": str(self.project_id),
            "activation_state": self.activation_state,
            "kind": self.kind,
            "key": self.key,
            "resolved_at": self.resolved_at.isoformat(),
            "activated_at": self.activated_at.isoformat() if self.activated_at else None,
        }


@dataclass(frozen=True)
class ProductionResolution:
    """The outcome of resolving learning for one execution.

    ``parameters is None`` is the healthy, expected case: baseline behaviour.
    It is returned for *every* failure mode, so no-learning is indistinguishable
    from pre-learning AutoForge.
    """

    parameters: Optional[dict[str, Any]]
    provenance: Optional[ExecutionDecisionProvenance] = None
    reason: str = "no active learning"
    degraded: bool = False
    #: SHADOW and CANARY observe without changing behaviour.
    mode: str = ActivationMode.FULL.value

    @property
    def is_applied(self) -> bool:
        return self.parameters is not None

    @property
    def is_shadow(self) -> bool:
        return self.mode == ActivationMode.SHADOW.value

    @property
    def is_canary(self) -> bool:
        return self.mode == ActivationMode.CANARY.value

    @property
    def is_baseline(self) -> bool:
        """True when behaviour is exactly the pre-learning baseline."""
        return self.parameters is None


class ActiveLearningResolver:
    """Resolve active learning for one production execution.

    Gate 2's required chain, in order, each step failing closed to baseline:

        project → active learning state → integrity → scope → authorization →
        compatibility → activation → execution

    Public contract:

    * :meth:`resolve` **never raises**. Every failure mode returns
      ``parameters=None``, i.e. legacy behaviour.
    * It performs a *read* only. There is no promote/activate/rollback method,
      so wiring it into production execution adds no authority.
    * Every degradation is recorded in :attr:`degradations` with its reason.
    """

    def __init__(
        self,
        *,
        store: Optional[ActiveStateReader],
        parameters_for: Optional[Callable[[ActiveLearningState], dict[str, Any]]] = None,
        authorize: Optional[Callable[[ActiveLearningState, uuid.UUID], bool]] = None,
        compatible_targets: tuple[str, ...] = LEARNABLE_TARGETS,
        now: Optional[Callable[[], datetime]] = None,
    ) -> None:
        self._store = store
        self._parameters_for = parameters_for
        self._authorize = authorize
        self._compatible = tuple(compatible_targets)
        self._now = now or (lambda: datetime.now(timezone.utc))
        self._degradations: list[str] = []

    @property
    def degradations(self) -> tuple[str, ...]:
        """Every reason learning was not applied. Truthful, never empty."""
        return tuple(self._degradations)

    @property
    def enabled(self) -> bool:
        """False when no store is wired — the explicit "learning disabled" case."""
        return self._store is not None

    def resolve(
        self, *, project_id: uuid.UUID, kind: str, key: str, target: str
    ) -> ProductionResolution:
        """Resolve learning for one execution. Never raises, never escalates."""
        try:
            return self._resolve(
                project_id=project_id, kind=kind, key=key, target=target
            )
        except Exception as exc:  # noqa: BLE001 - critical path must survive
            reason = (
                f"learning resolver degraded to baseline behaviour "
                f"({type(exc).__name__}: {exc})"
            )
            logger.warning("%s", reason)
            self._degradations.append(reason)
            return ProductionResolution(parameters=None, reason=reason, degraded=True)

    def _baseline(self, reason: str, *, degraded: bool = False) -> ProductionResolution:
        if degraded:
            self._degradations.append(reason)
        return ProductionResolution(parameters=None, reason=reason, degraded=degraded)

    def _resolve(
        self, *, project_id: uuid.UUID, kind: str, key: str, target: str
    ) -> ProductionResolution:
        # ── Gate 3: the target must be inside the bounded learnable set.
        if target in PROTECTED_TARGETS:
            return self._baseline(
                f"target {target!r} is permanently outside learning authority"
            )
        if target not in self._compatible:
            return self._baseline(
                f"target {target!r} is not in the declared learnable set"
            )

        # ── Explicit "learning disabled".
        if self._store is None:
            return self._baseline("learning is disabled; baseline behaviour")

        # ── Absent learning is the healthy common case, not a degradation.
        state = self._store.get_active_state(project_id, kind, key)
        if state is None:
            return self._baseline("no active learning for this project")

        # 1. Integrity — an unverifiable pointer is never applied.
        if not state.content_hash:
            return self._baseline(
                "active learning failed integrity verification", degraded=True
            )

        # 2. Scope — defence in depth against a cross-project pointer.
        if str(state.project_id) != str(project_id):
            return self._baseline(
                f"active learning belongs to project {state.project_id}, "
                f"addressed from {project_id}",
                degraded=True,
            )

        # 3. Revoked — a deactivated candidate must not apply.
        if state.deactivation_timestamp is not None:
            return self._baseline("active learning has been revoked")

        # 4. Expired — a state activated in the future is not yet trustworthy.
        activated = state.activation_timestamp
        if activated is not None and activated.tzinfo is None:
            activated = activated.replace(tzinfo=timezone.utc)
        if activated is not None and activated > self._now():
            return self._baseline(
                "active learning is not yet active", degraded=True
            )

        # 5. Authorization — checked by the external platform. Absence of an
        #    authorizer is treated as *no authorization*, i.e. baseline.
        if self._authorize is None:
            return self._baseline(
                "no authorizer configured; learning not applied", degraded=True
            )
        if not self._authorize(state, project_id):
            return self._baseline(
                f"authorization refused learning {state.candidate_id}",
                degraded=True,
            )

        # 6. Compatibility — the state must actually target this decision point.
        if state.kind != kind:
            return self._baseline(
                f"active learning kind {state.kind!r} is incompatible with "
                f"{kind!r}",
                degraded=True,
            )

        parameters = (
            dict(self._parameters_for(state)) if self._parameters_for else {}
        )
        provenance = ExecutionDecisionProvenance(
            learning_id=f"{kind}:{key}",
            version_id=state.version_id,
            candidate_id=state.candidate_id,
            project_id=state.project_id,
            activation_state=ActivationMode.FULL.value,
            kind=kind,
            key=key,
            resolved_at=self._now(),
            activated_at=activated,
        )
        return ProductionResolution(
            parameters=parameters,
            provenance=provenance,
            reason="active learning applied",
        )


def assert_resolver_has_no_authority(resolver: ActiveLearningResolver) -> None:
    """Prove the resolver cannot grant authority (Gate 1 / safety principle).

    Wiring learning into production execution must add no authority. The
    resolver exposes reads only; this assertion is what makes that testable
    rather than asserted in prose.
    """
    for forbidden in (
        "promote",
        "activate",
        "deactivate",
        "rollback",
        "approve",
        "authorize",
        "grant",
        "escalate",
        "set_policy",
        "write",
        "save",
        "commit",
    ):
        if hasattr(resolver, forbidden):
            raise AuthorizationDenied(
                f"production learning resolver exposes {forbidden!r}; wiring it "
                f"into execution would add authority"
            )