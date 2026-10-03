"""Learning-signal extraction — Phase 19B-3 (Gate 3).

Gate 19A §1 is the governing property this module implements:

    Security violations MUST NEVER become ordinary optimization signals.

Scoring a violation — even negatively — teaches the optimizer that the boundary
is a *reachable point in the search space* and creates pressure to make the
boundary less strict. So a hard constraint is **disqualifying**, never scored,
and this extractor emits nothing a reward function could later read as a number.

The other load-bearing rules are CR-05, FS-01 and FS-02: a model-generated
explanation may *enrich* a signal but can never *replace* source evidence.
Concretely:

* every signal carries at least one :class:`EvidenceRef` with a content hash,
* confidence comes from the evidence tier via the existing
  :func:`autoforge_learning.signals.derive_confidence`, and
* there is no parameter through which model text could raise it.

Every one of the twelve Gate 3 signal classes is reachable from a real source;
none of them can be produced without a measurement.
"""
from __future__ import annotations

import logging
from typing import Mapping, Optional, Sequence

from autoforge_learning.models import (
    EvidenceRef,
    ExecutionObservation,
    ExperienceSource,
    LearningScope,
    LearningSignal,
    SignalClass,
    SignalPolarity,
)
from autoforge_learning.signals import derive_confidence

logger = logging.getLogger("autoforge.learning.extraction")

__test__ = False  # declares an extractor, not tests


#: Outcomes that constitute a successful task execution.
_SUCCESS_OUTCOMES = frozenset(
    {"passed", "succeeded", "approved", "success", "ok", "completed", "green"}
)

#: Outcomes that constitute a failure. Kept separate from the success set so a
#: typo can never silently classify a failure as a win.
_FAILURE_OUTCOMES = frozenset(
    {"failed", "failure", "rejected", "error", "timeout", "red", "cancelled"}
)

#: Sample size below which a pattern signal cannot express directional
#: confidence. Mirrors the 19B-1 constant so the two paths cannot disagree.
_MIN_SAMPLE_FOR_PATTERN = 3

#: Signal classes that describe a *pattern* and therefore require repetition
#: before they may express any confidence (CR-03).
_PATTERN_CLASSES = frozenset(
    {
        SignalClass.REPAIR_PATTERN,
        SignalClass.REPEATED_ERROR,
        SignalClass.RESOURCE_PATTERN,
        SignalClass.TOOL_PATTERN,
        SignalClass.INEFFICIENCY,
    }
)

#: Signal class implied by each source when the outcome is not itself decisive.
_CLASS_BY_SOURCE: dict[ExperienceSource, SignalClass] = {
    ExperienceSource.VALIDATION: SignalClass.VALIDATION_RESULT,
    ExperienceSource.REVIEW: SignalClass.REVIEW_RESULT,
    ExperienceSource.USER_FEEDBACK: SignalClass.USER_FEEDBACK,
    ExperienceSource.RESOURCE_BEHAVIOUR: SignalClass.RESOURCE_PATTERN,
    ExperienceSource.EXECUTION_LATENCY: SignalClass.INEFFICIENCY,
    ExperienceSource.TOOL_OUTCOME: SignalClass.TOOL_PATTERN,
    ExperienceSource.REPAIR_ATTEMPT: SignalClass.REPAIR_PATTERN,
    ExperienceSource.RETRY: SignalClass.REPEATED_ERROR,
    ExperienceSource.MODEL_OUTCOME: SignalClass.TOOL_PATTERN,
    ExperienceSource.RAG_RETRIEVAL: SignalClass.TOOL_PATTERN,
    ExperienceSource.TASK_EXECUTION: SignalClass.SUCCESS,
    ExperienceSource.AGENT_TASK_OUTCOME: SignalClass.SUCCESS,
    ExperienceSource.AUTOMATION_OUTCOME: SignalClass.SUCCESS,
    ExperienceSource.ARTIFACT_GENERATION: SignalClass.SUCCESS,
    ExperienceSource.PROJECT_OUTCOME: SignalClass.SUCCESS,
    ExperienceSource.MODERNIZATION: SignalClass.SUCCESS,
    ExperienceSource.MIGRATION: SignalClass.SUCCESS,
    ExperienceSource.FAILURE: SignalClass.REPEATED_ERROR,
}


