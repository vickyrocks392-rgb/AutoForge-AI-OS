"""Hypothesis generation — Phase 19B-3 (Gate 4).

A hypothesis is a *proposal* until evaluated. This module produces several
**competing** hypotheses from the same evidence rather than one "best" guess,
because Gate 4 requires the system not to assume the first generated hypothesis
is correct.

Three properties are enforced structurally rather than by convention:

1. **Evidence-bound.** :class:`Hypothesis` requires at least one ``EvidenceRef``;
   an unsupported hypothesis cannot be constructed at all.
2. **Inert.** Every hypothesis is emitted at ``L1_INSIGHT``, which
   :meth:`Hypothesis.is_inert` reports as ``True``. It names a rollback strategy
   because Gate 4 requires one, but possessing a string is not possessing a
   capability.
3. **Scope-preserving.** Hypotheses inherit the scope of the observations that
   produced them, and the generator refuses to consume evidence from another
   project, so a hypothesis can never be born with a wider scope than its
   evidence.
"""

from __future__ import annotations

import logging
import uuid
from typing import Mapping, Optional, Sequence

from autoforge_learning.models import (
    EvidenceRef,
    Hypothesis,
    LearningAuthority,
    LearningLineage,
    LearningScope,
    LearningSignal,
    SignalClass,
    SignalPolarity,
)

logger = logging.getLogger("autoforge.learning.hypothesis")

__test__ = False  # declares a generator, not tests


class HypothesisRejected(Exception):
    """A signal cannot produce an admissible hypothesis."""


#: Maps a signal class onto the *kind* of change it motivates. Every value is
#: a member of the certified ``LEARNABLE_PROPOSAL_KINDS`` allow-list, so a
#: generated hypothesis can never propose an unlearnable kind.
_PROPOSAL_KIND_BY_SIGNAL: dict[SignalClass, str] = {
    SignalClass.INEFFICIENCY: "optimization_hint",
    SignalClass.RESOURCE_PATTERN: "optimization_hint",
    SignalClass.REPAIR_PATTERN: "pattern_template",
    SignalClass.REPEATED_ERROR: "pattern_template",
    SignalClass.TOOL_PATTERN: "routing_rule",
    SignalClass.IMPROVEMENT: "pattern_template",
    SignalClass.SUCCESS: "documentation_pattern",
    SignalClass.USER_FEEDBACK: "pattern_template",
    SignalClass.REVIEW_RESULT: "pattern_template",
    SignalClass.VALIDATION_RESULT: "pattern_template",
    SignalClass.FAILURE: "workflow_definition",
    SignalClass.REGRESSION: "workflow_definition",
}

#: The measurable criterion each signal class implies. A hypothesis inherits
#: the metric of the signal that motivated it, so its success criterion is
#: checkable rather than aspirational.
_METRIC_BY_SIGNAL: dict[SignalClass, str] = {
    SignalClass.INEFFICIENCY: "latency_ms",
    SignalClass.RESOURCE_PATTERN: "resource_units",
    SignalClass.REPEATED_ERROR: "retry_count",
    SignalClass.TOOL_PATTERN: "tool_success_rate",
    SignalClass.REPAIR_PATTERN: "repair_success_rate",
    SignalClass.SUCCESS: "task_success_rate",
    SignalClass.FAILURE: "task_failure_rate",
    SignalClass.REGRESSION: "regression_count",
    SignalClass.IMPROVEMENT: "improvement_count",
    SignalClass.USER_FEEDBACK: "feedback_score",
    SignalClass.REVIEW_RESULT: "review_approval_rate",
    SignalClass.VALIDATION_RESULT: "validation_pass_rate",
}

#: Metric names whose improvement means "smaller is better". A hypothesis that
#: got this backwards would optimise in the wrong direction, so the direction
#: is derived rather than supplied.
_LOWER_IS_BETTER = frozenset(
    {"latency_ms", "resource_units", "retry_count", "task_failure_rate", "regression_count"}
)


