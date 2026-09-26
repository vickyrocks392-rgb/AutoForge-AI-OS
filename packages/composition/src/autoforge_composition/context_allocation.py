"""
Router-backed Model Allocation Port for Context Engineering (18-L Gate 4B).

Implements :class:`autoforge_execution.context_budget.ModelAllocationPort` over
the **existing** :class:`ModelRouterService`. This closes the Gate 4 section 7
"Pass 1 -> allocate -> Pass 2" seam, which Gate 4 verified in isolation but left
unwired in the production system; without it the applied context budget always
fell back to the conservative default instead of reflecting the model that would
actually run the operation.

Design constraints this module deliberately honours:

* **Runtime / provider neutrality.** It only ever reports *constraints* (window
  and output reserve) that the chosen model advertises. It never executes, never
  chooses a runtime, and never names llama.cpp, MLX, or any provider, so the
  Context Engineering layer stays runtime-agnostic.
* **No new dependency.** It depends only on the AI Infrastructure router and the
  Protocol it satisfies, both already part of the canonical architecture.
* **Fail-soft, never fail-loud.** Allocation is a *budget refinement*, not a
  correctness gate. If the router cannot select a candidate (no model declares
  the capability, or none satisfies the constraints), this returns ``None`` and
  the builder applies its documented conservative default and labels it on the
  observability record. A budget hint must never be the reason an engineering
  operation fails.

The declared Pass-1 requirement is forwarded as ``min_context_window_tokens`` so
the router can prefer a model whose real window is large enough, instead of
selecting one and discovering the window is too small only afterwards.
"""

from __future__ import annotations

import logging
from typing import Any, Mapping

from autoforge_ai_infrastructure.metadata import RoutingRequest
from autoforge_ai_infrastructure.router import ModelRouterService

from autoforge_execution.context_budget import ModelWindow

logger = logging.getLogger("autoforge.composition.context_allocation")

__all__ = ["RouterModelAllocationPort"]


class RouterModelAllocationPort:
    """Adapts :class:`ModelRouterService` to the Context Engineering allocation port.

    The name mirrors the Protocol it implements so the composition root reads as
    explicit dependency injection rather than an incidental helper call.
    """

    def __init__(self, router: ModelRouterService) -> None:
        self._router = router

    def allocate_model_window(
        self,
        *,
        min_context_window_tokens: int,
        model_id: str | None = None,
        requirements: Mapping[str, Any] | None = None,
    ) -> ModelWindow | None:
        """Return the selected model's real context window, or ``None``.

        ``None`` is a normal, expected outcome: the caller then applies its
        conservative default and records that it did so. This never raises,
        because a budget refinement must not fail an engineering operation.
        """
        requirements = dict(requirements or {})

        try:
            request = RoutingRequest(
                required_capabilities=frozenset(
                    requirements.get("required_capabilities") or ()
                ),
                min_context_window_tokens=max(1, int(min_context_window_tokens)),
                quality_priority=requirements.get("quality_priority"),
                latency_priority=requirements.get("latency_priority"),
                reliability_minimum=requirements.get("reliability_minimum"),
            )
            decision = self._router.route(request)
            selected = decision.selected.model
        except Exception as exc:  # noqa: BLE001 - budget refinement must not raise
            logger.debug("context budget model allocation skipped: %s", exc)
            return None

        window = getattr(selected, "context_window_tokens", 0) or 0
        if window <= 0:
            return None

        return ModelWindow(
            model_id=selected.model_id,
            context_window_tokens=int(window),
            max_output_tokens=(
                int(selected.max_output_tokens)
                if getattr(selected, "max_output_tokens", None)
                else None
            ),
            provider_id=selected.provider_id,
        )
