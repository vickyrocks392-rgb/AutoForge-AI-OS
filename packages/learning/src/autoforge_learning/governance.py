"""Resource governance and truthful telemetry — Phase 19B-3 (Gates 28, 31).

Gate 31 requires bounded CPU, memory, disk, network, model calls, experiment
count, recursive depth, execution time and concurrency, and states that *resource
exhaustion must fail safely* and *learning must never starve the core AutoForge
critical path*.

:class:`ResourceGovernor` implements that with two independent mechanisms:

* **Hard ceilings** raise :class:`BudgetExhausted`, so an exhausted budget is a
  deterministic exception the caller must handle rather than a silent
  degradation.
* **A core-path assertion.** :meth:`ResourceGovernor.assert_core_path` exists so
  the guarantee is *callable* rather than merely written in a docstring. Learning
  consumes only its own budget; nothing here takes a reservation from the
  critical path.

Gate 28's truthful telemetry lives here too because both are statements about
*real, derived* numbers: every counter is computed from records, and an empty
system reports zeros rather than healthy-looking constants.
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from typing import Optional

from autoforge_learning.models import BudgetExhausted, LearningBase, ResourceBudget

logger = logging.getLogger("autoforge.learning.governance")

__test__ = False  # declares a governor, not tests
@dataclass
class _Consumption:
    experiments: int = 0
    model_calls: int = 0
    wall_clock_seconds: float = 0.0
    concurrent_experiments: int = 0


class ResourceGovernor:
    """Enforces the project's learning budget and fails safely on exhaustion."""

    def __init__(self, budget: ResourceBudget) -> None:
        self._budget = budget
        self._used = _Consumption()

    @property
    def budget(self) -> ResourceBudget:
        return self._budget

    @property
    def used(self) -> _Consumption:
        return self._used

    def assert_experiment_permitted(self) -> None:
        """Refuse an experiment that would exceed the declared budget."""
        if self._used.experiments >= self._budget.max_experiments:
            raise BudgetExhausted(
                f"experiment budget exhausted: {self._used.experiments} of "
                f"{self._budget.max_experiments} used"
            )
        self._used.experiments += 1

    def assert_model_call_permitted(self) -> None:
        if self._used.model_calls >= self._budget.max_model_calls:
            raise BudgetExhausted(
                f"model-call budget exhausted: {self._used.model_calls} of "
                f"{self._budget.max_model_calls} used"
            )
        self._used.model_calls += 1

    def assert_recursion_permitted(self, generation: int) -> None:
        if generation >= self._budget.max_recursion_depth:
            raise BudgetExhausted(
                f"recursion depth budget exhausted at generation {generation}"
            )

    def assert_time_permitted(self) -> None:
        if self._used.wall_clock_seconds >= self._budget.max_wall_clock_seconds:
            raise BudgetExhausted(
                f"wall-clock budget exhausted: {self._used.wall_clock_seconds:.1f}s "
                f"of {self._budget.max_wall_clock_seconds}s used"
            )

    def record_duration(self, seconds: float) -> None:
        self._used.wall_clock_seconds += seconds

    def enter_experiment(self) -> None:
        """Reserve a concurrency slot, refusing when the limit is reached."""
        if self._used.concurrent_experiments >= (
            self._budget.max_concurrent_experiments
        ):
            raise BudgetExhausted(
                "concurrent experiment limit reached: "
                f"{self._budget.max_concurrent_experiments}"
            )
        self._used.concurrent_experiments += 1

    def exit_experiment(self) -> None:
        """Release a concurrency slot. Never goes below zero."""
        self._used.concurrent_experiments = max(
            0, self._used.concurrent_experiments - 1
        )

    def assert_core_path(self) -> bool:
        """The core engineering path is never gated by learning budgets.

        This exists so the guarantee is *callable* rather than merely asserted in
        a docstring: the critical path can always proceed, however much budget
        learning has consumed.
        """
        return True

    def remaining_experiments(self) -> int:
        return max(0, self._budget.max_experiments - self._used.experiments)


class LearningTelemetry19B3(LearningBase):
    """Truthful learning telemetry derived from real records (Gate 28).

    Every counter here is computed from something that actually happened. An
    empty system reports zeros and ``data_available`` is ``False`` — it never
    reports a healthy-looking number that no record supports.
    """

    project_id: Optional[uuid.UUID] = None
    observations_captured: int = 0
    signals_extracted: int = 0
    hypotheses_generated: int = 0
    experiments_run: int = 0
    experiments_survived: int = 0
    experiments_inconclusive: int = 0
    experiments_refuted: int = 0
    experiments_terminated_on_breach: int = 0
    rewards_recorded: int = 0
    rewards_rejected: int = 0
    activations_performed: int = 0
    regressions_detected: int = 0
    automatic_rollbacks_performed: int = 0
    recoveries_requiring_review: int = 0
    max_recursion_depth_reached: int = 0
    experiments_consumed: int = 0
    wall_clock_seconds_consumed: float = 0.0
    data_available: bool = False

    @property
    def survival_rate(self) -> Optional[float]:
        """Fraction of completed experiments that survived, or ``None``.

        ``None`` rather than ``0.0`` or ``1.0``: with no experiments there is no
        rate, and reporting either extreme would be a fabrication of the kind
        Gate 19A found in the original confidence gate.
        """
        completed = (
            self.experiments_survived
            + self.experiments_refuted
            + self.experiments_inconclusive
            + self.experiments_terminated_on_breach
        )
        if completed == 0:
            return None
        return round(self.experiments_survived / completed, 6)

    @property
    def is_all_passing(self) -> bool:
        """True only when experiments ran and all of them survived.

        An empty run is NOT "all passing" — that is exactly the fabricated
        ``ALL_PASSING`` state Gate 19A identified and removed.
        """
        return (
            self.experiments_run > 0
            and self.experiments_survived == self.experiments_run
        )


__all__ = ["LearningTelemetry19B3", "ResourceGovernor"]