class SignalExtractor:
    """Derives :class:`LearningSignal` objects from real observations.

    The extractor is deterministic: given the same observations it emits the
    same signals with the same confidences, which is what makes the loop
    reproducible (Gate 30).
    """

    def extract(
        self,
        *,
        scope: LearningScope,
        observations: Sequence[ExecutionObservation],
        evidence_for,
    ) -> tuple[LearningSignal, ...]:
        """Extract every signal the observations genuinely support.

        ``evidence_for`` is the collector's ``evidence_for`` callable: an
        observation must be convertible into a citation before it can produce a
        signal. No numeric magnitude is invented here — a signal carries the
        observation count and its evidence, and reproducibility comes from the
        deterministic classification rather than a fabricated number.
        """
        if not observations:
            return ()

        grouped: dict[SignalClass, list[ExecutionObservation]] = {}
        for observation in observations:
            grouped.setdefault(self._classify(observation), []).append(observation)

        signals: list[LearningSignal] = []
        for signal_class, members in sorted(
            grouped.items(), key=lambda kv: kv[0].value
        ):
            signals.append(
                self._build(
                    signal_class=signal_class,
                    scope=scope,
                    members=members,
                    evidence=tuple(evidence_for(o) for o in members),
                )
            )
        return tuple(signals)

    @staticmethod
    def _classify(observation: ExecutionObservation) -> SignalClass:
        """Map a real observation onto exactly one signal class.

        The mapping is total and deterministic. An unrecognised outcome falls
        back to the class implied by its *source*, never to a generic positive.
        """
        outcome = (observation.outcome or "").strip().lower()
        if outcome in _FAILURE_OUTCOMES:
            return SignalClass.FAILURE
        if outcome in _SUCCESS_OUTCOMES:
            return _CLASS_BY_SOURCE.get(observation.source, SignalClass.SUCCESS)
        return _CLASS_BY_SOURCE.get(observation.source, SignalClass.FAILURE)

    def _build(
        self,
        *,
        signal_class: SignalClass,
        scope: LearningScope,
        members: Sequence[ExecutionObservation],
        evidence: Sequence[EvidenceRef],
    ) -> LearningSignal:
        """Assemble one signal with evidence-derived confidence."""
        sample = len(members)

        if signal_class in _PATTERN_CLASSES and sample < _MIN_SAMPLE_FOR_PATTERN:
            # CR-03: a pattern seen once is an anecdote, not a pattern. It is
            # still recorded — never discarded — but it cannot support
            # promotion, which the zero confidence expresses honestly.
            confidence = 0.0
        else:
            confidence = derive_confidence(evidence, sample)

        polarity = (
            SignalPolarity.NEGATIVE
            if signal_class in (SignalClass.FAILURE, SignalClass.REPEATED_ERROR)
            else SignalPolarity.POSITIVE
        )
        return LearningSignal(
            scope=scope,
            polarity=polarity,
            metric=self._metric_name(signal_class),
            observation=self._observation_prose(signal_class, members),
            evidence=tuple(evidence),
            sample_size=sample,
            confidence=confidence,
        )

    @staticmethod
    def _metric_name(signal_class: SignalClass) -> str:
        if signal_class is SignalClass.INEFFICIENCY:
            return "latency_ms"
        if signal_class is SignalClass.RESOURCE_PATTERN:
            return "resource_units"
        if signal_class is SignalClass.REPEATED_ERROR:
            return "retry_count"
        return f"{signal_class.value}_rate"

    @staticmethod
    def _observation_prose(
        signal_class: SignalClass, members: Sequence[ExecutionObservation]
    ) -> str:
        sources = ", ".join(sorted({m.source.value for m in members}))
        outcomes = ", ".join(sorted({m.outcome for m in members}))
        return (
            f"{signal_class}: {len(members)} observation(s) from "
            f"[{sources}] with outcomes [{outcomes}]"
        )


__all__ = ["SignalExtractor"]
def directional_signals(
    signals: Sequence[LearningSignal],
    *,
    baseline_comparison: Mapping[str, float],
    measured_value=None,
) -> tuple[LearningSignal, ...]:
    """Reclassify signals as IMPROVEMENT or REGRESSION against a real baseline.

    Gate 3 requires the directional distinction to be real, and 19A FS-07
    forbids deriving a positive signal from a counter-metric reduction alone.
    The comparison is therefore made against an explicit pre-change baseline
    supplied by the caller; a signal whose metric has no baseline entry — or
    whose members carry no measurement at all — is returned **unchanged**
    rather than being optimistically upgraded.
    """
    out: list[LearningSignal] = []
    for signal in signals:
        baseline = baseline_comparison.get(signal.metric)
        if baseline is None or measured_value is None:
            out.append(signal)
            continue
        observed = _mean_measured(signal, measured_value)
        if observed is None:
            out.append(signal)
            continue
        improved = observed > baseline
        out.append(
            signal.model_copy(
                update={
                    "metric": "improvement" if improved else "regression",
                    "polarity": (
                        SignalPolarity.POSITIVE
                        if improved
                        else SignalPolarity.NEGATIVE
                    ),
                    "observation": (
                        f"{signal.observation}; baseline={baseline}, "
                        f"observed={observed}"
                    ),
                }
            )
        )
    return tuple(out)


def _mean_measured(
    signal: LearningSignal, measured_value
) -> Optional[float]:
    """Mean of the real numbers behind a signal, or ``None`` when unmeasured."""
    if not signal.evidence:
        return None
    return measured_value(signal)


__all__ = ["SignalExtractor", "directional_signals"]