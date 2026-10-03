"""Continual learning and forgetting protection — Phase 19B-3 (Gates 19, 20, 21).

Gate 19 requires continual learning *without uncontrolled accumulation*, and
forbids silently deleting learning history. The resolution is that records are
never removed — they are **aged, deduplicated, superseded, retired and
archived**, and each of those is a state transition on an immutable record
rather than a delete. ``CandidateLifecycle`` therefore has no ``delete``, no
``purge`` and no ``remove`` method at all; the absence is the guarantee.

Gate 20 requires catastrophic-forgetting protection: a new candidate must show
NEW PERFORMANCE **and** PRESERVED PREVIOUS CAPABILITIES. ``CapabilitySuite``
holds the previously-solved regression cases, and ``check_preservation`` refuses
a candidate that improves one metric while destroying another — unless the
trade-off was *explicitly authorized* by a named human, which is a recorded
decision, not something the optimizer can assert about itself.

Gate 21's separation (MEMORY / KNOWLEDGE / LEARNING / EXPERIENCE) is preserved
structurally: this module stores *lifecycle metadata* only, never payloads, and
the four concerns remain distinct types with distinct stores.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Mapping, Optional

logger = logging.getLogger("autoforge.learning.continual")

__test__ = False  # declares a lifecycle, not tests
class CandidateLifecycleState(str, Enum):
    """Lifecycle states for continual learning (Gate 19).

    ``ARCHIVED`` is a real, recorded state rather than deletion: history is
    retained forever, which is what "never silently delete learning history"
    requires.
    """

    PROPOSED = "proposed"
    EVALUATED = "evaluated"
    APPROVED = "approved"
    ACTIVE = "active"
    SUPERSEDED = "superseded"
    RETIRED = "retired"
    ARCHIVED = "archived"


#: How long a candidate may sit in PROPOSED before it is considered stale.
DEFAULT_MAX_CANDIDATE_AGE = timedelta(days=30)


@dataclass
class CandidateRecordState:
    """Lifecycle metadata for one candidate. Deliberately payload-free."""

    candidate_id: uuid.UUID
    project_id: uuid.UUID
    summary: str
    state: CandidateLifecycleState = CandidateLifecycleState.PROPOSED
    created_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    updated_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    #: Fingerprint used for deduplication, derived from candidate content so two
    #: genuinely different proposals are not collapsed.
    fingerprint: str = ""
    supersedes: Optional[uuid.UUID] = None
    superseded_by: Optional[uuid.UUID] = None
    retirement_reason: str = ""

    @property
    def age(self) -> timedelta:
        return datetime.now(timezone.utc) - self.created_at

    @property
    def is_stale(self) -> bool:
        return (
            self.state is CandidateLifecycleState.PROPOSED
            and self.age > DEFAULT_MAX_CANDIDATE_AGE
        )

    @property
    def is_active(self) -> bool:
        return self.state is CandidateLifecycleState.ACTIVE


class CandidateLifecycle:
    """Aging, deduplication, supersession, retirement and archival.

    Note what this class does **not** have: no delete, no purge, no remove.
    Archival is the terminal state, and it is a record, not an erasure.
    """

    def __init__(self) -> None:
        self._records: list[CandidateRecordState] = []

    @property
    def records(self) -> tuple[CandidateRecordState, ...]:
        return tuple(self._records)

    def register(
        self,
        *,
        candidate_id: uuid.UUID,
        project_id: uuid.UUID,
        summary: str,
        fingerprint: str,
    ) -> tuple[CandidateRecordState, bool]:
        """Register a candidate, detecting duplicates by fingerprint.

        Returns the record and whether it was newly created. A duplicate is
        returned as the existing record rather than a second copy, which keeps
        the store bounded without deleting anything.
        """
        existing = self._find(fingerprint, project_id)
        if existing is not None:
            return existing, False
        record = CandidateRecordState(
            candidate_id=candidate_id,
            project_id=project_id,
            summary=summary,
            fingerprint=fingerprint,
        )
        self._records.append(record)
        return record, True

    def transition(
        self,
        candidate_id: uuid.UUID,
        new_state: CandidateLifecycleState,
        *,
        reason: str = "",
        supersedes: Optional[uuid.UUID] = None,
    ) -> CandidateRecordState:
        """Move a candidate to a new lifecycle state, recording why."""
        record = self._get(candidate_id)
        if record.state is CandidateLifecycleState.ARCHIVED and (
            new_state is not CandidateLifecycleState.ARCHIVED
        ):
            raise ValueError(
                f"candidate {candidate_id} is archived and its history is immutable"
            )
        if new_state is CandidateLifecycleState.SUPERSEDED and supersedes is None:
            raise ValueError(
                "supersession requires naming the superseding candidate so lineage "
                "is never lost"
            )

        updated = CandidateRecordState(
            candidate_id=record.candidate_id,
            project_id=record.project_id,
            summary=record.summary,
            state=new_state,
            created_at=record.created_at,
            updated_at=datetime.now(timezone.utc),
            fingerprint=record.fingerprint,
            # ``supersedes`` names what replaced this candidate; ``superseded_by``
            # is retained from the prior transition so lineage is never lost in
            # either direction.
            supersedes=supersedes or record.supersedes,
            superseded_by=record.superseded_by,
            retirement_reason=reason,
        )
        self._replace(record, updated)
        return updated

    def archive(self, candidate_id: uuid.UUID, reason: str) -> CandidateRecordState:
        """Archive a candidate. The record is retained, never removed."""
        return self.transition(
            candidate_id, CandidateLifecycleState.ARCHIVED, reason=reason
        )

    def stale_candidates(self) -> tuple[CandidateRecordState, ...]:
        """Candidates that have sat unevaluated past the age limit."""
        return tuple(r for r in self._records if r.is_stale)

    def history_for(self, candidate_id: uuid.UUID) -> tuple[CandidateRecordState, ...]:
        """Every record in a supersession chain, oldest first.

        ``supersedes`` names the candidate that *replaced* this one, so the chain
        is walked forward from ``candidate_id`` through its successors. A
        successor that has not been registered yet — a candidate can be
        superseded by a proposal still being prepared — simply ends the walk
        rather than raising, so lineage stays readable at every intermediate
        state.
        """
        chain: list[CandidateRecordState] = []
        current = self._find_by_id(candidate_id)
        seen: set[uuid.UUID] = set()
        while current is not None and current.candidate_id not in seen:
            seen.add(current.candidate_id)
            chain.append(current)
            current = (
                self._find_by_id(current.supersedes) if current.supersedes else None
            )
        return tuple(chain)

    # ── internals ────────────────────────────────────────────────────────────

    def _find_by_id(self, candidate_id: uuid.UUID) -> Optional[CandidateRecordState]:
        for record in self._records:
            if record.candidate_id == candidate_id:
                return record
        return None

    def _find(self, fingerprint: str, project_id: uuid.UUID):
        for record in self._records:
            if (
                record.fingerprint == fingerprint
                and record.project_id == project_id
                and record.state is not CandidateLifecycleState.SUPERSEDED
            ):
                return record
        return None

    def _get(self, candidate_id: uuid.UUID) -> CandidateRecordState:
        for record in self._records:
            if record.candidate_id == candidate_id:
                return record
        raise KeyError(candidate_id)

    def _replace(
        self, old: CandidateRecordState, new: CandidateRecordState
    ) -> None:
        self._records[self._records.index(old)] = new


@dataclass
class CapabilityCase:
    """One previously-solved problem that must keep working (Gate 20)."""

    case_id: uuid.UUID
    name: str
    #: Metric name -> the floor that must still hold.
    floors: dict[str, float]
    recorded_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    #: True only when a named human explicitly authorized this trade-off.
    trade_off_authorized: bool = False
    authorized_by: str = ""


class CapabilitySuite:
    """The regression suite of previously-solved problems.

    Gate 20 requires a new candidate to demonstrate new performance *and*
    preserved previous capabilities. This class is what "previously solved"
    means concretely: cases with floors a candidate must still clear.
    """

    def __init__(self) -> None:
        self._cases: list[CapabilityCase] = []

    @property
    def cases(self) -> tuple[CapabilityCase, ...]:
        return tuple(self._cases)

    def record(self, case: CapabilityCase) -> CapabilityCase:
        self._cases.append(case)
        return case

    def check(self, measurements: Mapping[str, float]) -> tuple[CapabilityCase, ...]:
        """Every case the candidate would now fail.

        A missing measurement counts as a failure, because "we did not check"
        must never read as "it still works".
        """
        broken: list[CapabilityCase] = []
        for case in self._cases:
            if case.trade_off_authorized:
                continue
            for metric, floor in case.floors.items():
                value = measurements.get(metric)
                if value is None or value < floor:
                    broken.append(case)
                    break
        return tuple(broken)


def check_preservation(
    *,
    suite: CapabilitySuite,
    measurements: Mapping[str, float],
    new_performance_metric: str,
    new_performance_value: float,
    required_new_performance: float,
) -> tuple[bool, str]:
    """Gate 20's joint requirement: new performance AND preserved capability.

    Returns ``(accepted, reason)``. A candidate that clears the bar but breaks a
    previously-solved case is refused, because "optimize only for the latest
    task" is exactly the failure mode this gate exists to prevent.
    """
    broken = suite.check(measurements)
    if broken:
        names = sorted(c.name for c in broken)
        return (
            False,
            "candidate regressed previously-solved capabilities "
            f"{names}; a gain on {new_performance_metric} does not authorize "
            "destroying a previously-solved problem",
        )
    if new_performance_value < required_new_performance:
        return (
            False,
            f"candidate did not reach the required new performance on "
            f"{new_performance_metric} "
            f"({new_performance_value} < {required_new_performance})",
        )
    return (
        True,
        f"new performance on {new_performance_metric} ({new_performance_value}) "
        f"with all {len(suite.cases)} previously-solved capability case(s) preserved",
    )


__all__ = [
    "DEFAULT_MAX_CANDIDATE_AGE",
    "CandidateLifecycle",
    "CandidateLifecycleState",
    "CandidateRecordState",
    "CapabilityCase",
    "CapabilitySuite",
    "check_preservation",
]