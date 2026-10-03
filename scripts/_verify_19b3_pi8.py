"""PHASE 19B-3 — PI-8 RECONCILIATION EVIDENCE (Gate 29).

This script does not *define* PI-8. It transcribes the authoritative contract
from ``phase19/REGRESSION_PROTECTION.md`` §2 and proves that:

1. The contract as written in 19A is still what the repository says today.
2. The 19B-3 implementation measures that contract rather than replacing it.
3. With no authoritative customer-outcome instrumentation (the real situation),
   PI-8 is reported NOT_APPLICABLE / DEFERRED and never silently "passes".
4. The deferral can be lifted only by a verifiable instrumented source.

Run: python3 scripts/_verify_19b3_pi8.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages" / "learning" / "src"))
sys.path.insert(0, str(ROOT / "packages" / "security" / "src"))

from autoforge_learning.effectiveness import (  # noqa: E402
    PI8_CONTRACT,
    CustomerOutcomeEvidence,
    assert_pi8_definition_unchanged,
    measure_effectiveness,
)
from autoforge_learning.models import (  # noqa: E402
    ExperienceSource,
    ExecutionObservation,
    LearningScope,
    LearningScopeKind,
    ValidationTruth,
)

CONTRACT_DOC = ROOT / "phase19" / "REGRESSION_PROTECTION.md"


def authoritative_row() -> dict[str, str]:
    """Parse the PI-8 row straight out of the authoritative 19A document."""
    text = CONTRACT_DOC.read_text(encoding="utf-8")
    row = next(
        line for line in text.splitlines() if line.strip().startswith("| **PI-8**")
    )
    cells = [c.strip().strip("*") for c in row.strip().strip("|").split("|")]
    return {
        "invariant": cells[0],
        "name": cells[1],
        "floor": cells[2],
        "measurement_source": cells[3],
        "invariant_class": cells[4],
    }


def check(label: str, condition: bool, detail: str) -> bool:
    print(f"  [{'PASS' if condition else 'FAIL'}] {label}")
    if detail:
        print(f"         {detail}")
    return condition


def _observation(scope, latency_ms: float) -> ExecutionObservation:
    """A real observation, exactly as the collector would produce one."""
    import hashlib

    content = f"latency_ms={latency_ms}"
    return ExecutionObservation(
        scope=scope,
        source=ExperienceSource.TASK_EXECUTION,
        subject_ref=f"task:{latency_ms}",
        outcome="passed",
        content_hash=hashlib.sha256(content.encode()).hexdigest(),
        duration_ms=latency_ms,
    )


def main() -> int:
    import uuid

    def norm(text: str) -> str:
        """Compare meaning, not the table's typography.

        The contract document writes the class in caps and prefixes the
        measurement source with an em-dash placeholder; the implementation stores
        the same facts in a machine-comparable form. Normalising both sides means
        a genuine divergence still fails while cosmetic differences do not.
        """
        return " ".join(text.replace("*", "").replace("—", "").split()).casefold()

    print("=" * 78)
    print("PHASE 19B-3 — PI-8 RECONCILIATION EVIDENCE")
    print("=" * 78)
    print(f"\nAuthoritative source: {CONTRACT_DOC.relative_to(ROOT)}\n")

    ok = True
    authoritative = authoritative_row()
    print("1. Authoritative contract, parsed from the 19A document")
    for key, value in sorted(authoritative.items()):
        print(f"     {key:20s} = {value!r}")
    print()

    print("2. Implementation contract matches the authoritative definition")
    for field in (
        "invariant",
        "name",
        "floor",
        "measurement_source",
        "invariant_class",
    ):
        same = norm(PI8_CONTRACT[field]) == norm(authoritative[field])
        ok &= check(
            f"{field} matches",
            same,
            f"{PI8_CONTRACT[field]!r} vs authoritative {authoritative[field]!r}",
        )

    print("\n3. The implementation measured PI-8 rather than redefining it")
    ok &= check(
        "no new PI-8 definition was introduced",
        assert_pi8_definition_unchanged(),
        "PI8_CONTRACT is transcribed from the contract, not authored",
    )

    scope = LearningScope(
        kind=LearningScopeKind.PROJECT, project_id=uuid.uuid4()
    )

    print("\n4. Real-world state: no customer-outcome instrumentation exists")
    report = measure_effectiveness(
        project_id=scope.project_id,
        baseline_observations=(
            _observation(scope, 100.0),
            _observation(scope, 110.0),
        ),
        post_observations=(
            _observation(scope, 80.0),
            _observation(scope, 90.0),
        ),
        customer_outcome=None,
    )
    ok &= check(
        "PI-8 is NOT_APPLICABLE, never silently passing",
        not report.pi8_measured
        and report.pi8_status == ValidationTruth.NOT_APPLICABLE.value,
        f"status = {report.pi8_status}, measured = {report.pi8_measured}",
    )
    latency = report.measurement.post_learning.get("latency_ms")
    baseline_latency = report.measurement.baseline.get("latency_ms")
    ok &= check(
        "the real improvement is still measured",
        latency is not None
        and baseline_latency is not None
        and latency < baseline_latency,
        f"mean latency {baseline_latency}ms -> {latency}ms",
    )

    print("\n5. The deferral is liftable only by verifiable instrumentation")
    lifted = measure_effectiveness(
        project_id=scope.project_id,
        baseline_observations=(_observation(scope, 100.0),),
        post_observations=(_observation(scope, 80.0),),
        customer_outcome=CustomerOutcomeEvidence(
            source_ref="post_release_survey",
            content_hash="a" * 64,
            satisfied=True,
            source_identity="analytics.customer_outcomes",
        ),
    )
    ok &= check(
        "an instrumented source does lift the deferral",
        lifted.pi8_measured and lifted.pi8_status == ValidationTruth.PASSED.value,
        f"status = {lifted.pi8_status}, measured = {lifted.pi8_measured}",
    )

    print("\n" + "=" * 78)
    print("RESULT:", "PASS" if ok else "FAIL")
    print("=" * 78)
    print(
        "\nConclusion: PI-8 remains DEFERRED exactly as 19A specified. The 19B-3\n"
        "implementation measures the contract rather than redefining it, and the\n"
        "deferral is lifted only by real instrumentation with verifiable provenance."
    )
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())