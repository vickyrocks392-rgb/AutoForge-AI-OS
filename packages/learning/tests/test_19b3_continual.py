"""Phase 19B-3 — Gates 19-21: continual learning and forgetting protection."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from autoforge_learning import (
    CandidateLifecycle,
    CandidateLifecycleState,
    CapabilityCase,
    CapabilitySuite,
    check_preservation,
)


@pytest.fixture()
def project_id() -> uuid.UUID:
    return uuid.uuid4()


def register(lifecycle, project_id, fingerprint, summary="a"):
    return lifecycle.register(
        candidate_id=uuid.uuid4(),
        project_id=project_id,
        summary=summary,
        fingerprint=fingerprint,
    )


# ── Gate 19: continual learning without uncontrolled accumulation ─────────────


def test_the_lifecycle_has_no_destructive_operations():
    """History is never deleted; the absence of the methods is the guarantee."""
    lifecycle = CandidateLifecycle()
    for forbidden in ("delete", "purge", "remove", "drop", "clear"):
        assert not hasattr(lifecycle, forbidden)


def test_duplicates_are_detected_not_duplicated(project_id):
    lifecycle = CandidateLifecycle()
    first, created = register(lifecycle, project_id, "fp-1", "prefer template A")
    second, created_again = register(lifecycle, project_id, "fp-1", "prefer template A")
    assert created and not created_again
    assert first.candidate_id == second.candidate_id
    assert len(lifecycle.records) == 1


def test_distinct_candidates_are_not_collapsed(project_id):
    lifecycle = CandidateLifecycle()
    register(lifecycle, project_id, "fp-1", "a")
    register(lifecycle, project_id, "fp-2", "b")
    assert len(lifecycle.records) == 2


def test_deduplication_is_project_scoped(project_id):
    """The same fingerprint in another project is a different candidate."""
    lifecycle = CandidateLifecycle()
    register(lifecycle, project_id, "fp-1")
    _, created_elsewhere = register(lifecycle, uuid.uuid4(), "fp-1")
    assert created_elsewhere
    assert len(lifecycle.records) == 2


def test_supersession_requires_naming_its_successor(project_id):
    """Lineage is never lost, so supersession must name what replaces it."""
    lifecycle = CandidateLifecycle()
    record, _ = register(lifecycle, project_id, "fp-1")
    with pytest.raises(ValueError, match="superseding"):
        lifecycle.transition(record.candidate_id, CandidateLifecycleState.SUPERSEDED)


def test_supersession_retains_the_chain(project_id):
    """The superseded record and its successor remain linked in lineage."""
    lifecycle = CandidateLifecycle()
    record, _ = register(lifecycle, project_id, "fp-1")
    successor, _ = register(lifecycle, project_id, "fp-2", "b")
    lifecycle.transition(
        record.candidate_id,
        CandidateLifecycleState.SUPERSEDED,
        supersedes=successor.candidate_id,
    )
    chain = lifecycle.history_for(record.candidate_id)
    assert [c.candidate_id for c in chain] == [
        record.candidate_id,
        successor.candidate_id,
    ]
    assert chain[0].state is CandidateLifecycleState.SUPERSEDED


def test_archival_is_a_state_not_an_erasure(project_id):
    lifecycle = CandidateLifecycle()
    record, _ = register(lifecycle, project_id, "fp-1")
    archived = lifecycle.archive(record.candidate_id, "superseded")
    assert archived.state is CandidateLifecycleState.ARCHIVED
    assert archived.retirement_reason == "superseded"
    assert len(lifecycle.records) == 1


def test_an_archived_record_is_immutable(project_id):
    lifecycle = CandidateLifecycle()
    record, _ = register(lifecycle, project_id, "fp-1")
    lifecycle.archive(record.candidate_id, "done")
    with pytest.raises(ValueError, match="immutable"):
        lifecycle.transition(record.candidate_id, CandidateLifecycleState.ACTIVE)


def test_retirement_records_its_reason(project_id):
    lifecycle = CandidateLifecycle()
    record, _ = register(lifecycle, project_id, "fp-1")
    retired = lifecycle.transition(
        record.candidate_id, CandidateLifecycleState.RETIRED, reason="no longer useful"
    )
    assert retired.state is CandidateLifecycleState.RETIRED
    assert retired.retirement_reason == "no longer useful"


def test_stale_candidates_are_identifiable(project_id):
    lifecycle = CandidateLifecycle()
    record, _ = register(lifecycle, project_id, "fp-1")
    assert not lifecycle.stale_candidates()
    aged = type(record)(
        candidate_id=record.candidate_id,
        project_id=record.project_id,
        summary=record.summary,
        fingerprint=record.fingerprint,
    )
    aged.created_at = datetime.now(timezone.utc) - timedelta(days=90)
    lifecycle._records[0] = aged
    assert lifecycle.stale_candidates()


# ── Gate 20: catastrophic-forgetting protection ──────────────────────────────


def build_suite() -> CapabilitySuite:
    suite = CapabilitySuite()
    suite.record(
        CapabilityCase(
            case_id=uuid.uuid4(), name="pci-cobol-parse", floors={"pass_rate": 0.95}
        )
    )
    return suite


def test_new_performance_with_preserved_capability_is_accepted():
    accepted, reason = check_preservation(
        suite=build_suite(),
        measurements={"pass_rate": 0.99, "latency_ms": 10.0},
        new_performance_metric="latency_ms",
        new_performance_value=5.0,
        required_new_performance=1.0,
    )
    assert accepted
    assert "preserved" in reason


def test_forgetting_a_solved_problem_is_refused():
    """A gain on the latest task does not authorize destroying a solved one."""
    accepted, reason = check_preservation(
        suite=build_suite(),
        measurements={"latency_ms": 10.0},
        new_performance_metric="latency_ms",
        new_performance_value=5.0,
        required_new_performance=1.0,
    )
    assert not accepted
    assert "pci-cobol-parse" in reason


def test_failing_to_reach_new_performance_is_refused():
    accepted, _ = check_preservation(
        suite=build_suite(),
        measurements={"pass_rate": 0.99},
        new_performance_metric="latency_ms",
        new_performance_value=0.5,
        required_new_performance=1.0,
    )
    assert not accepted


def test_an_explicitly_authorized_tradeoff_is_honoured():
    """A trade-off requires a recorded human decision, never a self-claim."""
    suite = CapabilitySuite()
    suite.record(
        CapabilityCase(
            case_id=uuid.uuid4(),
            name="legacy-report",
            floors={"legacy_report_pass": 0.99},
            trade_off_authorized=True,
            authorized_by="human.approver",
        )
    )
    accepted, _ = check_preservation(
        suite=suite,
        measurements={"legacy_report_pass": 0.1},
        new_performance_metric="latency_ms",
        new_performance_value=5.0,
        required_new_performance=1.0,
    )
    assert accepted


def test_an_unmeasured_capability_is_a_failure_not_a_pass():
    """'We did not check' must never read as 'it still works'."""
    accepted, _ = check_preservation(
        suite=build_suite(),
        measurements={"latency_ms": 1.0},
        new_performance_metric="latency_ms",
        new_performance_value=5.0,
        required_new_performance=1.0,
    )
    assert not accepted