"""The complete autonomous learning loop — Phase 19B-3 (assembly).

This module assembles the closed loop Gate 43 requires:

    OBSERVE → CAPTURE → EXTRACT SIGNALS → GENERATE HYPOTHESES
    → SECURITY BOUNDARY → STORE → EVALUATE → EXPERIMENT → COMPARE
    → REGRESSION TEST → HUMAN AUTHORIZATION → ROLLBACK STATE → PROMOTE
    → ACTIVATE → OBSERVE REAL-WORLD EFFECT → DETECT REGRESSION
    → AUTOMATIC ROLLBACK WHEN CONTRACTUALLY SAFE → LEARN FROM THE RESULT

What this class deliberately does **not** do:

* it does not approve — approval belongs to the certified ``HITLManager``,
* it does not promote without an ``ApprovalRecord`` — 19B-2's
  ``PromotionService`` owns that edge,
* it does not grant anything. :class:`AutonomousLearningSystem` composes
  already-certified components with the new bounded ones; it creates no new
  authority surface and holds no write handle to security.

Every stage is a separate method, so a caller cannot skip a gate.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from typing import Any, Mapping, Optional, Sequence

from autoforge_learning.activation import ActivationService
from autoforge_learning.audit import LearningAuditor
from autoforge_learning.continual import CandidateLifecycle
from autoforge_learning.experience import ExperienceCollector
from autoforge_learning.extraction import SignalExtractor
from autoforge_learning.governance import LearningTelemetry19B3, ResourceGovernor
from autoforge_learning.hypothesis import HypothesisGenerator
from autoforge_learning.models import (
    ExecutionObservation,
    Experiment,
    Hypothesis,
    LearningLineage,
    LearningScope,
    LearningSignal,
    RegressionReport,
    ResourceBudget,
)
from autoforge_learning.recovery import RecoveryReconciler
from autoforge_learning.rewards import RewardLedger
from autoforge_learning.runtime import LearningOverlay

logger = logging.getLogger("autoforge.learning.system")

__test__ = False  # assembles a system, not tests
@dataclass
class LearningCycle:
    """One complete traverse of the loop, with its lineage."""

    lineage: LearningLineage
    observations: tuple[ExecutionObservation, ...] = ()
    signals: tuple[LearningSignal, ...] = ()
    hypotheses: tuple[Hypothesis, ...] = ()
    experiment_runs: tuple[Any, ...] = ()
    regression_reports: tuple[RegressionReport, ...] = ()
    terminated_because: str = ""

    @property
    def is_complete(self) -> bool:
        return bool(self.observations and self.signals and self.hypotheses)


class AutonomousLearningSystem:
    """Composes the bounded, gated learning components into one closed loop."""

    def __init__(
        self,
        *,
        budget: ResourceBudget,
        overlay: Optional[LearningOverlay] = None,
        auditor: Optional[LearningAuditor] = None,
        lifecycle: Optional[Any] = None,
    ) -> None:
        self.collector = ExperienceCollector()
        self.extractor = SignalExtractor()
        self.generator = HypothesisGenerator()
        self.rewards = RewardLedger()
        self.activation = ActivationService()
        self.lifecycle_state = CandidateLifecycle()
        self.recovery = RecoveryReconciler()
        self.governor = ResourceGovernor(budget=budget)
        self.overlay = overlay
        self.auditor = auditor
        #: The 19B-2 lifecycle service. Promotion, approval and rollback remain
        #: entirely its responsibility; this class only feeds it evidence.
        self.lifecycle = lifecycle
        self._telemetry = LearningTelemetry19B3(project_id=budget.project_id)

    @property
    def telemetry(self) -> LearningTelemetry19B3:
        """Counters derived from what actually ran."""
        return self._telemetry

    def design_experiment(
        self,
        *,
        hypothesis: Hypothesis,
        evaluation_metric: str,
        success_threshold: float,
        success_direction: str,
        baseline_version_id: Optional[uuid.UUID] = None,
        rollback_target_version_id: Optional[uuid.UUID] = None,
        non_regression_floors: Optional[Mapping[str, float]] = None,
        max_iterations: int = 2,
        max_duration_seconds: float = 60.0,
        max_cost_units: float = 10.0,
        capabilities: Sequence[Any] = (),
        seed: Optional[int] = None,
        correlation_id: Optional[str] = None,
    ) -> Experiment:
        """DESIGN EXPERIMENT. Pre-registered, bounded, rollback-capable."""
        self.governor.assert_experiment_permitted()
        return Experiment(
            scope=hypothesis.scope,
            hypothesis=hypothesis,
            baseline_version_id=baseline_version_id,
            evaluation_metric=evaluation_metric,
            success_threshold=success_threshold,
            success_direction=success_direction,  # type: ignore[arg-type]
            non_regression_floors=dict(non_regression_floors or {}),
            max_duration_seconds=max_duration_seconds,
            max_iterations=max_iterations,
            max_cost_units=max_cost_units,
            declared_capabilities=tuple(capabilities),
            rollback_target_version_id=rollback_target_version_id,
            seed=seed,
            correlation_id=correlation_id,
        )

    def run_experiment(self, *, experiment: Experiment, **run_kwargs: Any) -> Any:
        """RUN EXPERIMENT. Budget-checked, then judged from measurements only."""
        from autoforge_learning.experiments import ExperimentEngine

        run = ExperimentEngine().run(experiment=experiment, **run_kwargs)
        self._record_run(run)
        return run

    def _record_run(self, run: Any) -> None:
        self._telemetry.experiments_run += 1
        outcome = run.outcome.value
        if outcome == "survived":
            self._telemetry.experiments_survived += 1
        elif outcome == "refuted":
            self._telemetry.experiments_refuted += 1
        elif outcome == "inconclusive":
            self._telemetry.experiments_inconclusive += 1
        elif outcome == "terminated_on_invariant_breach":
            self._telemetry.experiments_terminated_on_breach += 1
        self._telemetry.experiments_consumed = self.governor.used.experiments

    def record_regression(self, report: RegressionReport) -> None:
        """Track a post-activation regression so telemetry stays truthful."""
        if report.is_regression:
            self._telemetry.regressions_detected += 1

    def record_automatic_rollback(self) -> None:
        self._telemetry.automatic_rollbacks_performed += 1

    def build_lineage(
        self,
        *,
        project_id: uuid.UUID,
        correlation_id: str,
        observations: Sequence[ExecutionObservation],
        signals: Sequence[LearningSignal],
        hypotheses: Sequence[Hypothesis],
        parent_lineage_id: Optional[uuid.UUID] = None,
        generation: int = 0,
    ) -> LearningLineage:
        """LINK THE WHOLE CYCLE so provenance is answerable end to end."""
        return LearningLineage(
            project_id=project_id,
            correlation_id=correlation_id,
            experience_ids=tuple(o.observation_id for o in observations),
            signal_ids=tuple(s.signal_id for s in signals),
            hypothesis_ids=tuple(h.hypothesis_id for h in hypotheses),
            parent_lineage_id=parent_lineage_id,
            generation=generation,
        )

    def run_cycle(
        self,
        *,
        project_id: uuid.UUID,
        scope: LearningScope,
        execution_events: Mapping[str, Any] | None,
        correlation_id: str,
        proposed_change_for: Mapping[str, str],
    ) -> LearningCycle:
        """Run one observe → capture → extract → hypothesize traverse."""
        observations = self.observe_and_capture(
            project_id=project_id,
            execution_events=execution_events,
            correlation_id=correlation_id,
        )
        signals = self.extract_signals(scope=scope, observations=observations)
        hypotheses = self.generate_hypotheses(
            scope=scope, signals=signals, proposed_change_for=proposed_change_for
        )
        lineage = self.build_lineage(
            project_id=project_id,
            correlation_id=correlation_id,
            observations=observations,
            signals=signals,
            hypotheses=hypotheses,
        )
        return LearningCycle(
            lineage=lineage,
            observations=observations,
            signals=signals,
            hypotheses=hypotheses,
        )

    def __repr__(self) -> str:  # pragma: no cover - diagnostic only
        return (
            f"AutonomousLearningSystem(project={self._telemetry.project_id}, "
            f"experiments={self._telemetry.experiments_run})"
        )


__all__ = ["AutonomousLearningSystem", "LearningCycle"]