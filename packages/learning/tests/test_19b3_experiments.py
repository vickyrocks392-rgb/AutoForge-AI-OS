"""Phase 19B-3 — Gates 5-7, 30: bounded, isolated, reproducible experimentation."""

from __future__ import annotations

import uuid

import pytest

from autoforge_learning import (
    ArmOutcome,
    Experiment,
    ExperimentArm,
    ExperimentCapability,
    ExperimentEngine,
    ExperimentOutcome,
    Hypothesis,
    LearningScope,
    LearningScopeKind,
    Reward,
    RewardPolarity,
)
from autoforge_learning.experiments import ENFORCED_PROHIBITIONS, ExperimentError
from autoforge_learning.models import (
    EvidenceRef,
    EvidenceSource,
    RegressionSeverity,
)


@pytest.fixture()
def project_id() -> uuid.UUID:
    return uuid.uuid4()


@pytest.fixture()
def scope(project_id: uuid.UUID) -> LearningScope:
    return LearningScope(kind=LearningScopeKind.PROJECT, project_id=project_id)


@pytest.fixture()
def hypothesis(scope: LearningScope) -> Hypothesis:
    return Hypothesis(
        scope=scope,
        observation="latency observed",
        supporting_evidence=(
            EvidenceRef.from_payload(EvidenceSource.TELEMETRY, "t:1", {"v": 1}),
        ),
        proposed_change="use the faster context strategy",
        expected_effect="reduce latency_ms",
        success_metric="latency_ms",
        success_threshold=100.0,
        success_direction="decrease",
        risk="low",
        rollback_strategy="restore prior version",
    )


def make_experiment(hypothesis: Hypothesis, **overrides) -> Experiment:
    kwargs = dict(
        scope=hypothesis.scope,
        hypothesis=hypothesis,
        evaluation_metric="latency_ms",
        success_threshold=100.0,
        success_direction="decrease",
        max_duration_seconds=30.0,
        max_iterations=2,
        max_cost_units=10.0,
        declared_capabilities=(ExperimentCapability.CPU_TIME,),
        rollback_target_version_id=uuid.uuid4(),
        seed=42,
    )
    kwargs.update(overrides)
    return Experiment(**kwargs)


def arm(value: float, *, iterations: int = 2, kind=ExperimentArm.TREATMENT):
    def runner(_arm, _experiment):
        return ArmOutcome(
            arm=kind,
            metrics={"latency_ms": value},
            iterations_completed=iterations,
        )

    return runner


def run(hypothesis, experiment=None, **kwargs):
    defaults = dict(
        experiment=experiment or make_experiment(hypothesis),
        control_runner=arm(150.0, kind=ExperimentArm.CONTROL),
        treatment_runner=arm(80.0),
        environment={"python": "3.12"},
    )
    defaults.update(kwargs)
    return ExperimentEngine().run(**defaults)


# ── Gate 5: bounded experimentation ───────────────────────────────────────────


def test_twelve_prohibitions_are_enumerated():
    """19A §3 EX-01..EX-12 are represented as data, not prose."""
    assert len(ENFORCED_PROHIBITIONS) == 12


def test_an_improvement_survives(hypothesis):
    result = run(hypothesis)
    assert result.outcome is ExperimentOutcome.SURVIVED
    assert result.measured_delta == pytest.approx(-70.0)


def test_a_regression_is_refuted(hypothesis):
    assert run(hypothesis, treatment_runner=arm(400.0)).outcome is (
        ExperimentOutcome.REFUTED
    )


def test_an_incomplete_run_is_inconclusive_not_refuted(hypothesis):
    """A partial result must never read as a refutation (p-hacking defence)."""
    result = run(hypothesis, treatment_runner=arm(80.0, iterations=1))
    assert result.outcome is ExperimentOutcome.INCONCLUSIVE


def test_an_unmeasured_arm_is_inconclusive(hypothesis):
    def unmeasured(a, _e):
        return ArmOutcome(arm=a, iterations_completed=2)

    result = run(hypothesis, treatment_runner=unmeasured)
    assert result.outcome is ExperimentOutcome.INCONCLUSIVE


def test_a_raising_arm_is_unmeasured_not_successful(hypothesis):
    def raises(_arm, _experiment):
        raise RuntimeError("arm exploded")

    result = run(hypothesis, treatment_runner=raises)
    assert result.outcome is ExperimentOutcome.INCONCLUSIVE
def test_an_unmeasured_non_regression_floor_blocks(hypothesis):
    """An unmeasured floor cannot be assumed satisfied."""
    result = run(
        hypothesis,
        experiment=make_experiment(
            hypothesis, non_regression_floors={"resource_units": 1.0}
        ),
    )
    assert result.outcome is ExperimentOutcome.TERMINATED_ON_INVARIANT_BREACH


