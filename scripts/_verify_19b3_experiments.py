"""Ad-hoc verification of the 19B-3 experiment engine (Gates 5-7, 30)."""

from __future__ import annotations

import uuid

from autoforge_learning.experiments import ExperimentEngine
from autoforge_learning.models import (
    ArmOutcome,
    EvidenceRef,
    EvidenceSource,
    Experiment,
    ExperimentArm,
    ExperimentCapability,
    ExperimentOutcome,
    Hypothesis,
    LearningScope,
    LearningScopeKind,
    RegressionSeverity,
    Reward,
    RewardPolarity,
)


def make_experiment(**overrides) -> Experiment:
    project_id = uuid.uuid4()
    scope = LearningScope(kind=LearningScopeKind.PROJECT, project_id=project_id)
    evidence = (
        EvidenceRef.from_payload(EvidenceSource.TELEMETRY, "t:1", {"v": 1}),
    )
    hypothesis = Hypothesis(
        scope=scope,
        observation="latency observed",
        supporting_evidence=evidence,
        proposed_change="use the faster context strategy",
        expected_effect="reduce latency_ms",
        success_metric="latency_ms",
        success_threshold=100.0,
        success_direction="decrease",
        risk="low",
        rollback_strategy="restore prior version",
    )
    kwargs = dict(
        scope=scope,
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


def arm(value: float, *, iterations: int = 2, arm_kind=ExperimentArm.TREATMENT):
    return lambda _arm, _exp: ArmOutcome(
        arm=arm_kind, metrics={"latency_ms": value}, iterations_completed=iterations
    )


def main() -> None:
    engine = ExperimentEngine()
    experiment = make_experiment()

    survived = engine.run(
        experiment=experiment,
        control_runner=arm(150.0, arm_kind=ExperimentArm.CONTROL),
        treatment_runner=arm(80.0),
        environment={"python": "3.12"},
    )
    print("improved ->", survived.outcome.value, "delta", survived.measured_delta)

    refuted = engine.run(
        experiment=experiment,
        control_runner=arm(150.0, arm_kind=ExperimentArm.CONTROL),
        treatment_runner=arm(400.0),
        environment={"python": "3.12"},
    )
    print("worse ->", refuted.outcome.value)

    partial = engine.run(
        experiment=experiment,
        control_runner=arm(150.0, arm_kind=ExperimentArm.CONTROL),
        treatment_runner=arm(80.0, iterations=1),
        environment={"python": "3.12"},
    )
    print("partial ->", partial.outcome.value)

    unmeasured = engine.run(
        experiment=experiment,
        control_runner=arm(150.0, arm_kind=ExperimentArm.CONTROL),
        treatment_runner=lambda a, e: ArmOutcome(arm=a, iterations_completed=2),
        environment={"python": "3.12"},
    )
    print("unmeasured ->", unmeasured.outcome.value)

    reward = Reward(
        scope=experiment.scope,
        objective="latency",
        polarity=RewardPolarity.POSITIVE,
        raw_value=999.0,
        normalized_value=1.0,
        provenance_ref="telemetry:run1",
        provenance_hash="a" * 64,
    )
    breached = engine.run(
        experiment=experiment,
        control_runner=arm(150.0, arm_kind=ExperimentArm.CONTROL),
        treatment_runner=arm(80.0),
        rewards=[reward],
        environment={"python": "3.12"},
        invariant_check=lambda outcome: RegressionSeverity.MAJOR,
    )
    print(
        "breach ->",
        breached.outcome.value,
        "reward_suppressed",
        breached.reward_suppressed,
        "reward_total",
        breached.reward_total,
    )

    floored = engine.run(
        experiment=make_experiment(non_regression_floors={"latency_ms": 90.0}),
        control_runner=arm(150.0, arm_kind=ExperimentArm.CONTROL),
        treatment_runner=arm(80.0),
        environment={"python": "3.12"},
    )
    print("floor breach ->", floored.outcome.value)

    floor_unmeasured = engine.run(
        experiment=make_experiment(non_regression_floors={"resource_units": 1.0}),
        control_runner=arm(150.0, arm_kind=ExperimentArm.CONTROL),
        treatment_runner=arm(80.0),
        environment={"python": "3.12"},
    )
    print("unmeasured floor ->", floor_unmeasured.outcome.value)

    print("reproducible ->", survived.is_reproducible)
    print("notes:", survived.reproduction_instructions[:90], "...")


if __name__ == "__main__":
    main()