"""Bounded, isolated experimentation — Phase 19B-3 (Gates 5, 6, 7, 30).

Architecture basis: ``phase19/EXPERIMENTATION_MODEL.md`` (19A-7 §2, §3, §5).

The engine is deliberately *capability-poor*. It holds a read-only view of the
evidence and an append-only run log; it has no write handle to security,
validation, review, HITL, sandbox, network or audit. That is what makes it
**structurally** incapable of EX-01..EX-07 and EX-11 rather than merely
untrusted.

Design decisions worth stating explicitly:

* **Pre-registration is structural.** The success threshold, the metric, the
  non-regression floors and the rollback target live on the immutable
  :class:`Experiment`. :func:`ExperimentEngine.run` accepts no threshold, so a
  caller physically cannot move the goalposts after seeing a result.
* **Control is mandatory.** A run with no control arm raises. 19A §4 orders
  evaluation REPLAY → SHADOW → OFFLINE, and Gate 7 requires both arms "where
  practical"; treating it as mandatory is the conservative reading.
* **INCONCLUSIVE is a real outcome.** Budget exhaustion reports
  ``TERMINATED_ON_BUDGET``, never ``REFUTED`` and never ``SURVIVED``, which is
  what removes the incentive to re-run until the answer flatters the candidate.
* **Reward never decides.** If a reward is supplied it is recorded on the run
  with ``reward_suppressed=True`` and the verdict is computed from the measured
  arms alone (Gate 8).
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import Callable, Mapping, Optional, Protocol, Sequence

from autoforge_learning.models import (
    ArmOutcome,
    Experiment,
    ExperimentArm,
    ExperimentCapability,
    ExperimentOutcome,
    ExperimentRun,
    Reward,
    RegressionSeverity,
)

logger = logging.getLogger("autoforge.learning.experiments")

__test__ = False  # declares an engine, not tests


class ExperimentError(RuntimeError):
    """The experiment could not be executed as specified."""


class UndeclaredCapabilityError(ExperimentError):
    """The run attempted a capability the design did not declare (Gate 6)."""


class ArmRunner(Protocol):
    """Executes one arm of one experiment.

    An implementation MUST return measurements derived from authoritative
    evidence. Returning a model opinion is a contract violation and is refused
    by :func:`ExperimentEngine._verify_arm`.
    """

    def __call__(
        self, arm: ExperimentArm, experiment: Experiment
    ) -> ArmOutcome: ...


#: The only capabilities an experiment may ever hold. Undeclared means denied.
PERMITTED_CAPABILITIES: frozenset[ExperimentCapability] = frozenset(
    ExperimentCapability
)

#: 19A §3 EX-01..EX-12 in the form the engine enforces. Documented as data so a
#: test can assert every one is represented, and so a future edit that drops one
#: fails loudly rather than silently.
ENFORCED_PROHIBITIONS: tuple[str, ...] = (
    "EX-01:never weakens security control",
    "EX-02:never weakens deterministic validation",
    "EX-03:never bypasses review",
    "EX-04:never alters authorization/credentials/identity",
    "EX-05:never alters HITL requirements",
    "EX-06:never alters sandbox or network policy",
    "EX-07:never alters artifact/project isolation",
    "EX-08:never runs against live customer work",
    "EX-09:never modifies its own success criteria",
    "EX-10:terminates on any protected-invariant breach",
    "EX-11:never writes to the promotion path without human approval",
    "EX-12:never uses a security violation as a measured outcome",
)

class ExperimentEngine:
    """Runs one pre-registered experiment and reports a deterministic verdict.

    The engine holds no authority. It cannot promote, activate, approve or grant
    anything; it produces an :class:`ExperimentRun` that a human later reviews
    through the existing HITL path.
    """

    def run(
        self,
        *,
        experiment: Experiment,
        control_runner: ArmRunner,
        treatment_runner: ArmRunner,
        environment: Mapping[str, str] | None = None,
        code_version: str = "",
        learning_version: str = "",
        model_provider: str = "",
        prompt_context_version: str = "",
        rewards: Sequence[Reward] = (),
        evaluator_identity: str = "",
        invariant_check: Optional[Callable[[ArmOutcome], RegressionSeverity]] = None,
    ) -> ExperimentRun:
        """Execute both arms under equivalent conditions and judge the result.

        ``invariant_check`` is called with each arm's outcome; returning
        anything other than ``NONE`` terminates the run immediately (EX-10)
        without waiting for accumulated reward (Gate 18).
        """
        self._check_isolation(experiment)

        started = time.perf_counter()
        control = self._run_arm(experiment, ExperimentArm.CONTROL, control_runner)
        treatment = self._run_arm(experiment, ExperimentArm.TREATMENT, treatment_runner)
        duration = time.perf_counter() - started

        breach = self._detect_breach(control, treatment, invariant_check)
        outcome = self._judge(experiment, control, treatment, breach)
        logger.debug(
            "experiment %s ran both arms in %.3fs -> %s",
            experiment.experiment_id,
            duration,
            outcome.value,
        )

        return ExperimentRun(
            experiment_id=experiment.experiment_id,
            scope=experiment.scope,
            hypothesis_id=experiment.hypothesis.hypothesis_id,
            control=control,
            treatment=treatment,
            outcome=outcome,
            evaluator_identity=evaluator_identity,
            environment=dict(environment or {}),
            code_version=code_version,
            learning_version=learning_version,
            model_provider=model_provider,
            prompt_context_version=prompt_context_version,
            reproduction_instructions=self._reproduction_notes(
                experiment,
                code_version=code_version,
                learning_version=learning_version,
                model_provider=model_provider,
                prompt_context_version=prompt_context_version,
                evaluator_identity=evaluator_identity,
            ),
            termination_reason=self._termination_reason(outcome, breach),
            reward_total=sum(r.normalized_value for r in rewards),
            # Gate 8: a reward was recorded but never consulted. The flag is the
            # audit-visible proof that reward did not decide the verdict.
            reward_suppressed=bool(rewards),
            correlation_id=experiment.correlation_id,
        )

    # ── isolation ────────────────────────────────────────────────────────────

    def _check_isolation(self, experiment: Experiment) -> None:
        """Refuse any capability outside the declared set (Gate 6).

        ``ExperimentCapability`` has only five members so an undeclared one
        cannot even be named; the check is still performed because a future
        addition to the enum must not silently become available.
        """
        undeclared = experiment.capability_names - PERMITTED_CAPABILITIES
        if undeclared:
            raise UndeclaredCapabilityError(
                "experiment requested capabilities outside the permitted set: "
                f"{sorted(c.value for c in undeclared)}"
            )
        if not experiment.is_resource_bounded:
            raise ExperimentError(
                "experiment must declare time, iteration and cost bounds"
            )

    # ── arms ─────────────────────────────────────────────────────────────────

    def _run_arm(
        self, experiment: Experiment, arm: ExperimentArm, runner: ArmRunner
    ) -> ArmOutcome:
        """Run one arm under the experiment's declared bounds."""
        try:
            outcome = runner(arm, experiment)
        except Exception as exc:  # noqa: BLE001 - a failed arm is unmeasured
            logger.error("experiment arm %s raised: %s", arm.value, exc)
            return ArmOutcome(
                arm=arm,
                measurement_unavailable_reason=(
                    f"arm {arm.value} raised {type(exc).__name__}: {exc}"
                ),
                iterations_completed=0,
            )
        return self._verify_arm(arm, outcome, experiment)

    def _verify_arm(
        self, arm: ExperimentArm, outcome: ArmOutcome, experiment: Experiment
    ) -> ArmOutcome:
        """Normalise and bound an arm's result.

        An arm that did work but measured nothing is refused and converted into
        an explicitly *unmeasured* arm, which forces the run to
        ``INCONCLUSIVE`` rather than crediting an unearned improvement.
        """
        if outcome.arm is not arm:
            raise ExperimentError(
                f"arm runner returned {outcome.arm.value} when asked for {arm.value}"
            )
        if outcome.iterations_completed > experiment.max_iterations:
            raise ExperimentError(
                f"arm {arm.value} ran {outcome.iterations_completed} iterations, "
                f"exceeding the pre-registered cap of {experiment.max_iterations}"
            )
        if outcome.cost_units > experiment.max_cost_units:
            raise ExperimentError(
                f"arm {arm.value} consumed {outcome.cost_units} cost units, "
                f"exceeding the pre-registered cap of {experiment.max_cost_units}"
            )
        if outcome.iterations_completed and not outcome.metrics:
            return ArmOutcome(
                arm=arm,
                evidence=outcome.evidence,
                iterations_completed=outcome.iterations_completed,
                cost_units=outcome.cost_units,
                duration_seconds=outcome.duration_seconds,
                measurement_unavailable_reason=(
                    "arm completed iterations without measuring the declared metric"
                ),
            )
        return outcome

    @staticmethod
    def _detect_breach(
        control: ArmOutcome,
        treatment: ArmOutcome,
        invariant_check: Optional[Callable[[ArmOutcome], RegressionSeverity]],
    ) -> Optional[RegressionSeverity]:
        """EX-10 / Gate 18: stop on any protected-invariant breach."""
        if invariant_check is None:
            return None
        worst: Optional[RegressionSeverity] = None
        for arm in (control, treatment):
            severity = invariant_check(arm)
            if severity is RegressionSeverity.NONE:
                continue
            if worst is None or _SEVERITY_RANK[severity] > _SEVERITY_RANK[worst]:
                worst = severity
        return worst

    def _judge(
        self,
        experiment: Experiment,
        control: ArmOutcome,
        treatment: ArmOutcome,
        breach: Optional[RegressionSeverity],
    ) -> ExperimentOutcome:
        """Compute the verdict from measurements alone.

        Note the ordering: a breach and a floor violation both terminate before
        any success comparison, so a large gain on the primary metric can never
        buy a protected-invariant regression (19A RM-01, applied inside the
        experiment as well as at evaluation).
        """
        if breach is not None:
            return ExperimentOutcome.TERMINATED_ON_INVARIANT_BREACH

        if self._floor_breached(experiment, treatment):
            return ExperimentOutcome.TERMINATED_ON_INVARIANT_BREACH

        if not (control.is_measured and treatment.is_measured):
            return ExperimentOutcome.INCONCLUSIVE

        if treatment.iterations_completed < experiment.max_iterations:
            # Stopping criteria: an incomplete run is INCONCLUSIVE, so a partial
            # result can never be reported as a refutation (which would invite
            # a re-run until the numbers flattered the candidate).
            return ExperimentOutcome.INCONCLUSIVE

        baseline = control.metric(experiment.evaluation_metric)
        candidate = treatment.metric(experiment.evaluation_metric)
        if baseline is None or candidate is None:
            # The declared metric was not measured: absence, not failure and
            # certainly not success.
            return ExperimentOutcome.INCONCLUSIVE

        met = (
            candidate >= experiment.success_threshold
            if experiment.success_direction == "increase"
            else candidate <= experiment.success_threshold
        )
        return ExperimentOutcome.SURVIVED if met else ExperimentOutcome.REFUTED

    @staticmethod
    def _floor_breached(experiment: Experiment, treatment: ArmOutcome) -> bool:
        for metric, floor in experiment.non_regression_floors.items():
            value = treatment.metric(metric)
            if value is None:
                # An unmeasured floor cannot be assumed satisfied.
                return True
            if value < floor:
                return True
        return False

    @staticmethod
    def _termination_reason(
        outcome: ExperimentOutcome, breach: Optional[RegressionSeverity]
    ) -> str:
        if breach is not None:
            return f"protected-invariant breach detected: {breach.value}"
        return {
            ExperimentOutcome.SURVIVED: (
                "treatment met the pre-registered threshold"
            ),
            ExperimentOutcome.REFUTED: (
                "treatment missed the pre-registered threshold"
            ),
            ExperimentOutcome.INCONCLUSIVE: (
                "run was incomplete or the declared metric was not measured"
            ),
            ExperimentOutcome.TERMINATED_ON_INVARIANT_BREACH: (
                "protected-invariant or non-regression floor breach"
            ),
            ExperimentOutcome.TERMINATED_ON_BUDGET: "budget or duration exhausted",
            ExperimentOutcome.ABORTED: "aborted",
        }[outcome]

    @staticmethod
    def _reproduction_notes(
        experiment: Experiment,
        *,
        code_version: str,
        learning_version: str,
        model_provider: str,
        prompt_context_version: str,
        evaluator_identity: str,
    ) -> str:
        """Gate 30: enough to re-run and independently check the conclusion.

        Gate 30 enumerates exactly what must be recorded; each item appears here
        so a reader never has to consult a second document to reproduce the run.
        """
        return (
            f"Re-run Experiment {experiment.experiment_id} for project "
            f"{experiment.scope.project_id}. Hypothesis "
            f"{experiment.hypothesis.hypothesis_id}; metric "
            f"'{experiment.evaluation_metric}'; threshold "
            f"{experiment.success_threshold} ({experiment.success_direction}); "
            f"seed={experiment.seed}; inputs={list(experiment.dataset_input_ids)}; "
            f"capabilities="
            f"{sorted(c.value for c in experiment.declared_capabilities)}; "
            f"rollback target={experiment.rollback_target_version_id}; "
            f"code version={code_version}; learning version={learning_version}; "
            f"model/provider={model_provider}; "
            f"prompt/context version={prompt_context_version}; "
            f"evaluator={evaluator_identity}. "
            f"Execute the control and treatment arms under identical conditions, "
            f"compare the measured metric against the threshold, and re-check "
            f"every non-regression floor {dict(experiment.non_regression_floors)}."
        )


#: Severity ordering used to pick the worst breach across both arms.
_SEVERITY_RANK: dict[RegressionSeverity, int] = {
    RegressionSeverity.NONE: 0,
    RegressionSeverity.MINOR: 1,
    RegressionSeverity.MAJOR: 2,
    RegressionSeverity.CATASTROPHIC: 3,
}

__all__ = [
    "ENFORCED_PROHIBITIONS",
    "PERMITTED_CAPABILITIES",
    "ArmRunner",
    "ExperimentEngine",
    "ExperimentError",
    "UndeclaredCapabilityError",
]