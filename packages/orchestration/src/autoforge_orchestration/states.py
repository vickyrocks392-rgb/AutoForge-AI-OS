"""Deterministic StageStatus state machine (Phase 18).

Pure table lookup — no AI, no judgment, explicit violations.
"""

from __future__ import annotations

from autoforge_orchestration.errors import StageStateError
from autoforge_orchestration.models import StageStatus

# ── Deterministic Transition Table ──────────────────────────────────────────

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
    return _STAGE_TRANSITIONS.get(current, frozenset())


def is_stage_terminal(status: StageStatus) -> bool:
    return status in _TERMINAL_STATES


def is_stage_successful_terminal(status: StageStatus) -> bool:
    return status == StageStatus.SUCCEEDED


def is_stage_failed_terminal(status: StageStatus, attempt: int, max_attempts: int) -> bool:
    """A stage is terminally failed when FAILED AND the retry budget is spent."""
    return status == StageStatus.FAILED and attempt >= max_attempts


def transition_stage(
    stage_id: str,
    current: StageStatus,
    target: StageStatus,
) -> StageStatus:
    """Apply a validated transition; returns the new status."""
    validate_stage_transition(current, target, stage_id=stage_id)
    return target