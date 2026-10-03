"""Learning activation and shadow evaluation — Phase 19B-3 (Gates 14, 15).

Gate 14 insists that ``PROMOTED`` and ``ACTIVE`` are different states. A
candidate may be promoted and still be ``INACTIVE`` during a staged rollout,
which is what makes a canary possible at all: the human approved the change,
and a separate, explicit, *reversible* decision decides how much traffic it
sees.

Gate 15's shadow mode is the safety valve that lets learning gather evidence
before it is trusted. The invariant that makes shadow safe is structural:
``ActivationRecord.affects_behaviour`` is ``False`` for a shadow record, and the
model validator refuses to construct a shadow record carrying any real traffic.
There is no configuration in which a "shadow" candidate changes an outcome.

Every transition here is recorded as an immutable ``ActivationRecord``, so
"why is this candidate live at 10%?" is always answerable.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Optional

from autoforge_learning.models import (
    ActivationMode,
    ActivationRecord,
    ActivationState,
)

logger = logging.getLogger("autoforge.learning.activation")

__test__ = False  # declares a service, not tests


class ActivationError(RuntimeError):
    """An activation transition was refused."""


#: States in which a candidate is actually receiving real traffic.
_LIVE_STATES = frozenset(
    {ActivationState.CANARY, ActivationState.LIMITED, ActivationState.FULL}
)
class ActivationError(RuntimeError):
    """An activation transition was refused."""


#: The staged rollout order. A candidate may only move forward through this
#: sequence, and only to a strictly greater traffic fraction.
ROLLOUT_ORDER: tuple[ActivationMode, ...] = (
    ActivationMode.SHADOW,
    ActivationMode.CANARY,
    ActivationMode.LIMITED,
    ActivationMode.FULL,
)

#: Traffic fraction each stage corresponds to. Shadow is fixed at 0.0 by the
#: model validator, so it is documentation rather than configuration.
TRAFFIC_BY_MODE: dict[ActivationMode, float] = {
    ActivationMode.SHADOW: 0.0,
    ActivationMode.CANARY: 0.05,
    ActivationMode.LIMITED: 0.25,
    ActivationMode.FULL: 1.0,
}


@dataclass
class ShadowComparison:
    """What the shadow candidate *would* have done, versus what happened.

    The authoritative result is always ``baseline``. ``shadow`` is recorded for
    evidence only and is never substituted for it, which is the whole point of
    19A §4's SHADOW step.
    """

    execution_id: uuid.UUID
    baseline_outcome: str
    shadow_outcome: str
    agreed: bool
    baseline_evidence_hash: str = ""
    shadow_evidence_hash: str = ""

    @property
    def authoritative_source(self) -> str:
        return "baseline"


@dataclass
class ActivationTransition:
    """The result of one activation-state change."""

    record: ActivationRecord
    previous_state: Optional[ActivationState]
    reason: str


class ActivationService:
    """Controls how much traffic a promoted candidate receives."""

    def __init__(self) -> None:
        self._records: list[ActivationRecord] = []

    @property
    def history(self) -> tuple[ActivationRecord, ...]:
        return tuple(self._records)

    def activate(
        self,
        *,
        candidate_id: uuid.UUID,
        project_id: uuid.UUID,
        kind: str,
        key: str,
        mode: ActivationMode,
        version_id: Optional[uuid.UUID] = None,
        rollback_handle_id: Optional[uuid.UUID] = None,
        activated_by: str = "autoforge.learning.activation",
        correlation_id: Optional[str] = None,
    ) -> ActivationTransition:
        """Move a candidate into the given rollout stage.

        Progress is monotonic in traffic: a candidate may be promoted from
        shadow to canary, but demoting live traffic back to shadow silently
        would change behaviour under running executions. Deactivation is the
        supported way to stop affecting behaviour.
        """
        current = self.current(
            candidate_id=candidate_id, project_id=project_id, kind=kind, key=key
        )
        if current is not None and current.state in _LIVE_STATES:
            if ROLLOUT_ORDER.index(mode) < ROLLOUT_ORDER.index(_mode_of(current.state)):
                raise ActivationError(
                    f"cannot move a {current.state.value} activation back to "
                    f"{mode.value}; use deactivate() to stop affecting behaviour"
                )

        state = _state_for(mode)
        record = ActivationRecord(
            candidate_id=candidate_id,
            project_id=project_id,
            kind=kind,
            key=key,
            state=state,
            mode=mode,
            traffic_fraction=TRAFFIC_BY_MODE[mode],
            version_id=version_id,
            rollback_handle_id=rollback_handle_id,
            activated_by=activated_by,
            correlation_id=correlation_id,
        )
        self._records.append(record)
        return ActivationTransition(
            record=record,
            previous_state=current.state if current else None,
            reason=f"activated in {mode.value} mode",
        )

    def deactivate(
        self,
        *,
        candidate_id: uuid.UUID,
        project_id: uuid.UUID,
        kind: str,
        key: str,
        reason: str,
        correlation_id: Optional[str] = None,
    ) -> ActivationTransition:
        """Stop a candidate affecting behaviour, keeping the history intact."""
        current = self.current(
            candidate_id=candidate_id, project_id=project_id, kind=kind, key=key
        )
        record = ActivationRecord(
            candidate_id=candidate_id,
            project_id=project_id,
            kind=kind,
            key=key,
            state=ActivationState.DEACTIVATED,
            mode=ActivationMode.SHADOW,
            traffic_fraction=0.0,
            version_id=current.version_id if current else None,
            rollback_handle_id=current.rollback_handle_id if current else None,
            deactivated_at=datetime.now(timezone.utc),
            correlation_id=correlation_id,
        )
        self._records.append(record)
        return ActivationTransition(
            record=record,
            previous_state=current.state if current else None,
            reason=reason,
        )

    def current(
        self,
        *,
        candidate_id: uuid.UUID,
        project_id: uuid.UUID,
        kind: str,
        key: str,
    ) -> Optional[ActivationRecord]:
        """The latest activation record for one (candidate, kind, key)."""
        matches = [
            r
            for r in self._records
            if r.candidate_id == candidate_id
            and r.project_id == project_id
            and r.kind == kind
            and r.key == key
        ]
        return matches[-1] if matches else None

    def shadow_compare(
        self,
        *,
        execution_id: uuid.UUID,
        baseline_outcome: str,
        shadow_runner: Callable[[], str],
        baseline_evidence_hash: str = "",
        shadow_evidence_hash: str = "",
    ) -> ShadowComparison:
        """Run the candidate alongside the baseline and record the comparison.

        ``shadow_runner`` is invoked for observation only. Its result is
        recorded and never returned as authoritative — the baseline outcome is
        what the caller must keep using.
        """
        try:
            shadow_outcome = shadow_runner()
        except Exception as exc:  # noqa: BLE001 - a shadow failure is not a failure
            logger.warning("shadow execution failed: %s", exc)
            shadow_outcome = f"shadow_error:{type(exc).__name__}"

        return ShadowComparison(
            execution_id=execution_id,
            baseline_outcome=baseline_outcome,
            shadow_outcome=shadow_outcome,
            agreed=shadow_outcome == baseline_outcome,
            baseline_evidence_hash=baseline_evidence_hash,
            shadow_evidence_hash=shadow_evidence_hash,
        )


def _state_for(mode: ActivationMode) -> ActivationState:
    return {
        ActivationMode.SHADOW: ActivationState.SHADOW,
        ActivationMode.CANARY: ActivationState.CANARY,
        ActivationMode.LIMITED: ActivationState.LIMITED,
        ActivationMode.FULL: ActivationState.FULL,
    }[mode]


def _mode_of(state: ActivationState) -> ActivationMode:
    for mode in ROLLOUT_ORDER:
        if _state_for(mode) is state:
            return mode
    return ActivationMode.SHADOW


__all__ = [
    "ROLLOUT_ORDER",
    "TRAFFIC_BY_MODE",
    "ActivationError",
    "ActivationService",
    "ActivationTransition",
    "ShadowComparison",
]