class HypothesisGenerator:
    """Derives multiple competing hypotheses from evidence-backed signals."""

    def generate(
        self,
        *,
        signals: Sequence[LearningSignal],
        scope: LearningScope,
        proposed_change_for: Mapping[str, str] | None = None,
        rollback_strategy: str = "restore the previously active version",
    ) -> tuple[Hypothesis, ...]:
        """Generate one hypothesis per admissible signal, all mutually competing.

        ``proposed_change_for`` maps a signal metric to the concrete change text
        the caller proposes. A metric with no entry yields no hypothesis — the
        generator will not invent a change nobody proposed.
        """
        admissible = self._admissible(signals, scope)
        changes = proposed_change_for or {}

        built: list[Hypothesis] = []
        for signal in admissible:
            change = changes.get(signal.metric)
            if not change:
                logger.debug(
                    "no proposed change supplied for metric %r; skipping", signal.metric
                )
                continue
            built.append(self._build(signal, scope, change, rollback_strategy))

        if len(built) < 2:
            # A single hypothesis is not a hypothesis *set*. Returning it is
            # allowed, but the tuple makes it visible that no competition
            # exists — we never pretend otherwise.
            return tuple(built)

        ids = [h.hypothesis_id for h in built]
        return tuple(
            h.model_copy(
                update={
                    "competing_with": tuple(i for i in ids if i != h.hypothesis_id)
                }
            )
            for h in built
        )

    def lineage_for(
        self,
        hypotheses: Sequence[Hypothesis],
        *,
        project_id: uuid.UUID,
        correlation_id: str,
        signal_ids: Sequence[uuid.UUID] = (),
    ) -> LearningLineage:
        """Record the lineage connecting the signals to the hypotheses."""
        return LearningLineage(
            project_id=project_id,
            correlation_id=correlation_id,
            signal_ids=tuple(signal_ids),
            hypothesis_ids=tuple(h.hypothesis_id for h in hypotheses),
        )

    # ── internals ────────────────────────────────────────────────────────────

    @staticmethod
    def _admissible(
        signals: Sequence[LearningSignal], scope: LearningScope
    ) -> tuple[LearningSignal, ...]:
        """Filter to signals that can legitimately motivate a hypothesis."""
        out: list[LearningSignal] = []
        for signal in signals:
            # A disqualifying signal is never a proposal source (19A §1).
            if signal.is_disqualifying:
                continue
            # Cross-project evidence can never motivate a proposal here.
            if signal.scope.project_id != scope.project_id:
                logger.warning(
                    "rejecting signal %s from project %s for project %s",
                    signal.signal_id,
                    signal.scope.project_id,
                    scope.project_id,
                )
                continue
            # CR-06: no evidence produces no hypothesis.
            if not signal.evidence:
                continue
            out.append(signal)
        return tuple(out)

    @staticmethod
    def _build(
        signal: LearningSignal,
        scope: LearningScope,
        change: str,
        rollback_strategy: str,
    ) -> Hypothesis:
        direction = (
            "decrease" if signal.metric in _LOWER_IS_BETTER else "increase"
        )
        return Hypothesis(
            scope=scope,
            observation=signal.observation,
            supporting_evidence=tuple(signal.evidence),
            proposed_change=change,
            expected_effect=(
                f"{'reduce' if direction == 'decrease' else 'improve'} "
                f"{signal.metric} for scope {scope.kind.value}"
            ),
            success_metric=signal.metric,
            success_threshold=signal.confidence,
            success_direction=direction,
            risk=(
                "unknown until evaluated; the hypothesis is inert and cannot "
                "affect behaviour before promotion"
            ),
            authority=LearningAuthority.L1_INSIGHT,
            rollback_strategy=rollback_strategy,
        )


def proposal_kind_for(signal: LearningSignal) -> str:
    """The certified learnable proposal kind a signal would motivate.

    Derived from the signal's metric prefix, so the result is always inside
    ``LEARNABLE_PROPOSAL_KINDS`` and the boundary cannot reject it for kind.
    """
    stem = signal.metric.removesuffix("_rate")
    try:
        signal_class = SignalClass(stem)
    except ValueError:
        signal_class = SignalClass.SUCCESS
    return _PROPOSAL_KIND_BY_SIGNAL.get(signal_class, "optimization_hint")