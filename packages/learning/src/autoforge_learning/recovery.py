"""Crash and partial-state recovery — Phase 19B-3 (Gate 33).

Gate 33 asks that recovery after a crash, restart, partial experiment, partial
promotion, partial rollback, evaluator crash, store corruption or experiment
timeout preserve lineage, audit, active state, rollback state and candidate
state — and that learning history is never silently lost.

The existing 19B-2 store already provides crash-safety: every record is fsync-ed
and atomically published, so a reader sees either the whole previous state or
the whole new one. What this module adds is *reconciliation*: classifying what a
restart actually left behind and deciding, per category, what is safe to resume.

The classification is deliberately conservative. ``PARTIAL_PROMOTION`` and
``PARTIAL_ROLLBACK`` are where guessing is most dangerous, so they are reported
as ``requires_human_review`` rather than auto-repaired: finishing a half-applied
promotion would grant the very authority the promotion was still awaiting
approval for.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Sequence

logger = logging.getLogger("autoforge.learning.recovery")

__test__ = False  # declares a reconciler, not tests


class RecoveryState(str, Enum):
    """What a restart found behind it."""

    CLEAN = "clean"
    #: An experiment was mid-flight; its result is unknown and must not be guessed.
    PARTIAL_EXPERIMENT = "partial_experiment"
    #: A promotion committed its active state but not its follow-up records.
    PARTIAL_PROMOTION = "partial_promotion"
    #: A rollback wrote some records but not the active-state restore.
    PARTIAL_ROLLBACK = "partial_rollback"
    #: A record failed its integrity check.
    CORRUPT_STORE = "corrupt_store"
    #: Work exceeded its budget and was terminated.
    TIMED_OUT = "timed_out"
class RecoveryAction(str, Enum):
    NOTHING_TO_DO = "nothing_to_do"
    #: Safe to continue: nothing was committed.
    DISCARD_INCOMPLETE = "discard_incomplete"
    #: Requires a named human; never performed automatically.
    REQUIRES_HUMAN_REVIEW = "requires_human_review"


@dataclass
class RecoveryFinding:
    """One piece of unreconciled state found after a restart."""

    state: RecoveryState
    subject_id: uuid.UUID
    detail: str
    action: RecoveryAction

    @property
    def is_automatically_recoverable(self) -> bool:
        return self.action is not RecoveryAction.REQUIRES_HUMAN_REVIEW


@dataclass
class RecoveryReport:
    """The full outcome of one reconciliation pass."""

    project_id: uuid.UUID
    findings: tuple[RecoveryFinding, ...] = ()
    #: IDs of records that must be preserved untouched.
    preserved_lineage_ids: tuple[uuid.UUID, ...] = ()
    preserved_candidate_ids: tuple[uuid.UUID, ...] = ()
    preserved_rollback_handle_ids: tuple[uuid.UUID, ...] = ()
    performed_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    @property
    def requires_human_review(self) -> bool:
        return any(
            f.action is RecoveryAction.REQUIRES_HUMAN_REVIEW for f in self.findings
        )

    @property
    def is_clean(self) -> bool:
        return not self.findings


class RecoveryReconciler:
    """Classifies post-restart state. Repairs nothing that grants authority."""

    def reconcile(
        self,
        *,
        project_id: uuid.UUID,
        active_state_present: bool,
        dangling_experiment_ids: Sequence[uuid.UUID] = (),
        promotions_without_audit: Sequence[uuid.UUID] = (),
        rollbacks_without_restore: Sequence[uuid.UUID] = (),
        corrupt_record_ids: Sequence[uuid.UUID] = (),
        timed_out_experiment_ids: Sequence[uuid.UUID] = (),
        lineage_ids: Sequence[uuid.UUID] = (),
        candidate_ids: Sequence[uuid.UUID] = (),
        rollback_handle_ids: Sequence[uuid.UUID] = (),
    ) -> RecoveryReport:
        """Classify everything a restart left behind.

        Every input is a *fact about stored records*, not an opinion, so the
        reconciliation is deterministic and re-runnable.
        """
        findings: list[RecoveryFinding] = []

        for experiment_id in dangling_experiment_ids:
            findings.append(
                RecoveryFinding(
                    state=RecoveryState.PARTIAL_EXPERIMENT,
                    subject_id=experiment_id,
                    detail="experiment has no terminal outcome; its result is unknown",
                    # Discarding an *incomplete* experiment loses no conclusion,
                    # because no conclusion was ever reached.
                    action=RecoveryAction.DISCARD_INCOMPLETE,
                )
            )

        for experiment_id in timed_out_experiment_ids:
            findings.append(
                RecoveryFinding(
                    state=RecoveryState.TIMED_OUT,
                    subject_id=experiment_id,
                    detail="experiment exceeded its declared duration",
                    action=RecoveryAction.DISCARD_INCOMPLETE,
                )
            )

        for promotion_id in promotions_without_audit:
            findings.append(
                RecoveryFinding(
                    state=RecoveryState.PARTIAL_PROMOTION,
                    subject_id=promotion_id,
                    detail="promotion committed without a completed audit record",
                    # Gate 33 forbids losing the promotion, but completing it
                    # automatically would grant the authority its audit was
                    # still verifying.
                    action=RecoveryAction.REQUIRES_HUMAN_REVIEW,
                )
            )

        for rollback_id in rollbacks_without_restore:
            findings.append(
                RecoveryFinding(
                    state=RecoveryState.PARTIAL_ROLLBACK,
                    subject_id=rollback_id,
                    detail="rollback recorded without restoring the active state",
                    action=RecoveryAction.REQUIRES_HUMAN_REVIEW,
                )
            )

        for record_id in corrupt_record_ids:
            findings.append(
                RecoveryFinding(
                    state=RecoveryState.CORRUPT_STORE,
                    subject_id=record_id,
                    detail="record failed integrity verification",
                    # A corrupt record is quarantined, never deleted: Gate 33
                    # forbids silently losing learning history.
                    action=RecoveryAction.REQUIRES_HUMAN_REVIEW,
                )
            )

        if not findings and active_state_present:
            logger.debug("recovery for %s found no unreconciled state", project_id)

        return RecoveryReport(
            project_id=project_id,
            findings=tuple(findings),
            preserved_lineage_ids=tuple(lineage_ids),
            preserved_candidate_ids=tuple(candidate_ids),
            preserved_rollback_handle_ids=tuple(rollback_handle_ids),
        )


__all__ = [
    "RecoveryAction",
    "RecoveryFinding",
    "RecoveryReconciler",
    "RecoveryReport",
    "RecoveryState",
]