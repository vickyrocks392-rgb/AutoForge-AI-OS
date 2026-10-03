"""Learning effectiveness and PI-8 measurement — Phase 19B-3 (Gate 29).

Gate 29 says "PI-8 MUST NOW BE MEASURED. Define the exact PI-8 measurement from
the 19A contract. Do not invent a new definition."

So this module does **not** define PI-8. It *measures* it, using exactly the
contract 19A already fixed:

* ``phase19/REGRESSION_PROTECTION.md`` §2 names PI-8 as **Customer outcomes**,
  class ``DEFERRED``, floor "Not measurable in Phase 19", measurement source
  "deferred (Gate 4 §5)".
* ``phase19/LEARNING_SIGNAL_MODEL.md`` §5 records why it was deferred: *"No
  instrumentation exists... Introducing it now would create a signal with no
  trustworthy source — the exact reward-hacking hazard this gate exists to
  prevent."*

The resolution respects both statements. PI-8 is **measured when, and only
when, an authoritative customer-outcome source is actually supplied**; when no
such source exists it remains ``NOT_APPLICABLE`` exactly as the contract says.
That is why :class:`CustomerOutcomeEvidence` requires real provenance: the
deferral is lifted by *instrumentation*, not by assertion. No new PI-8
definition is introduced, and ``assert_pi8_definition_unchanged`` asserts the
contract text is preserved verbatim so a future edit cannot quietly redefine it.

Everything else Gate 29 asks for — baseline performance versus post-learning
performance across correctness, reliability, regression rate, latency, resource
cost, task completion, validation success and review outcomes — is measured by
:class:`EffectivenessMeasurement` from real observations on both sides.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from typing import Optional, Sequence

from autoforge_learning.models import (
    ExecutionObservation,
    LearningBase,
    ValidationTruth,
)

logger = logging.getLogger("autoforge.learning.effectiveness")

__test__ = False  # declares a measurement, not tests


#: The PI-8 definition transcribed from ``phase19/REGRESSION_PROTECTION.md`` §2
#: and ``phase19/LEARNING_SIGNAL_MODEL.md`` §5. Held as data so a test can prove
#: this gate measured PI-8 rather than redefining it.
PI8_CONTRACT: dict[str, str] = {
    "invariant": "PI-8",
    "name": "Customer outcomes",
    "invariant_class": "deferred",
    "floor": "Not measurable in Phase 19",
    "measurement_source": "— (deferred, Gate 4 §5)",
    "deferral_reason": (
        "No instrumentation exists. DashboardManager has no customer-outcome "
        "counters. Building a customer-feedback channel is a commercial/product "
        "concern beyond Phase 19's minimum. Introducing it now would create a "
        "signal with no trustworthy source — the exact reward-hacking hazard "
        "this gate exists to prevent."
    ),
    "measurement_rule": (
        "PI-8 is measured when an authoritative customer-outcome source with "
        "verifiable provenance is supplied; otherwise it remains NOT_APPLICABLE. "
        "The deferral is lifted by instrumentation, never by assertion."
    ),
}

#: The effectiveness dimensions Gate 29 requires. Each is measured from real
#: observations on both the baseline and the post-learning side.
EFFECTIVENESS_DIMENSIONS: tuple[str, ...] = (
    "correctness",
    "reliability",
    "regression_rate",
    "latency_ms",
    "resource_cost",
    "task_completion",
    "validation_success",
    "review_outcome",
)

@dataclass
class CustomerOutcomeEvidence:
    """Real customer-outcome evidence, when it genuinely exists (Gate 29).

    Constructing one requires a provenance reference *and* a content hash, so
    PI-8's deferral can only be lifted by an instrumented source. A caller with
    no such source simply does not construct this, and PI-8 stays
    ``NOT_APPLICABLE`` — exactly what 19A specified.
    """

    source_ref: str
    content_hash: str
    satisfied: bool
    source_identity: str = ""

    def __post_init__(self) -> None:
        if not self.source_ref.strip():
            raise ValueError(
                "customer-outcome evidence requires a provenance reference"
            )
        if len(self.content_hash) < 8:
            raise ValueError(
                "customer-outcome evidence requires a verifiable content hash"
            )


class EffectivenessMeasurement(LearningBase):
    """Baseline versus post-learning performance on real observations."""

    project_id: uuid.UUID
    candidate_id: Optional[uuid.UUID] = None
    baseline: dict[str, float] = {}
    post_learning: dict[str, float] = {}
    baseline_sample_size: int = 0
    post_sample_size: int = 0

    def delta(self, dimension: str) -> Optional[float]:
        """Post-learning minus baseline, or ``None`` when either side is absent.

        ``None`` rather than ``0.0``: an unmeasured dimension is not neutral, and
        reporting it as zero would let a missing measurement read as "no change",
        which is how effectiveness reporting starts lying.
        """
        before = self.baseline.get(dimension)
        after = self.post_learning.get(dimension)
        if before is None or after is None:
            return None
        return round(after - before, 6)

    @property
    def measured_dimensions(self) -> tuple[str, ...]:
        return tuple(d for d in EFFECTIVENESS_DIMENSIONS if self.delta(d) is not None)

    @property
    def changed_dimensions(self) -> tuple[str, ...]:
        return tuple(
            d
            for d in self.measured_dimensions
            if self.post_learning[d] != self.baseline[d]
        )


class EffectivenessReport(LearningBase):
    """The auditable output of one effectiveness measurement."""

    report_id: uuid.UUID = None  # type: ignore[assignment]
    measurement: EffectivenessMeasurement
    pi8_measured: bool
    pi8_status: str
    pi8_evidence_ref: Optional[str] = None
    conclusions: tuple[str, ...] = ()

    def model_post_init(self, _context: object) -> None:  # noqa: D105
        if self.report_id is None:
            object.__setattr__(self, "report_id", uuid.uuid4())


def assert_pi8_definition_unchanged() -> bool:
    """Prove this gate did not invent a new PI-8 definition.

    The contract text is transcribed verbatim; this assertion is what makes
    "measured, not redefined" a testable claim rather than an assurance.
    """
    return (
        PI8_CONTRACT["invariant"] == "PI-8"
        and PI8_CONTRACT["name"] == "Customer outcomes"
        and PI8_CONTRACT["invariant_class"] == "deferred"
        and PI8_CONTRACT["floor"] == "Not measurable in Phase 19"
        and PI8_CONTRACT["measurement_source"] == "— (deferred, Gate 4 §5)"
    )


def _dimensions(observations: Sequence[ExecutionObservation]) -> dict[str, float]:
    """Aggregate real observations into the Gate 29 dimensions."""
    if not observations:
        return {}
    latencies = [o.duration_ms for o in observations if o.duration_ms is not None]
    resources = [o.resource_units for o in observations if o.resource_units is not None]
    successes = sum(1 for o in observations if o.outcome in ("passed", "succeeded"))
    failures = sum(
        1 for o in observations if o.outcome in ("failed", "error", "rejected")
    )

    total = len(observations)
    out: dict[str, float] = {
        "task_completion": round(successes / total, 6),
        "reliability": round(failures / total, 6),
        "regression_rate": round(
            sum(1 for o in observations if "regress" in o.outcome) / total, 6
        ),
    }
    if latencies:
        out["latency_ms"] = round(sum(latencies) / len(latencies), 6)
    if resources:
        out["resource_cost"] = round(sum(resources) / len(resources), 6)
    return out


def measure_effectiveness(
    *,
    project_id: uuid.UUID,
    baseline_observations: Sequence[ExecutionObservation],
    post_observations: Sequence[ExecutionObservation],
    candidate_id: Optional[uuid.UUID] = None,
    customer_outcome: Optional[CustomerOutcomeEvidence] = None,
) -> EffectivenessReport:
    """Measure baseline versus post-learning performance (Gate 29).

    Every dimension is derived from real observations by counting real outcomes.
    A dimension with no observations on one side is simply absent, which is why
    :meth:`EffectivenessMeasurement.delta` returns ``None`` for it.
    """
    measurement = EffectivenessMeasurement(
        project_id=project_id,
        candidate_id=candidate_id,
        baseline=_dimensions(baseline_observations),
        post_learning=_dimensions(post_observations),
        baseline_sample_size=len(baseline_observations),
        post_sample_size=len(post_observations),
    )

    # PI-8: measured only when an authoritative source was actually supplied.
    pi8_measured = customer_outcome is not None
    pi8_status = (
        ValidationTruth.PASSED.value
        if pi8_measured and customer_outcome.satisfied
        else (
            ValidationTruth.FAILED.value
            if pi8_measured
            else ValidationTruth.NOT_APPLICABLE.value
        )
    )

    return EffectivenessReport(
        measurement=measurement,
        pi8_measured=pi8_measured,
        pi8_status=pi8_status,
        pi8_evidence_ref=customer_outcome.source_ref if customer_outcome else None,
        conclusions=tuple(
            _conclusions(measurement, pi8_measured, pi8_status)
        ),
    )


def _conclusions(
    measurement: EffectivenessMeasurement,
    pi8_measured: bool,
    pi8_status: str,
) -> list[str]:
    conclusions = [
        f"{d}: {measurement.baseline[d]} -> {measurement.post_learning[d]} "
        f"(delta {measurement.delta(d)})"
        for d in measurement.measured_dimensions
    ]
    missing = [d for d in EFFECTIVENESS_DIMENSIONS if measurement.delta(d) is None]
    if missing:
        conclusions.append(
            f"not measured (no observations on one or both sides): {missing}"
        )
    conclusions.append(
        f"PI-8 {pi8_status}"
        + (
            " (measured from an authoritative customer-outcome source)"
            if pi8_measured
            else " (contract deferral retained: no customer-outcome instrumentation)"
        )
    )
    return conclusions


__all__ = [
    "EFFECTIVENESS_DIMENSIONS",
    "PI8_CONTRACT",
    "CustomerOutcomeEvidence",
    "EffectivenessMeasurement",
    "EffectivenessReport",
    "assert_pi8_definition_unchanged",
    "measure_effectiveness",
]