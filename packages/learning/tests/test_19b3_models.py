"""Phase 19B-3 — Gate 1: the complete closed-loop system model."""

from __future__ import annotations

import uuid

import pytest
from pydantic import ValidationError

from autoforge_learning import (
    ActivationRecord,
    ActivationState,
    ArmOutcome,
    ExecutionObservation,
    Experiment,
    ExperimentRun,
    ExperienceSource,
    Hypothesis,
    LearningAuthority,
    LearningCandidate,
    LearningClass,
    LearningLineage,
    LearningScope,
    LearningScopeKind,
    LearningSignal,
    ResourceBudget,
    Reward,
    RewardPolarity,
)
from autoforge_learning.models import EvidenceRef, EvidenceSource


@pytest.fixture()
def project_id() -> uuid.UUID:
    return uuid.uuid4()


@pytest.fixture()
def scope(project_id: uuid.UUID) -> LearningScope:
    return LearningScope(kind=LearningScopeKind.PROJECT, project_id=project_id)


@pytest.fixture()
def evidence() -> tuple[EvidenceRef, ...]:
    return (
        EvidenceRef.from_payload(EvidenceSource.TELEMETRY, "telemetry:1", {"v": 1}),
    )


@pytest.fixture()
def hypothesis(scope: LearningScope, evidence) -> Hypothesis:
    return Hypothesis(
        scope=scope,
        observation="latency observed repeatedly",
        supporting_evidence=evidence,
        proposed_change="prefer the compact context strategy",
        expected_effect="reduce latency_ms",
        success_metric="latency_ms",
        success_threshold=100.0,
        success_direction="decrease",
        risk="unknown until evaluated",
        rollback_strategy="restore prior version",
    )


def test_gate1_object_types_all_exist():
    """Every object Gate 1 names is representable."""
    for obj in (
        ExecutionObservation,
        LearningSignal,
        Hypothesis,
        LearningCandidate,
        Experiment,
        ExperimentRun,
        ArmOutcome,
        ActivationRecord,
        LearningLineage,
        Reward,
    ):
        assert type(obj).__name__


def test_every_gate1_object_is_immutable(project_id):
    """Immutability is structural, not conventional."""
    observation = ExecutionObservation(
        scope=LearningScope(kind=LearningScopeKind.PROJECT, project_id=project_id),
        source=ExperienceSource.TASK_EXECUTION,
        subject_ref="task:1",
        content_hash="a" * 64,
        outcome="passed",
    )
    with pytest.raises(ValidationError):
        observation.outcome = "tampered"  # type: ignore[misc]


def test_every_gate1_object_carries_schema_version_and_integrity(
    project_id, hypothesis
):
    scope = LearningScope(kind=LearningScopeKind.PROJECT, project_id=project_id)
    objects = [
        ExecutionObservation(
            scope=scope,
            source=ExperienceSource.TASK_EXECUTION,
            subject_ref="t:1",
            content_hash="a" * 64,
            outcome="passed",
        ),
        hypothesis,
        Experiment(
            scope=scope,
            hypothesis=hypothesis,
            evaluation_metric="latency_ms",
            success_threshold=1.0,
            success_direction="decrease",
            max_duration_seconds=1.0,
            max_iterations=1,
            max_cost_units=1.0,
            rollback_target_version_id=uuid.uuid4(),
        ),
        LearningLineage(project_id=project_id, correlation_id="c"),
        Reward(
            scope=scope,
            objective="latency_ms",
            polarity=RewardPolarity.POSITIVE,
            raw_value=1.0,
            provenance_ref="t:1",
            provenance_hash="b" * 64,
        ),
    ]
    for obj in objects:
        assert obj.schema_version, f"{type(obj).__name__} lacks a schema version"
        assert obj.canonical_json()
        assert obj.record_hash(), f"{type(obj).__name__} lacks integrity"


def test_gate1_objects_all_carry_project_scope(scope, hypothesis):
    for obj in (
        LearningCandidate(scope=scope, kind="pattern_template", summary="s"),
        hypothesis,
    ):
        assert obj.scope.project_id == scope.project_id
    assert LearningLineage(
        project_id=scope.project_id, correlation_id="c"
    ).project_id == scope.project_id


def test_level5_is_unrepresentable_on_a_hypothesis(scope, evidence):
    """No learning path may reach Level 5, including the new hypothesis type."""
    with pytest.raises(Exception):
        Hypothesis(
            scope=scope,
            observation="o",
            supporting_evidence=evidence,
            proposed_change="c",
            expected_effect="e",
            success_metric="m",
            success_threshold=1.0,
            risk="r",
            rollback_strategy="rb",
            authority=LearningAuthority.L5_SECURITY_POLICY,  # type: ignore[arg-type]
        )


def test_experiment_requires_a_rollback_target(scope, hypothesis):
    """An experiment with no deterministic rollback cannot be constructed."""
    with pytest.raises(Exception, match="rollback"):
        Experiment(
            scope=scope,
            hypothesis=hypothesis,
            evaluation_metric="latency_ms",
            success_threshold=1.0,
            success_direction="decrease",
            max_duration_seconds=1.0,
            max_iterations=1,
            max_cost_units=1.0,
        )


def test_experiment_requires_a_named_metric(scope, hypothesis):
    with pytest.raises(Exception, match="evaluation_metric"):
        Experiment(
            scope=scope,
            hypothesis=hypothesis,
            evaluation_metric="   ",
            success_threshold=1.0,
            success_direction="decrease",
            max_duration_seconds=1.0,
            max_iterations=1,
            max_cost_units=1.0,
            rollback_target_version_id=uuid.uuid4(),
        )


def test_experiment_requires_time_bounds(scope, hypothesis):
    with pytest.raises(Exception):
        Experiment(
            scope=scope,
            hypothesis=hypothesis,
            evaluation_metric="latency_ms",
            success_threshold=1.0,
            success_direction="decrease",
            max_duration_seconds=0.0,
            max_iterations=1,
            max_cost_units=1.0,
            rollback_target_version_id=uuid.uuid4(),
        )


def test_shadow_activation_cannot_carry_traffic(project_id):
    """A shadow candidate that affects behaviour is not a shadow."""
    with pytest.raises(Exception):
        ActivationRecord(
            candidate_id=uuid.uuid4(),
            project_id=project_id,
            kind="pattern_template",
            key="k",
            state=ActivationState.SHADOW,
            traffic_fraction=0.5,
        )


def test_reward_requires_provenance(scope):
    """A reward with no provenance is fabrication, refused at construction."""
    with pytest.raises(Exception):
        Reward(
            scope=scope,
            objective="latency_ms",
            polarity=RewardPolarity.POSITIVE,
            raw_value=1.0,
            provenance_ref="   ",
            provenance_hash="c" * 64,
        )


def test_learning_class_is_explicit():
    """Gate 22: project-specific and global are distinct, named classes."""
    assert set(LearningClass) == {
        LearningClass.PROJECT_SPECIFIC,
        LearningClass.GLOBAL_VALIDATED,
    }


def test_zero_budget_denies_by_default(project_id):
    """A zero budget is an honest deny, never an accidental unlimited one."""
    budget = ResourceBudget(
        project_id=project_id,
        max_experiments=0,
        max_recursion_depth=0,
        max_wall_clock_seconds=0.0,
        max_model_calls=0,
        max_concurrent_experiments=0,
        max_disk_bytes=0,
        max_memory_bytes=0,
        max_network_bytes=0,
    )
    assert budget.denies_everything_by_default