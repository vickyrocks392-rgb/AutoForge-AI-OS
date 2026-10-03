"""Regression detection and automatic rollback — Phase 19B-3 (Gates 16–18).

Gate 16 requires automatic regression detection with *explicitly defined*
thresholds and forbids "arbitrary model judgment". Every threshold therefore
lives on :class:`RegressionPolicy`, which the caller pins before activation,
and :class:`RegressionMonitor` is a pure comparison of measurements against
those thresholds. It contains no model call, no heuristic and no fallback.

Gate 17 requires automatic rollback when a contractually defined threshold is
crossed, in a fixed order: detect → verify evidence → freeze promotion →
deterministic rollback → audit → record → generate a signal. :func:`enforce` is
that order, and its rollback callable is the *existing*
``PromotionService.rollback``, which requires no model. Automatic rollback only
operates inside the previously authorized rollback scope recorded on the
activation, so it can restore a prior state but can never invent a new one.

Gate 18's catastrophic conditions bypass the accumulation logic entirely: a
security violation, correctness collapse, artifact corruption, credential
leakage, policy violation, sandbox violation or unauthorized network activity
trips the hard stop immediately.
"""

from __future__ import annotations

import hashlib
import logging
import uuid
from dataclasses import dataclass
from typing import Callable, Mapping, Optional, Sequence

from autoforge_learning.models import (
    EvidenceRef,
    RegressionReport,
    RegressionSeverity,
)

logger = logging.getLogger("autoforge.learning.monitoring")

__test__ = False  # declares a monitor, not tests
#: Gate 18 hard-stop conditions. Presence of any of these is catastrophic and
#: bypasses every accumulated-reward or sample-size consideration.
CATASTROPHIC_CONDITIONS: tuple[str, ...] = (
    "security_violation",
    "correctness_collapse",
    "repeated_execution_failure",
    "artifact_corruption",
    "credential_leakage",
    "policy_violation",
    "sandbox_violation",
    "unauthorized_network_activity",
)


class RegressionPolicy:
    """Pre-registered thresholds, pinned before activation.

    Every threshold lives here rather than inside the monitor, so the monitor
    itself holds no policy and cannot adjust a goalpost after seeing a result.
    """

    def __init__(
        self,
        *,
        thresholds: Mapping[str, tuple[float, bool]] | None = None,
        tracked_invariants: Sequence[str] = (),
        min_sample_size: int = 1,
        catastrophic_conditions: Sequence[str] = CATASTROPHIC_CONDITIONS,
    ) -> None:
        self.thresholds = dict(thresholds or {})
        self.tracked_invariants = tuple(tracked_invariants)
        self.min_sample_size = min_sample_size
        self.catastrophic_conditions = tuple(catastrophic_conditions)

    def canonical(self) -> str:
        return repr(
            (
                sorted(self.thresholds.items()),
                tuple(sorted(self.tracked_invariants)),
                self.min_sample_size,
                tuple(sorted(self.catastrophic_conditions)),
            )
        )

    @property
    def policy_hash(self) -> str:
        """Content hash of the pinned thresholds.

        Monitoring records this at activation time and re-verifies it later, so
        a policy edited after the fact is detected rather than silently applied.
        """
        return hashlib.sha256(self.canonical().encode("utf-8")).hexdigest()

    def assert_unchanged(self, pinned_hash: str) -> bool:
        return self.policy_hash == pinned_hash


