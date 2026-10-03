"""Bounded learning optimization — Phase 19B-3 (Gate 9).

Gate 9 draws a hard line and this module encodes the line as *data*:

    OPTIMIZABLE
      prompt strategies, context-selection strategies, tool-selection
      heuristics, workflow heuristics, retrieval strategies, planning
      heuristics, model-selection policies (where already permitted),
      execution strategies, repair strategies, and validation strategies that
      do NOT weaken validation itself.

    PERMANENTLY OUT OF SCOPE
      authorization, credentials, security policies, HITL policy, guardrails,
      audit policy, trust levels, sandbox escape controls.

The second list is not a policy the caller could relax: it is
:data:`NEVER_OPTIMIZABLE`, which :meth:`BoundedOptimizer.assert_optimizable`
refuses unconditionally. A domain is optimizable only by being present in
:data:`OPTIMIZABLE_TARGETS`, so the default answer for an unknown domain is
"no".
"""
#: Domains that are *never* optimizable, whatever the caller asks for. This is
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from typing import Optional, Sequence

from autoforge_learning.models import LearningBase, ResourceBudget

logger = logging.getLogger("autoforge.learning.optimization")

__test__ = False  # declares an optimizer, not tests


class OptimizationRefused(RuntimeError):
    """The requested optimization target is permanently out of scope."""


#: Domains the bounded optimizer may tune. Anything not listed is refused.
OPTIMIZABLE_TARGETS: frozenset[str] = frozenset(
    {
        "prompt_strategy",
        "context_selection_strategy",
        "tool_selection_heuristic",
        "workflow_heuristic",
        "retrieval_strategy",
        "planning_heuristic",
        "model_selection_policy",
        "execution_strategy",
        "repair_strategy",
        "validation_strategy",
    }
)
#: the machine-readable form of Gate 9's "permanently outside autonomous
#: optimization" list and of 19A §2.1's missing security scopes.
NEVER_OPTIMIZABLE: frozenset[str] = frozenset(
    {
        "authorization",
        "credentials",
        "security_policy",
        "hitl_policy",
        "guardrails",
        "audit_policy",
        "trust_level",
        "sandbox_escape_control",
        "rollback_policy",
        "validation_strength",
        "review_policy",
        "completion_policy",
        "project_isolation",
    }
)


@dataclass
class OptimizationStep:
    """One bounded move of the optimizer."""

    step_id: uuid.UUID
    generation: int
    target: str
    from_value: str
    to_value: str
    accepted: bool
    reason: str
    measured_delta: Optional[float] = None


class OptimizationTrace(LearningBase):
    """The full, auditable record of a bounded optimization run."""

    trace_id: uuid.UUID
    project_id: uuid.UUID
    target: str
    steps: tuple[OptimizationStep, ...] = ()
    best_value: Optional[str] = None
    best_score: Optional[float] = None
    generations_completed: int = 0
    terminated_because: str = ""

    @property
    def improved(self) -> bool:
        return bool(self.steps) and self.best_score is not None


class BoundedOptimizer:
    """Improves one approved target under a hard budget, or refuses to start."""

    def __init__(self, *, budget: ResourceBudget, project_id: uuid.UUID) -> None:
        self._budget = budget
        self._project_id = project_id

    def assert_optimizable(self, target: str) -> None:
        """Refuse any permanently out-of-scope or unknown domain (Gate 9).

        Two independent refusals, checked in order: the explicit deny-list, then
        the allow-list. The deny-list is checked first so a future edit that
        accidentally added "authorization" to the allow-list would still be
        refused here.
        """
        if target in NEVER_OPTIMIZABLE:
            raise OptimizationRefused(
                f"target {target!r} is permanently outside autonomous optimization; "
                "security authority is external to learning"
            )
        if target not in OPTIMIZABLE_TARGETS:
            raise OptimizationRefused(
                f"target {target!r} is not an approved learning optimization target"
            )

    def optimize(
        self,
        *,
        target: str,
        current_value: str,
        candidates: Sequence[str],
        score,
        generation: int = 0,
        trace_id: Optional[uuid.UUID] = None,
    ) -> OptimizationTrace:
        """Search candidate values under the declared budget.

        ``score`` returns a measured value for a candidate, or ``None`` when the
        candidate could not be measured. An unmeasured candidate is never
        accepted: the optimizer has no "best so far" it can fall back on
        without re-measuring it.
        """
        self.assert_optimizable(target)
        if generation > self._budget.max_recursion_depth:
            raise OptimizationRefused(
                f"generation {generation} exceeds the declared recursion depth "
                f"budget of {self._budget.max_recursion_depth}"
            )
        if len(candidates) > self._budget.max_experiments:
            raise OptimizationRefused(
                f"{len(candidates)} candidates exceed the experiment budget of "
                f"{self._budget.max_experiments}"
            )

        steps: list[OptimizationStep] = []
        best_value = current_value
        best_score = score(current_value)

        for candidate in candidates:
            value = score(candidate)
            if value is None:
                steps.append(
                    OptimizationStep(
                        step_id=uuid.uuid4(),
                        generation=generation,
                        target=target,
                        from_value=current_value,
                        to_value=candidate,
                        accepted=False,
                        reason="candidate could not be measured",
                    )
                )
                continue
            improved = best_score is None or value > best_score
            steps.append(
                OptimizationStep(
                    step_id=uuid.uuid4(),
                    generation=generation,
                    target=target,
                    from_value=current_value,
                    to_value=candidate,
                    accepted=improved,
                    reason=(
                        "improved on measured score" if improved else "no improvement"
                    ),
                    measured_delta=(
                        None if best_score is None else value - best_score
                    ),
                )
            )
            if improved:
                best_value, best_score = candidate, value

        return OptimizationTrace(
            trace_id=trace_id or uuid.uuid4(),
            project_id=self._project_id,
            target=target,
            steps=tuple(steps),
            best_value=best_value,
            best_score=best_score,
            generations_completed=generation + 1,
            terminated_because=(
                "budget exhausted"
                if len(steps) >= self._budget.max_experiments
                else "candidate set exhausted"
            ),
        )


__all__ = [
    "NEVER_OPTIMIZABLE",
    "OPTIMIZABLE_TARGETS",
    "BoundedOptimizer",
    "OptimizationRefused",
    "OptimizationStep",
    "OptimizationTrace",
]