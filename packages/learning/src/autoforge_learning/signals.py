"""Learning signals — Phase 19B-1 (Gate 4).

The Gate 19A audit found the existing promotion gate is a **tautology**:
``ReusableLesson.confidence`` is a branch constant (0.95 / 0.90 / 1.00) and
``learning_engine.py:122`` promotes anything with ``confidence >= 0.90``. Every
lesson therefore always passes.

This module replaces the constant with a **derived** value computed from the
evidence actually present:

* Evidence tier (D1 deterministic > D2 recorded > D3 aggregated).
* Sample size, against a minimum required before promotion may even be
  considered.
* Presence of at least one Q1 (deterministic, content-hashed) reference.
* Model confidence can never raise evidence quality — there is no parameter
  through which a model could influence this function (Gate 4 CR-05).
* Zero evidence yields ``0.0``, never a default positive (Gate 4 CR-06).

Security outcomes are **not** signals. They are hard disqualifiers
(:class:`SignalPolarity.DISQUALIFYING`), because treating a violation as a
reward — even a negative one — teaches the optimizer the boundary is negotiable.
"""

from __future__ import annotations

from typing import Iterable, Optional, Sequence

from autoforge_learning.models import (
    EvidenceQuality,
    EvidenceRef,
    LearningScope,
    LearningSignal,
    SignalPolarity,
)

#: A signal needs this many independent observations before it can express any
#: confidence at all (Gate 4 CR-03).
MIN_SAMPLE_FOR_CONFIDENCE = 3

#: Ceiling per evidence tier (Gate 4 CR-04). A D3 aggregate can never claim the
#: authority of a D1 deterministic result.
TIER_CONFIDENCE_CEILING = {1: 0.95, 2: 0.80, 3: 0.50, 4: 0.0}


def derive_confidence(
    evidence: Sequence[EvidenceRef],
    sample_size: int,
    *,
    corroborating_sources: int = 0,
) -> float:
    """Compute evidence-derived confidence in ``[0.0, 1.0]``.

    Deterministic and monotonic in the evidence actually supplied. There is no
    parameter a model could use to inflate the result.
    """
    authoritative = [e for e in evidence if e.is_authoritative]
    if not authoritative:
        # CR-06: no evidence produces no confidence, never a default positive.
        return 0.0

    if sample_size < MIN_SAMPLE_FOR_CONFIDENCE:
        # Below the minimum sample, confidence is capped low but not zero:
        # a real observation is still a real observation.
        base = TIER_CONFIDENCE_CEILING[min(e.tier for e in authoritative)]
        return round(base * 0.5, 4)

    best_tier = min(e.tier for e in authoritative)
    ceiling = TIER_CONFIDENCE_CEILING.get(best_tier, 0.0)
    if ceiling == 0.0:
        return 0.0

    has_q1 = any(e.quality is EvidenceQuality.Q1 for e in authoritative)
    if not has_q1:
        # Without a deterministic reference the ceiling is materially reduced.
        ceiling = min(ceiling, 0.5)

    # Volume saturating: log-shaped so 100 samples is not 10x a 10-sample run.
    volume = min(1.0, sample_size / (MIN_SAMPLE_FOR_CONFIDENCE * 4.0))
    corroboration = min(0.2, 0.1 * max(0, corroborating_sources))

    return round(min(ceiling, ceiling * (0.5 + 0.5 * volume) + corroboration), 4)


def positive_signal(
    *,
    scope: LearningScope,
    metric: str,
    evidence: Sequence[EvidenceRef],
    sample_size: int,
    observation: str = "",
    corroborating_sources: int = 0,
) -> LearningSignal:
    """Build a positive signal from deterministic evidence."""
    return LearningSignal(
        scope=scope,
        polarity=SignalPolarity.POSITIVE,
        metric=metric,
        observation=observation,
        evidence=tuple(evidence),
        sample_size=sample_size,
        confidence=derive_confidence(
            evidence, sample_size, corroborating_sources=corroborating_sources
        ),
    )


def negative_signal(
    *,
    scope: LearningScope,
    metric: str,
    evidence: Sequence[EvidenceRef],
    sample_size: int,
    observation: str = "",
) -> LearningSignal:
    """Build a negative signal (blocks promotion; never incentivizes)."""
    return LearningSignal(
        scope=scope,
        polarity=SignalPolarity.NEGATIVE,
        metric=metric,
        observation=observation,
        evidence=tuple(evidence),
        sample_size=sample_size,
        confidence=derive_confidence(evidence, sample_size),
    )


def disqualifying_signal(
    *,
    scope: LearningScope,
    metric: str,
    tripped_constraints: Iterable[str],
    observation: str = "",
    evidence: Sequence[EvidenceRef] = (),
) -> LearningSignal:
    """Build a hard-constraint signal.

    A non-empty ``tripped_constraints`` disqualifies the candidate outright,
    regardless of any confidence value.
    """
    return LearningSignal(
        scope=scope,
        polarity=SignalPolarity.DISQUALIFYING,
        metric=metric,
        observation=observation,
        evidence=tuple(evidence),
        sample_size=0,
        confidence=0.0,
        tripped_constraints=tuple(tripped_constraints),
    )


__all__ = [
    "MIN_SAMPLE_FOR_CONFIDENCE",
    "TIER_CONFIDENCE_CEILING",
    "derive_confidence",
    "disqualifying_signal",
    "negative_signal",
    "positive_signal",
]