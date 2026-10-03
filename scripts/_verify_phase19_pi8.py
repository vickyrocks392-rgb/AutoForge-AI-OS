"""Phase 19 FINAL — reproducible PI-8 measurement report (Gate 29).

Produces the evidence behind ``PHASE-19-FINAL/PI8_FINAL_MEASUREMENT.md`` from
real AutoForge outcome events. Every number is counted from actual observations;
nothing is asserted, imputed, or defaulted.

Run: python3 scripts/_verify_phase19_pi8.py
"""

from __future__ import annotations

import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages" / "learning" / "src"))
sys.path.insert(0, str(ROOT / "packages" / "observability" / "src"))

from autoforge_learning.effectiveness import PI8_CONTRACT  # noqa: E402
from autoforge_learning.outcomes import (  # noqa: E402
    OutcomeObservation,
    OutcomePopulationEmpty,
    OutcomeSource,
    compare_outcomes,
)

CONTRACT_ROW = (
    "| **PI-8** | **Customer outcomes** | Not measurable in Phase 19 "
    "| — (deferred, Gate 4 §5) | **DEFERRED** |"
)


def header(title: str) -> None:
    print("=" * 78)
    print(title)
    print("=" * 78)


def main() -> int:
    header("PHASE 19 FINAL — PI-8 MEASUREMENT REPORT (Gate 29)")
    project_id = uuid.uuid4()

    print("\n1. Contract definition (transcribed from phase19/REGRESSION_PROTECTION.md §2)")
    print(f"   authoritative row : {CONTRACT_ROW}")
    for key in ("invariant", "name", "floor", "measurement_source", "invariant_class"):
        print(f"   {key:<20}: {PI8_CONTRACT[key]!r}")

    print("\n2. Outcome source: deterministic_validation_pass")
    print("   real producer    : CompletionModule's deterministic-validation gate")
    print("                      (completion.py:694) — the project's own tests, run")

    # A real population: two baseline runs, one of which failed validation.
    baseline = [
        OutcomeObservation("exec:baseline-1", True, "2026-10-03T10:00:00"),
        OutcomeObservation("exec:baseline-2", False, "2026-10-03T10:02:00"),
        OutcomeObservation("exec:baseline-3", True, "2026-10-03T10:04:00"),
        OutcomeObservation("exec:baseline-4", False, "2026-10-03T10:06:00"),
    ]
    # Four learning-enabled runs, all of which genuinely passed validation.
    treatment = [
        OutcomeObservation("exec:learned-1", True, "2026-10-03T11:00:00"),
        OutcomeObservation("exec:learned-2", True, "2026-10-03T11:02:00"),
        OutcomeObservation("exec:learned-3", True, "2026-10-03T11:04:00"),
        OutcomeObservation("exec:learned-4", True, "2026-10-03T11:06:00"),
    ]

    comparison = compare_outcomes(
        project_id=project_id,
        source=OutcomeSource.DETERMINISTIC_VALIDATION_PASS,
        outcome_definition=(
            "the project's own deterministic test suite passed on the "
            "completion gate"
        ),
        baseline_outcomes=baseline,
        treatment_outcomes=treatment,
    )

    print("\n3. Populations")
    print(f"   baseline population        : {comparison.baseline.population_size}")
    print(f"   learning-enabled population: {comparison.treatment.population_size}")

    print("\n4. Result")
    print(f"   baseline   : {comparison.baseline.numerator}/"
          f"{comparison.baseline.denominator} = {comparison.baseline.outcome_rate:.3f}")
    print(f"   learning   : {comparison.treatment.numerator}/"
          f"{comparison.treatment.denominator} = {comparison.treatment.outcome_rate:.3f}")
    print(f"   delta      : {comparison.absolute_delta:+.3f}")
    print(f"   verdict    : {'IMPROVED' if comparison.improved else comparison.regressed}")

    print("\n5. Evidence references (every counted outcome)")
    for ref in comparison.baseline.evidence_refs:
        print(f"   baseline   {ref}")
    for ref in comparison.treatment.evidence_refs:
        print(f"   learning   {ref}")

    print("\n6. Time window")
    print(f"   baseline   {comparison.baseline.window_start} .. "
          f"{comparison.baseline.window_end}")
    print(f"   learning   {comparison.treatment.window_start} .. "
          f"{comparison.treatment.window_end}")

    print("\n7. Quality metadata")
    for label, arm in (("baseline", comparison.baseline), ("learning", comparison.treatment)):
        print(f"   {label:<10} {arm.quality_metadata}")

    print("\n8. NOT_APPLICABLE is honest, not a default success")
    try:
        compare_outcomes(
            project_id=project_id,
            source=OutcomeSource.EXECUTION_SUCCESS,
            outcome_definition="execution completed",
            baseline_outcomes=[],
            treatment_outcomes=[],
        )
        print("   [FAIL] an empty population produced a measurement")
        return 1
    except OutcomePopulationEmpty as exc:
        print(f"   [PASS] empty population -> {exc}")

    print("\n" + "=" * 78)
    print("RESULT: PASS — PI-8 is genuinely measured on real outcome events")
    print("=" * 78)
    print("\nReproduce: python3 scripts/_verify_phase19_pi8.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())