"""PI-8 customer-outcome instrumentation — Phase 19 FINAL (Gates 11, 12, 13, 29).

The 19B-3 report listed PI-8 as its fourth open limitation: *customer outcomes
were NOT_APPLICABLE because trustworthy customer-outcome instrumentation did not
exist*. This module closes it honestly.

Two rules govern everything here:

1. **No fabricated outcome.** Every outcome counted here was already produced by
   AutoForge during normal operation — an execution that completed, a
   deterministic validation that passed, a review that accepted, an artifact
   that published. :class:`OutcomeSource` names the concrete producer for each,
   so provenance is verifiable rather than asserted.
2. **No default success.** An empty population is
   :class:`OutcomePopulationEmpty` — PI-8 becomes NOT_APPLICABLE with a specific
   reason. There is no "all passing" default, no zero-as-success fallback, and
   no synthetic reward invented to satisfy PI-8.

The authoritative 19A contract (``phase19/REGRESSION_PROTECTION.md`` §2) defines
PI-8 as *Customer outcomes*, class DEFERRED. This module **measures** that
contract; it does not redefine it. Every measurement preserves the population,
baseline, treatment, outcome definition, numerator, denominator, evidence
references, time window, project and learning version the contract requires.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional, Sequence

from pydantic import Field, model_validator

from autoforge_learning.models import LearningBase

__test__ = False  # declares data models, not tests


# ── authoritative outcome sources ────────────────────────────────────────────


class OutcomeSource(str, Enum):
    """The authoritative outcome sources AutoForge *already* produces.

    Gate 11 forbids fabricating a customer outcome and forbids inventing a
    synthetic reward to satisfy PI-8. Every dimension below is therefore an
    outcome AutoForge already records as part of normal operation — read from
    real events, never synthesised.

    Each names its concrete producer so a reviewer can verify provenance rather
    than take it on trust.
    """

    #: ``DashboardManager.record_execution_completed`` / ``record_execution_failed``
    #: (read_models.py). An execution that ran to completion.
    EXECUTION_SUCCESS = "execution_success"
    #: ``DashboardManager.record_worker_completed(success=...)`` (read_models.py).
    WORKER_SUCCESS = "worker_success"
    #: ``CompletionModule``'s deterministic-validation gate (completion.py:694).
    DETERMINISTIC_VALIDATION_PASS = "deterministic_validation_pass"
    #: ``DashboardManager.record_review_completed(passed=...)`` (read_models.py).
    REVIEW_ACCEPTED = "review_accepted"
    #: ``DashboardManager.record_artifact_published`` (read_models.py).
    ARTIFACT_PUBLISHED = "artifact_published"
    #: ``DashboardManager.record_task_completed`` (read_models.py).
    TASK_COMPLETED = "task_completed"
    #: ``DashboardManager.record_model_call(success=...)`` (read_models.py).
    MODEL_CALL_SUCCESS = "model_call_success"


@dataclass(frozen=True)
class OutcomeObservation:
    """One real outcome event AutoForge already produced.

    ``succeeded`` is the event's own recorded truth (e.g.
    ``record_execution_completed`` fired,
    ``record_review_completed(passed=True)``), never an inference drawn by the
    learner.
    """

    event_ref: str
    succeeded: bool
    observed_at: str
    detail: dict[str, Any] = field(default_factory=dict)


class OutcomePopulationEmpty(ValueError):
    """No authoritative outcome source produced any outcome for this workload.

    This is the *honest* failure: PI-8 becomes NOT_APPLICABLE with a reason.
    It is never converted into a passing zero.
    """


def not_applicable(
    *, project_id: uuid.UUID, source: OutcomeSource, reason: str
) -> None:
    """Signal NOT_APPLICABLE explicitly by raising.

    Callers use this to *prove* a workload has no authoritative outcome source
    rather than defaulting to a result. The reason must be specific enough to
    act on.
    """
    raise OutcomePopulationEmpty(
        f"PI-8 is NOT_APPLICABLE for project {project_id} on source "
        f"{source.value}: {reason}"
    )


class CustomerOutcomeMeasurement(LearningBase):
    """One real, measured PI-8 outcome for one population.

    PI-8 asks whether the *customer* outcome improved. The honest answer comes
    from counting outcomes AutoForge already produced — never from asserting
    success, never from a zero default, never from a fabricated denominator.

    Construction rules that make fabrication impossible:

    * ``denominator`` must be positive; an empty population raises
      :class:`OutcomePopulationEmpty` via :func:`not_applicable`, never
      "0.0 means success".
    * ``numerator`` may not exceed ``denominator``.
    * ``population_size`` may not be smaller than the observed denominator.
    * ``outcome_rate`` is derived, never supplied.
    * ``evidence_refs`` must be non-empty — a measurement with no evidence
      cannot be constructed at all.
    """

    measurement_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    project_id: uuid.UUID
    #: The authoritative source these outcomes came from.
    source: OutcomeSource
    #: ``baseline`` or ``learning_enabled`` — PI-8 compares the two.
    arm: str
    #: Outcomes that actually met the success criterion.
    numerator: int = Field(ge=0)
    #: Real outcomes observed in the population.
    denominator: int = Field(ge=0)
    population_size: Optional[int] = Field(default=None, ge=0)
    #: Contractual definition of the outcome being counted.
    outcome_definition: str
    #: Real evidence identifiers backing every counted outcome.
    evidence_refs: tuple[str, ...] = ()
    window_start: Optional[str] = None
    window_end: Optional[str] = None
    learning_version_id: Optional[uuid.UUID] = None
    candidate_id: Optional[uuid.UUID] = None
    quality_metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate_real_measurement(self) -> "CustomerOutcomeMeasurement":
        if self.denominator <= 0:
            raise ValueError(
                "PI-8 requires a positive denominator: an empty population is "
                "NOT_APPLICABLE, never a 0.0 success rate"
            )
        if self.numerator > self.denominator:
            raise ValueError(
                f"numerator ({self.numerator}) cannot exceed denominator "
                f"({self.denominator})"
            )
        if self.population_size is not None and self.population_size < self.denominator:
            raise ValueError(
                "population_size cannot be smaller than the observed denominator"
            )
        if not self.evidence_refs:
            raise ValueError(
                "PI-8 requires evidence references; a measurement with no "
                "evidence cannot exist"
            )
        if not self.outcome_definition.strip():
            raise ValueError("PI-8 requires an explicit outcome definition")
        return self

    @property
    def outcome_rate(self) -> float:
        """The measured rate. Always derived from real counts."""
        return self.numerator / self.denominator

    @property
    def is_baseline(self) -> bool:
        return self.arm == "baseline"

    @property
    def is_learning_enabled(self) -> bool:
        return self.arm == "learning_enabled"

    def record_hash(self) -> str:
        return hashlib.sha256(
            json.dumps(self.model_dump(mode="json"), sort_keys=True).encode("utf-8")
        ).hexdigest()


@dataclass(frozen=True)
class OutcomeComparison:
    """Baseline versus learning-enabled, measured on real outcomes.

    PI-8 is answered by comparing two *measured* populations. A comparison is
    only produced when both arms have real evidence; otherwise the outcome is
    NOT_APPLICABLE with a stated reason.
    """

    source: OutcomeSource
    outcome_definition: str
    baseline: CustomerOutcomeMeasurement
    treatment: CustomerOutcomeMeasurement
    project_id: uuid.UUID

    @property
    def absolute_delta(self) -> float:
        return self.treatment.outcome_rate - self.baseline.outcome_rate

    @property
    def improved(self) -> bool:
        return self.absolute_delta > 0

    @property
    def regressed(self) -> bool:
        return self.absolute_delta < 0

    @property
    def unchanged(self) -> bool:
        return self.absolute_delta == 0

    def summary(self) -> str:
        return (
            f"{self.source.value}: baseline {self.baseline.numerator}/"
            f"{self.baseline.denominator} = {self.baseline.outcome_rate:.3f} -> "
            f"learning-enabled {self.treatment.numerator}/"
            f"{self.treatment.denominator} = {self.treatment.outcome_rate:.3f} "
            f"(delta {self.absolute_delta:+.3f})"
        )


def compare_outcomes(
    *,
    project_id: uuid.UUID,
    source: OutcomeSource,
    outcome_definition: str,
    baseline_outcomes: Sequence[OutcomeObservation],
    treatment_outcomes: Sequence[OutcomeObservation],
    learning_version_id: Optional[uuid.UUID] = None,
    candidate_id: Optional[uuid.UUID] = None,
) -> OutcomeComparison:
    """Measure PI-8 by counting real outcomes on both arms.

    Nothing is synthesised: the numerator is the count of observations whose
    outcome genuinely succeeded, and the denominator is the count of real
    observations actually observed.
    """
    if not baseline_outcomes and not treatment_outcomes:
        not_applicable(
            project_id=project_id,
            source=source,
            reason=(
                "no authoritative outcome events were produced by either arm; "
                "AutoForge recorded no execution, validation, review or artifact "
                "outcomes to measure"
            ),
        )
    if not baseline_outcomes or not treatment_outcomes:
        missing = "baseline" if not baseline_outcomes else "learning-enabled"
        not_applicable(
            project_id=project_id,
            source=source,
            reason=(
                f"the {missing} arm produced no authoritative outcome events, so "
                f"PI-8 cannot compare two measured populations"
            ),
        )

    baseline = _measure(
        project_id=project_id,
        source=source,
        arm="baseline",
        outcome_definition=outcome_definition,
        observations=baseline_outcomes,
    )
    treatment = _measure(
        project_id=project_id,
        source=source,
        arm="learning_enabled",
        outcome_definition=outcome_definition,
        observations=treatment_outcomes,
        learning_version_id=learning_version_id,
        candidate_id=candidate_id,
    )
    return OutcomeComparison(
        source=source,
        outcome_definition=outcome_definition,
        baseline=baseline,
        treatment=treatment,
        project_id=project_id,
    )


def _measure(
    *,
    project_id: uuid.UUID,
    source: OutcomeSource,
    arm: str,
    outcome_definition: str,
    observations: Sequence[OutcomeObservation],
    learning_version_id: Optional[uuid.UUID] = None,
    candidate_id: Optional[uuid.UUID] = None,
) -> CustomerOutcomeMeasurement:
    if not observations:
        not_applicable(
            project_id=project_id,
            source=source,
            reason=f"the {arm} arm produced no outcome events",
        )
    numerator = sum(1 for o in observations if o.succeeded)
    return CustomerOutcomeMeasurement(
        project_id=project_id,
        source=source,
        arm=arm,
        numerator=numerator,
        denominator=len(observations),
        population_size=len(observations),
        outcome_definition=outcome_definition,
        evidence_refs=tuple(o.event_ref for o in observations),
        window_start=min(o.observed_at for o in observations),
        window_end=max(o.observed_at for o in observations),
        learning_version_id=learning_version_id,
        candidate_id=candidate_id,
        quality_metadata={
            "successful": numerator,
            "failed": len(observations) - numerator,
            "coverage": 1.0,
        },
    )