def test_a_floor_breach_beats_a_primary_metric_gain(hypothesis):
    """RM-01 applied inside the experiment: no gain buys a regression."""
    result = run(
        hypothesis,
        experiment=make_experiment(
            hypothesis, non_regression_floors={"latency_ms": 90.0}
        ),
    )
    assert result.outcome is ExperimentOutcome.TERMINATED_ON_INVARIANT_BREACH


def test_an_overshooting_arm_is_refused(hypothesis):
    with pytest.raises(ExperimentError, match="iterations"):
        run(
            hypothesis,
            experiment=make_experiment(hypothesis, max_iterations=1),
            treatment_runner=arm(80.0, iterations=5),
        )


def test_a_cost_overrun_is_refused(hypothesis):
    def expensive(_arm, _experiment):
        return ArmOutcome(
            arm=ExperimentArm.TREATMENT,
            metrics={"latency_ms": 10.0},
            iterations_completed=1,
            cost_units=999.0,
        )

    with pytest.raises(ExperimentError, match="cost"):
        run(
            hypothesis,
            experiment=make_experiment(hypothesis, max_cost_units=1.0),
            treatment_runner=expensive,
        )


def test_an_invariant_breach_terminates_the_run(hypothesis):
    """EX-10 / Gate 18: no waiting for accumulated reward."""
    result = run(hypothesis, invariant_check=lambda outcome: RegressionSeverity.MAJOR)
    assert result.outcome is ExperimentOutcome.TERMINATED_ON_INVARIANT_BREACH
    assert "invariant" in result.termination_reason


def test_a_catastrophic_breach_is_detected(hypothesis):
    result = run(
        hypothesis, invariant_check=lambda outcome: RegressionSeverity.CATASTROPHIC
    )
    assert result.outcome is ExperimentOutcome.TERMINATED_ON_INVARIANT_BREACH


# ── Gate 7: control versus treatment ──────────────────────────────────────────


def test_both_arms_are_always_present(hypothesis):
    result = run(hypothesis)
    assert result.control.arm is ExperimentArm.CONTROL
    assert result.treatment.arm is ExperimentArm.TREATMENT


def test_neither_arm_can_declare_itself_better():
    """ArmOutcome carries measurements, never a verdict."""
    outcome = ArmOutcome(
        arm=ExperimentArm.TREATMENT,
        metrics={"latency_ms": 1.0},
        iterations_completed=1,
    )
    assert not hasattr(outcome, "is_better")
    assert not hasattr(outcome, "won")




# ── Gate 30: reproducibility ──────────────────────────────────────────────────


def test_every_run_records_reproducibility(hypothesis):
    result = run(
        hypothesis,
        code_version="abc123",
        learning_version="19B3",
        model_provider="local",
    )
    assert result.is_reproducible
    for field in (
        str(result.experiment_id),
        str(hypothesis.hypothesis_id),
        result.code_version,
        result.learning_version,
        result.model_provider,
        "seed=42",
    ):
        assert field in result.reproduction_instructions
    # The environment is recorded on the run itself, and its absence is what
    # makes a run non-reproducible.
    assert result.environment["python"] == "3.12"


def test_a_run_without_an_environment_is_not_claimed_reproducible(hypothesis):
    result = run(hypothesis, environment={})
    assert not result.is_reproducible


# ── Gate 8: reward never decides ─────────────────────────────────────────────


def make_reward(scope: LearningScope, value: float = 1.0) -> Reward:
    return Reward(
        scope=scope,
        objective="task_success_rate",
        polarity=RewardPolarity.POSITIVE,
        raw_value=1000.0,
        normalized_value=value,
        provenance_ref="telemetry:r",
        provenance_hash="a" * 64,
    )


def test_a_maximum_reward_cannot_rescue_a_breached_experiment(hypothesis):
    result = run(
        hypothesis,
        rewards=[make_reward(hypothesis.scope)],
        invariant_check=lambda outcome: RegressionSeverity.MAJOR,
    )
    assert result.outcome is ExperimentOutcome.TERMINATED_ON_INVARIANT_BREACH
    assert result.reward_suppressed is True
    assert result.reward_total == 1.0


def test_a_reward_never_changes_the_verdict(hypothesis):
    with_reward = run(hypothesis, rewards=[make_reward(hypothesis.scope)])
    without = run(hypothesis)
    assert with_reward.outcome is without.outcome
    assert with_reward.reward_suppressed is True
    assert without.reward_suppressed is False