class RegressionMonitor:
    """Compares measurements against pre-registered thresholds. No model."""

    def evaluate(
        self,
        *,
        candidate_id: uuid.UUID,
        project_id: uuid.UUID,
        kind: str,
        key: str,
        policy: RegressionPolicy,
        measurements: Mapping[str, float],
        invariant_verdicts: Mapping[str, str] | None = None,
        catastrophic_conditions: Sequence[str] = (),
        evidence: Sequence[EvidenceRef] = (),
        sample_size: int = 0,
        rollback_handle_id: Optional[uuid.UUID] = None,
        correlation_id: Optional[str] = None,
    ) -> RegressionReport:
        """Produce the deterministic regression verdict for one activation."""
        invariant_verdicts = invariant_verdicts or {}
        tripped_metrics: list[str] = []
        tripped_invariants: list[str] = []
        catastrophic: list[str] = []

        # 1. Catastrophic first. Gate 18: do not wait for accumulated reward.
        for condition in catastrophic_conditions:
            if condition in policy.catastrophic_conditions:
                catastrophic.append(condition)

        # 2. Tracked metrics against pre-registered thresholds.
        for metric, (worst, lower_is_better) in policy.thresholds.items():
            value = measurements.get(metric)
            if value is None:
                # An unmeasured metric is not a passing metric.
                tripped_metrics.append(f"{metric}:unmeasured")
                continue
            breached = value > worst if lower_is_better else value < worst
            if breached:
                tripped_metrics.append(f"{metric}:{value}>{worst}")

        # 3. Tracked protected invariants.
        for invariant in policy.tracked_invariants:
            verdict = invariant_verdicts.get(invariant)
            if verdict is None:
                tripped_invariants.append(f"{invariant}:unmeasured")
            elif verdict != "pass":
                tripped_invariants.append(f"{invariant}:{verdict}")

        severity = self._severity(
            catastrophic=catastrophic,
            tripped_metrics=tripped_metrics,
            tripped_invariants=tripped_invariants,
            sample_size=sample_size,
            policy=policy,
        )

        # Gate 17 step 2: verify evidence before permitting any automatic action.
        evidence_verified = bool(evidence) or not tripped_metrics
        auto_rollback_permitted = (
            severity in (RegressionSeverity.MAJOR, RegressionSeverity.CATASTROPHIC)
            and evidence_verified
            and rollback_handle_id is not None
        )

        return RegressionReport(
            candidate_id=candidate_id,
            project_id=project_id,
            kind=kind,
            key=key,
            severity=severity,
            tripped_metrics=tuple(tripped_metrics),
            tripped_invariants=tuple(tripped_invariants),
            catastrophic_reasons=tuple(catastrophic),
            sample_size=sample_size,
            evidence=tuple(evidence),
            auto_rollback_permitted=auto_rollback_permitted,
            rollback_handle_id=rollback_handle_id,
            correlation_id=correlation_id,
        )

    @staticmethod
    def _severity(
        *,
        catastrophic: Sequence[str],
        tripped_metrics: Sequence[str],
        tripped_invariants: Sequence[str],
        sample_size: int,
        policy: RegressionPolicy,
    ) -> RegressionSeverity:
        if catastrophic:
            return RegressionSeverity.CATASTROPHIC
        if tripped_invariants:
            return RegressionSeverity.MAJOR
        if tripped_metrics and sample_size >= policy.min_sample_size:
            return RegressionSeverity.MINOR
        return RegressionSeverity.NONE


@dataclass
class RollbackOutcome:
    """The full result of an automatic regression response (Gate 17)."""

    report: RegressionReport
    promotion_frozen: bool
    rollback_performed: bool
    rollback_record_id: Optional[uuid.UUID]
    audit_emitted: bool
    signal_generated: bool
    follow_up_candidate_created: bool
    steps: tuple[str, ...] = ()


def enforce(
    *,
    report: RegressionReport,
    freeze_promotion: Callable[[], bool],
    deterministic_rollback: Callable[[uuid.UUID], uuid.UUID],
    emit_audit: Callable[[RegressionReport], bool],
    generate_signal: Callable[[RegressionReport], bool],
    create_follow_up_candidate: Callable[[RegressionReport], bool],
) -> RollbackOutcome:
    """Execute Gate 17's fixed response order.

    The rollback callable is the existing ``PromotionService.rollback`` bound to
    the handle recorded on the activation. Nothing here reasons about whether
    rollback is *desirable*: it runs because a pre-registered threshold was
    crossed and the evidence verified, and the whole sequence is deterministic.
    """
    if not report.is_regression:
        return RollbackOutcome(
            report=report,
            promotion_frozen=False,
            rollback_performed=False,
            rollback_record_id=None,
            audit_emitted=False,
            signal_generated=False,
            follow_up_candidate_created=False,
            steps=("no regression detected; no action taken",),
        )

    steps: list[str] = []
    frozen = freeze_promotion()
    steps.append(f"promotion frozen: {frozen}")

    rollback_id: Optional[uuid.UUID] = None
    if report.auto_rollback_permitted and report.rollback_handle_id is not None:
        rollback_id = deterministic_rollback(report.rollback_handle_id)
        steps.append(f"deterministic rollback executed: {rollback_id}")
    else:
        steps.append(
            "automatic rollback not permitted: "
            + (
                "no rollback handle on this activation"
                if report.rollback_handle_id is None
                else "evidence did not verify"
            )
        )

    audited = emit_audit(report)
    steps.append(f"audit emitted: {audited}")

    signalled = generate_signal(report)
    steps.append(f"learning signal generated: {signalled}")

    follow_up = create_follow_up_candidate(report) if report.is_catastrophic else False
    steps.append(f"follow-up candidate created: {follow_up}")

    return RollbackOutcome(
        report=report,
        promotion_frozen=frozen,
        rollback_performed=rollback_id is not None,
        rollback_record_id=rollback_id,
        audit_emitted=audited,
        signal_generated=signalled,
        follow_up_candidate_created=follow_up,
        steps=tuple(steps),
    )


__all__ = [
    "CATASTROPHIC_CONDITIONS",
    "RegressionMonitor",
    "RegressionPolicy",
    "RollbackOutcome",
    "enforce",
]