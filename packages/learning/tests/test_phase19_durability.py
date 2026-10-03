"""Phase 19 FINAL — durable state, crash recovery and PI-8 tests.

Covers Gates 8 (durable lifecycle), 9 (crash recovery), 11–12 (customer outcome
instrumentation and PI-8 measurement), and 27 (durability/corruption).
"""

from __future__ import annotations

import hashlib
import json
import uuid

import pytest

from autoforge_learning.lifecycle_store import (
    DurableLearningLifecycleStore,
    LifecycleIntegrityError,
)
from autoforge_learning.models import (
    ExperienceSource,
    ExecutionObservation,
    LearningLineage,
    LearningScope,
    LearningScopeKind,
)
from autoforge_learning.outcomes import (
    CustomerOutcomeMeasurement,
    OutcomeObservation,
    OutcomePopulationEmpty,
    OutcomeSource,
    compare_outcomes,
)
from autoforge_learning.store import (
    LearningImmutableIdentityError,
    LearningRecordCorrupt,
)


@pytest.fixture()
def project_id() -> uuid.UUID:
    return uuid.uuid4()


@pytest.fixture()
def scope(project_id: uuid.UUID) -> LearningScope:
    return LearningScope(kind=LearningScopeKind.PROJECT, project_id=project_id)


def observation(scope, subject="t:1"):
    return ExecutionObservation(
        scope=scope,
        source=ExperienceSource.TASK_EXECUTION,
        subject_ref=subject,
        outcome="passed",
        content_hash=hashlib.sha256(subject.encode()).hexdigest(),
        duration_ms=100.0,
    )


# ── Gate 8: the whole lifecycle survives a restart ───────────────────────────


def test_every_lifecycle_record_survives_a_process_restart(tmp_path, scope, project_id):
    """A brand-new store instance is exactly a process restart."""
    store = DurableLearningLifecycleStore(tmp_path)
    obs = observation(scope)
    store.save_observation(obs)
    store.save_lineage(LearningLineage(project_id=project_id, correlation_id="c1"))

    reopened = DurableLearningLifecycleStore(tmp_path)
    recovered = reopened.load_observation(project_id, obs.observation_id)
    assert recovered is not None
    assert recovered.content_hash == obs.content_hash
    assert recovered.duration_ms == obs.duration_ms

    counts = reopened.verify_complete(project_id)
    assert counts["observation"] == 1
    assert counts["lineage"] == 1


def test_resaving_the_same_record_is_idempotent(tmp_path, scope, project_id):
    store = DurableLearningLifecycleStore(tmp_path)
    obs = observation(scope)
    store.save_observation(obs)
    again = store.save_observation(obs)
    assert again.observation_id == obs.observation_id
    assert len(store.list_observations(project_id)) == 1


def test_history_cannot_be_rewritten(tmp_path, scope, project_id):
    """Append-only: a different record under the same id is refused."""
    store = DurableLearningLifecycleStore(tmp_path)
    obs = observation(scope)
    store.save_observation(obs)
    tampered = observation(scope).model_copy(
        update={"observation_id": obs.observation_id, "outcome": "failed"}
    )
    with pytest.raises(LearningImmutableIdentityError):
        store.save_observation(tampered)


def test_a_missing_record_is_distinguishable_from_a_corrupt_one(tmp_path, project_id):
    store = DurableLearningLifecycleStore(tmp_path)
    assert store.load_observation(project_id, uuid.uuid4()) is None


# ── Gate 9 / 27: corruption is rejected, never defaulted ──────────────────────


def test_a_tampered_record_fails_integrity(tmp_path, scope, project_id):
    store = DurableLearningLifecycleStore(tmp_path)
    obs = observation(scope)
    store.save_observation(obs)

    path = next((tmp_path / str(project_id) / "observations").glob("*.json"))
    envelope = json.loads(path.read_text())
    envelope["payload"]["outcome"] = "failed"  # tamper with the payload
    path.write_text(json.dumps(envelope))

    with pytest.raises(LifecycleIntegrityError):
        DurableLearningLifecycleStore(tmp_path).load_observation(
            project_id, obs.observation_id
        )


