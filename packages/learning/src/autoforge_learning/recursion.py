"""Recursive self-improvement — Phase 19B-3 (Gate 10).

Gate 10 asks for a real loop:

    LEARN → APPLY → OBSERVE → EVALUATE → LEARN AGAIN

and then constrains it with the requirement that matters most:

    A learning cycle must never recursively expand its own authority.
    The system must not be able to produce
        learning → permission expansion → more learning → more permission

That prohibition is implemented structurally rather than by vigilance:

* **Depth is a counter, not a policy.** ``run_cycle`` increments ``generation``
  and refuses to exceed ``budget.max_recursion_depth``. There is no
  "continue until convergence" branch.
* **The budget is immutable and external.** A ``ResourceBudget`` is a frozen
  model built once for the project; a cycle receives it and cannot widen it.
* **Authority is not an input.** A cycle's ``stage`` callback returns an
  ``OptimizationTrace`` — measurements. It never returns a capability, a scope
  or a permission, so there is nothing for a deeper generation to inherit and
  amplify.
* **Scope is inherited, never widened.** ``assert_no_authority_expansion``
  compares parent and child scope kinds and raises on any widening.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from typing import Callable, Optional, Sequence

from autoforge_learning.models import (
    BudgetExhausted,
    LearningLineage,
    LearningScope,
    ResourceBudget,
)
from autoforge_learning.optimization import OptimizationTrace

logger = logging.getLogger("autoforge.learning.recursion")

__test__ = False  # declares a controller, not tests


class AuthorityExpansionAttempted(RuntimeError):
    """A recursive cycle tried to widen its own authority.

    This is the Gate 10 prohibition in executable form. It is raised rather than
    logged so the attempt can never be mistaken for a successful cycle.
    """


def assert_no_authority_expansion(
    *,
    parent_scope: LearningScope,
    child_scope: LearningScope,
    parent_capabilities: Sequence[str] = (),
    child_capabilities: Sequence[str] = (),
) -> None:
    """Refuse any cycle that widens scope or acquires capabilities.

    Scope is compared as well as capabilities, because a cycle that stayed on
    the same project but widened from ``PROJECT`` to ``GLOBAL_NON_SECURITY``
    scope would be an authority expansion even though it granted itself no new
    capability.
    """
    if parent_scope.project_id != child_scope.project_id:
        raise AuthorityExpansionAttempted(
            "a learning cycle may not change project scope "
            f"({parent_scope.project_id} -> {child_scope.project_id})"
        )
    if parent_scope.kind is not child_scope.kind:
        raise AuthorityExpansionAttempted(
            "a learning cycle may not widen its scope kind "
            f"({parent_scope.kind.value} -> {child_scope.kind.value})"
        )
    gained = set(child_capabilities) - set(parent_capabilities)
    if gained:
        raise AuthorityExpansionAttempted(
            f"a learning cycle may not acquire capabilities; gained {sorted(gained)}"
        )


@dataclass
class CycleResult:
    """The outcome of one bounded recursive cycle."""

    generation: int
    lineage: LearningLineage
    trace: Optional[OptimizationTrace]
    terminated_because: str


class RecursiveImprovement:
    """Runs LEARN → APPLY → OBSERVE → EVALUATE, bounded at every step."""

    def __init__(self, *, budget: ResourceBudget) -> None:
        self._budget = budget
        self._experiments_used = 0

    @property
    def budget(self) -> ResourceBudget:
        return self._budget

    @property
    def experiments_used(self) -> int:
        return self._experiments_used

    def run_cycle(
        self,
        *,
        scope: LearningScope,
        correlation_id: str,
        stage: Callable[[int], OptimizationTrace],
        parent_lineage: Optional[LearningLineage] = None,
        generation: int = 0,
    ) -> CycleResult:
        """Run exactly one bounded cycle.

        ``stage`` performs LEARN/APPLY/OBSERVE/EVALUATE for the given
        generation and returns its trace. It receives the generation number so
        it can vary its behaviour, but it is never told what its budget is —
        the budget is this object's business, and an untrusted stage has no
        parameter through which to widen it.
        """
        if generation >= self._budget.max_recursion_depth:
            raise BudgetExhausted(
                f"generation {generation} reached the recursion depth budget of "
                f"{self._budget.max_recursion_depth}"
            )
        if self._experiments_used >= self._budget.max_experiments:
            raise BudgetExhausted(
                f"experiment budget of {self._budget.max_experiments} exhausted "
                f"after {self._experiments_used} use(s)"
            )

        if parent_lineage is not None:
            # A child may never widen its parent's authority.
            assert_no_authority_expansion(
                parent_scope=_scope_of(parent_lineage),
                child_scope=scope,
            )

        self._experiments_used += 1
        trace = stage(generation)

        return CycleResult(
            generation=generation,
            lineage=LearningLineage(
                project_id=scope.project_id,
                correlation_id=correlation_id,
                parent_lineage_id=(
                    parent_lineage.lineage_id if parent_lineage else None
                ),
                generation=generation,
                experiment_run_ids=(
                    tuple(s.step_id for s in trace.steps) if trace else ()
                ),
            ),
            trace=trace,
            terminated_because=trace.terminated_because if trace else "no trace",
        )

    def run_until_bounded(
        self,
        *,
        scope: LearningScope,
        correlation_id: str,
        stage: Callable[[int], Optional[OptimizationTrace]],
        max_generations: Optional[int] = None,
    ) -> tuple[CycleResult, ...]:
        """Run cycles until the stage stops improving or a budget is exhausted.

        Termination is guaranteed by three independent conditions, so no input
        can make this loop unbounded: the stage returns ``None``, the stage
        returns a trace with no accepted step, or a budget is exhausted (which
        surfaces as :class:`BudgetExhausted` and ends the run with the cycles
        completed so far).
        """
        ceiling = (
            self._budget.max_recursion_depth
            if max_generations is None
            else min(max_generations, self._budget.max_recursion_depth)
        )
        results: list[CycleResult] = []
        parent: Optional[LearningLineage] = None

        for generation in range(ceiling):
            try:
                result = self.run_cycle(
                    scope=scope,
                    correlation_id=correlation_id,
                    stage=stage,
                    parent_lineage=parent,
                    generation=generation,
                )
            except BudgetExhausted as exc:
                logger.info("recursive improvement stopped: %s", exc)
                break

            results.append(result)
            parent = result.lineage

            if result.trace is None:
                break
            if not any(step.accepted for step in result.trace.steps):
                break

        return tuple(results)


def _scope_of(lineage: LearningLineage) -> LearningScope:
    """Recover the project scope a lineage was recorded under."""
    return LearningScope.model_validate(
        {"kind": "project", "project_id": lineage.project_id}
    )


__all__ = [
    "AuthorityExpansionAttempted",
    "CycleResult",
    "RecursiveImprovement",
    "assert_no_authority_expansion",
]