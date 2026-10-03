"""Ad-hoc verification of the 19B-3 continual + forgetting layer (Gates 19-21)."""

from __future__ import annotations

import uuid

from autoforge_learning.continual import (
    CandidateLifecycle,
    CandidateLifecycleState,
    CapabilityCase,
    CapabilitySuite,
    check_preservation,
)


def main() -> None:
    project_id = uuid.uuid4()
    lifecycle = CandidateLifecycle()

    first, created = lifecycle.register(
        candidate_id=uuid.uuid4(),
        project_id=project_id,
        summary="prefer template A",
        fingerprint="fp-1",
    )
    second, created_again = lifecycle.register(
        candidate_id=uuid.uuid4(),
        project_id=project_id,
        summary="prefer template A",
        fingerprint="fp-1",
    )
    print("deduplicated:", created and not created_again)
    print("same identity returned:", first.candidate_id == second.candidate_id)

    print(
        "no destructive methods:",
        not any(
            hasattr(lifecycle, m) for m in ("delete", "purge", "remove", "drop")
        ),
    )

    superseded = lifecycle.transition(
        first.candidate_id,
        CandidateLifecycleState.SUPERSEDED,
        supersedes=uuid.uuid4(),
    )
    print(
        "supersession lineage retained:",
        len(lifecycle.history_for(superseded.superseded_by)) == 1,
    )

    archived = lifecycle.archive(second.candidate_id, "superseded by newer template")
    print("archived state:", archived.state.value)
    print(
        "history retained after archive:",
        len(lifecycle.records) == 1
        and lifecycle.records[0].state is CandidateLifecycleState.ARCHIVED
        and lifecycle.records[0].retirement_reason != "",
    )

    suite = CapabilitySuite()
    suite.record(
        CapabilityCase(
            case_id=uuid.uuid4(), name="pci-cobol-parse", floors={"pass_rate": 0.95}
        )
    )

    ok = check_preservation(
        suite=suite,
        measurements={"pass_rate": 0.99, "latency_ms": 10.0},
        new_performance_metric="latency_ms",
        new_performance_value=5.0,
        required_new_performance=1.0,
    )
    print("new performance + preserved capability ->", ok[0])

    broke = check_preservation(
        suite=suite,
        measurements={"latency_ms": 10.0},
        new_performance_metric="latency_ms",
        new_performance_value=5.0,
        required_new_performance=1.0,
    )
    print("forgetting a solved problem ->", broke[0])
    print("  reason:", broke[1][:80])


if __name__ == "__main__":
    main()