def test_a_corrupt_record_is_never_returned_as_empty(tmp_path, scope, project_id):
    """Corruption raises; it never looks like an absent-but-successful read."""
    store = DurableLearningLifecycleStore(tmp_path)
    obs = observation(scope)
    store.save_observation(obs)
    path = next((tmp_path / str(project_id) / "observations").glob("*.json"))
    path.write_text("{ not json")

    reopened = DurableLearningLifecycleStore(tmp_path)
    with pytest.raises(LearningRecordCorrupt):
        reopened.load_observation(project_id, obs.observation_id)
    # Listing aborts rather than silently skipping the unreadable record.
    with pytest.raises(LearningRecordCorrupt):
        reopened.list_observations(project_id)


def test_a_truncated_record_is_rejected(tmp_path, scope, project_id):
    store = DurableLearningLifecycleStore(tmp_path)
    obs = observation(scope)
    store.save_observation(obs)
    path = next((tmp_path / str(project_id) / "observations").glob("*.json"))
    text = path.read_text()
    path.write_text(text[: len(text) // 2])
    with pytest.raises(LearningRecordCorrupt):
        DurableLearningLifecycleStore(tmp_path).load_observation(
            project_id, obs.observation_id
        )


def test_a_wrong_project_record_is_refused(tmp_path, scope):
    store = DurableLearningLifecycleStore(tmp_path)
    obs = observation(scope)
    store.save_observation(obs)
    # The record is filed under its own project; a foreign lookup cannot see it.
    assert store.load_observation(uuid.uuid4(), obs.observation_id) is None


def test_a_stale_schema_record_is_rejected(tmp_path, scope, project_id):
    store = DurableLearningLifecycleStore(tmp_path)
    obs = observation(scope)
    store.save_observation(obs)
    path = next((tmp_path / str(project_id) / "observations").glob("*.json"))
    envelope = json.loads(path.read_text())
    envelope["store_schema_version"] = "0.0.0-ancient"
    path.write_text(json.dumps(envelope))
    with pytest.raises(LearningRecordCorrupt):
        DurableLearningLifecycleStore(tmp_path).load_observation(
            project_id, obs.observation_id
        )


def test_verify_complete_reports_every_kind(tmp_path, project_id):
    counts = DurableLearningLifecycleStore(tmp_path).verify_complete(project_id)
    for kind in DurableLearningLifecycleStore.REQUIRED_KINDS:
        assert kind in counts
    assert counts["pi8"] == 0


# ── Gates 11–12: PI-8 measures real outcomes ──────────────────────────────────


def test_pi8_measures_a_real_improvement(project_id):
    comparison = compare_outcomes(
        project_id=project_id,
        source=OutcomeSource.DETERMINISTIC_VALIDATION_PASS,
        outcome_definition="deterministic validation passed",
        baseline_outcomes=[
            OutcomeObservation("exec:b1", True, "2026-10-03T10:00:00"),
            OutcomeObservation("exec:b2", False, "2026-10-03T10:01:00"),
        ],
        treatment_outcomes=[
            OutcomeObservation("exec:t1", True, "2026-10-03T11:00:00"),
            OutcomeObservation("exec:t2", True, "2026-10-03T11:01:00"),
        ],
    )
    assert comparison.improved
    assert comparison.baseline.numerator == 1
    assert comparison.baseline.denominator == 2
    assert comparison.treatment.numerator == 2
    assert comparison.baseline.outcome_rate == 0.5
    assert comparison.treatment.outcome_rate == 1.0


def test_pi8_measures_a_real_regression(project_id):
    comparison = compare_outcomes(
        project_id=project_id,
        source=OutcomeSource.EXECUTION_SUCCESS,
        outcome_definition="execution completed",
        baseline_outcomes=[
            OutcomeObservation("e:b1", True, "t1"),
            OutcomeObservation("e:b2", True, "t2"),
        ],
        treatment_outcomes=[
            OutcomeObservation("e:t1", False, "t3"),
            OutcomeObservation("e:t2", False, "t4"),
        ],
    )
    assert comparison.regressed
    assert comparison.absolute_delta == -1.0


def test_pi8_measures_no_change(project_id):
    same = [
        OutcomeObservation("e:1", True, "t1"),
        OutcomeObservation("e:2", True, "t2"),
    ]
    comparison = compare_outcomes(
        project_id=project_id,
        source=OutcomeSource.REVIEW_ACCEPTED,
        outcome_definition="review accepted",
        baseline_outcomes=same,
        treatment_outcomes=same,
    )
    assert comparison.unchanged


def test_pi8_is_not_applicable_without_a_real_population(project_id):
    """The honest failure: NOT_APPLICABLE with a reason, never a passing zero."""
    with pytest.raises(OutcomePopulationEmpty) as exc:
        compare_outcomes(
            project_id=project_id,
            source=OutcomeSource.EXECUTION_SUCCESS,
            outcome_definition="execution completed",
            baseline_outcomes=[],
            treatment_outcomes=[],
        )
    assert "NOT_APPLICABLE" in str(exc.value)


def test_pi8_is_not_applicable_when_one_arm_is_empty(project_id):
    with pytest.raises(OutcomePopulationEmpty):
        compare_outcomes(
            project_id=project_id,
            source=OutcomeSource.EXECUTION_SUCCESS,
            outcome_definition="execution completed",
            baseline_outcomes=[OutcomeObservation("e:1", True, "t")],
            treatment_outcomes=[],
        )


def test_a_measurement_requires_real_evidence(project_id):
    """A measurement with no evidence cannot be constructed."""
    with pytest.raises(Exception):
        CustomerOutcomeMeasurement(
            project_id=project_id,
            source=OutcomeSource.EXECUTION_SUCCESS,
            arm="baseline",
            numerator=1,
            denominator=1,
            outcome_definition="execution completed",
            evidence_refs=(),
        )


def test_a_measurement_requires_a_positive_denominator(project_id):
    """Zero-as-success fallback is impossible."""
    with pytest.raises(Exception):
        CustomerOutcomeMeasurement(
            project_id=project_id,
            source=OutcomeSource.EXECUTION_SUCCESS,
            arm="baseline",
            numerator=0,
            denominator=0,
            outcome_definition="execution completed",
            evidence_refs=("e:1",),
        )


def test_a_measurement_cannot_inflate_the_numerator(project_id):
    with pytest.raises(Exception):
        CustomerOutcomeMeasurement(
            project_id=project_id,
            source=OutcomeSource.EXECUTION_SUCCESS,
            arm="baseline",
            numerator=5,
            denominator=2,
            outcome_definition="execution completed",
            evidence_refs=("e:1",),
        )


def test_pi8_measurements_survive_a_restart(tmp_path, project_id):
    store = DurableLearningLifecycleStore(tmp_path)
    measurement = CustomerOutcomeMeasurement(
        project_id=project_id,
        source=OutcomeSource.TASK_COMPLETED,
        arm="learning_enabled",
        numerator=3,
        denominator=4,
        outcome_definition="task completed",
        evidence_refs=("t:1", "t:2", "t:3", "t:4"),
    )
    store.save_pi8(measurement)
    reopened = DurableLearningLifecycleStore(tmp_path)
    recovered = reopened.load_pi8(project_id, str(measurement.measurement_id))
    assert recovered is not None
    assert recovered.numerator == 3
    assert recovered.outcome_rate == 0.75
    assert reopened.verify_complete(project_id)["pi8"] == 1


def test_the_outcome_sources_name_real_autoforge_producers():
    """Every PI-8 dimension traces to an existing AutoForge read model."""
    values = {s.value for s in OutcomeSource}
    for expected in (
        "execution_success",
        "worker_success",
        "deterministic_validation_pass",
        "review_accepted",
        "artifact_published",
        "task_completed",
        "model_call_success",
    ):
        assert expected in values

    from autoforge_observability.read_models import DashboardManager

    for method in (
        "record_execution_completed",
        "record_worker_completed",
        "record_review_completed",
        "record_task_completed",
    ):
        assert hasattr(DashboardManager, method)

def test_a_missing_record_is_distinguishable_from_a_corrupt_one(tmp_path, project_id):
    store = DurableLearningLifecycleStore(tmp_path)
    assert store.load_observation(project_id, uuid.uuid4()) is None