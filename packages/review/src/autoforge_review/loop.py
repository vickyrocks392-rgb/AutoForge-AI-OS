"""Review Loop — bounded review lifecycle wrapper (section 29 / 35).

Provides the canonical Review Loop:
  RECEIVE -> ANALYZE -> VALIDATE -> TEST -> REVIEW -> REPORT -> QUALITY GATE
  -> APPROVE / REJECT

The loop is bounded and must have deterministic termination conditions.
It must not become an unbounded AI self-critique loop.
"""

from __future__ import annotations

from typing import Any

from autoforge_review.engine import ReviewEngine
from autoforge_review.models import ReviewRequest, ReviewLoopResult


class ReviewLoop:
    """Bounded review loop wrapper (section 29 / 35).

    Executes a single review cycle through the ReviewEngine and returns
    the final loop result.  The engine's internal review_loop method
    handles cycling and HITL decisions; this class is the stable public API.
    """

    def __init__(self, engine: ReviewEngine) -> None:
        self._engine = engine

    async def run(self, request: ReviewRequest, *, max_cycles: int | None = None) -> ReviewLoopResult:
        """Run one bounded review cycle.

        Args:
            request: The review request to process.
            max_cycles: Maximum review cycles before termination (None = engine default).

        Returns:
            The final ReviewLoopResult containing status, cycles, and outcome.
        """
        return await self._engine.review_loop(request, max_cycles=max_cycles)