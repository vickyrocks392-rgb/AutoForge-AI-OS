"""Truthful learning telemetry — Phase 19B-2 (Gate 16).

Every counter here is **derived from stored records and emitted audit
events**. Nothing is a constant, and nothing reports a healthy-looking
number that no record supports.

An empty store therefore reports zeros, and a run that evaluated three
candidates and promoted one reports ``3`` and ``1`` — not "100%".
"""

from __future__ import annotations

import uuid
from typing import Optional

from autoforge_learning.audit import LearningAuditAction, LearningAuditor
from autoforge_learning.evaluation import EvaluationOutcome
from autoforge_learning.models import LearningBase
from autoforge_learning.store import ApprovalStatus, DurableLearningStore, PromotionState

__test__ = False  # declares a data model, not tests


class LearningTelemetry(LearningBase):
    """Counts derived from real records. Never fabricated."""

    project_id: Optional[uuid.UUID] = None
    candidates_created: int = 0
    candidates_evaluated: int = 0
    candidates_failed_evaluation: int = 0
    approvals_requested: int = 0
    approvals_granted: int = 0
    approvals_rejected: int = 0
    promotions_attempted: int = 0
    promotions_succeeded: int = 0
    promotions_failed: int = 0
    rollbacks_attempted: int = 0
    rollbacks_succeeded: int = 0
    rollbacks_failed: int = 0
    data_available: bool = False

    @property
    def pass_rate(self) -> Optional[float]:
        """Fraction of evaluations that passed, or ``None`` when none ran.

        ``None`` rather than ``1.0`` or ``0.0``: with no evaluations there is
        no pass rate, and reporting either extreme would be a lie.
        """
        if self.candidates_evaluated == 0:
            return None
        passed = self.candidates_evaluated - self.candidates_failed_evaluation
        return passed / self.candidates_evaluated

    @property
    def is_all_passing(self) -> bool:
        """True only when every recorded evaluation passed.

        An empty run is NOT "all passing" — that is exactly the fabricated
        ``ALL_PASSING`` state Gate 19A found and removed.
        """
        return (
            self.candidates_evaluated > 0
            and self.candidates_failed_evaluation == 0
        )


class TelemetryCollector:
    """Builds :class:`LearningTelemetry` from the store and the audit trail."""

    def __init__(
        self,
        *,
        store: DurableLearningStore,
        auditor: LearningAuditor,
    ) -> None:
        self._store = store
        self._auditor = auditor

    def collect(self, project_id: uuid.UUID) -> LearningTelemetry:
        evaluations = self._store.list_evaluations(project_id)
        approvals = self._store.list_approvals(project_id)
        promotions = self._store.list_promotions(project_id)
        rollbacks = self._store.list_rollbacks(project_id)
        candidates = self._store.list_candidates(project_id)
        events = self._auditor.events

        def emitted(action: LearningAuditAction) -> int:
            return sum(
                1
                for e in events
                if e.action is action and e.project_id == project_id
            )

        return LearningTelemetry(
            project_id=project_id,
            candidates_created=len(candidates),
            candidates_evaluated=len(evaluations),
            candidates_failed_evaluation=sum(
                1 for e in evaluations if e.outcome is not EvaluationOutcome.PASSED
            ),
            approvals_requested=len(approvals),
            approvals_granted=sum(1 for a in approvals if a.status is ApprovalStatus.APPROVED),
            approvals_rejected=sum(
                1
                for a in approvals
                if a.status
                in (ApprovalStatus.REJECTED, ApprovalStatus.EXPIRED, ApprovalStatus.REVOKED)
            ),
            promotions_attempted=len(promotions),
            promotions_succeeded=sum(
                1 for p in promotions if p.state is PromotionState.PROMOTED
            ),
            promotions_failed=sum(1 for p in promotions if p.state is PromotionState.FAILED),
            rollbacks_attempted=emitted(LearningAuditAction.ROLLBACK_ATTEMPTED),
            rollbacks_succeeded=len(rollbacks),
            rollbacks_failed=emitted(LearningAuditAction.ROLLBACK_FAILED),
            data_available=bool(candidates or evaluations or approvals or promotions),
        )


__all__ = ["LearningTelemetry", "TelemetryCollector"]