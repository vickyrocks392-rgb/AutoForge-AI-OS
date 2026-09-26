"""
ContextWindowBudget — request-scoped, model-aware context budgeting.

Gate 2 §3. Implements the approved design exactly:

* This is a **sibling** abstraction, NOT the modernization ``ContextBudget``.
  Verified constraint: ``autoforge-execution`` does not depend on
  ``autoforge-modernization``, and that ``ContextBudget`` is keyed by
  ``project_id`` / ``job_id`` / ``unit_id`` — i.e. it is *job/unit scoped*, whereas
  this budget is scoped to a single intelligence operation. The modernization model
  is left completely untouched.
* Model awareness comes from the already-existing registry metadata
  (``ModelMetadata.context_window_tokens`` / ``max_output_tokens``). No new
  model-window fields are introduced and no model (M6 or otherwise) is hardcoded.
* ``budget_source`` records where the window came from, so a conservative default is
  never mistaken for a real model capability.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping, Protocol, runtime_checkable

from autoforge_execution.errors import InvalidBudgetError

#: Used only when no window can be obtained from the caller or model metadata.
#: Deliberately small and explicitly labelled as an assumption on the record.
CONSERVATIVE_DEFAULT_WINDOW_TOKENS = 8192
CONSERVATIVE_DEFAULT_OUTPUT_RESERVE_TOKENS = 1024


class BudgetSource(str, Enum):
    """Where the applied context window came from (Gate 2 §8, ``budget_source``)."""

    CALLER = "caller"
    MODEL_METADATA = "model_metadata"
    CONSERVATIVE_DEFAULT = "conservative_default"


@dataclass(frozen=True)
class ModelWindow:
    """A resolved model context window (Gate 4 §7, Pass 2 input).

    Produced by whatever allocator sits behind :class:`ModelAllocationPort`. The
    Context Engineering layer never learns *which* runtime answered — only the
    window that model actually guarantees. That is what keeps this module
    runtime-neutral: llama.cpp, MLX, or a cloud runtime are indistinguishable here.
    """

    model_id: str
    context_window_tokens: int
    max_output_tokens: int | None = None
    provider_id: str = ""


@runtime_checkable
class ModelAllocationPort(Protocol):
    """Pass 1 -> allocate -> Pass 2 seam (Gate 4 §7).

    Implemented at the composition root over the existing Model Router. The
    router allocates a model; this port only reports the *allocated model's* real
    constraints back to Context Engineering. It never executes anything and it
    never chooses a runtime.

    ``min_context_window_tokens`` carries the Pass-1 declared requirement so the
    allocator can honour the two-pass design instead of guessing a model and
    discovering afterwards that its window was too small.
    """

    def allocate_model_window(
        self,
        *,
        min_context_window_tokens: int,
        model_id: str | None = None,
        requirements: Mapping[str, Any] | None = None,
    ) -> ModelWindow | None:
        """Return the allocated model's real window, or ``None`` if unallocated."""
        ...


@dataclass
class ContextWindowBudget:
    """Token budget for one intelligence operation's context window.

    Derives ``available_for_context_tokens`` from the model window minus the
    reservations that are not context: required output capacity, system
    instructions, and tool/schema overhead.
    """

    model_context_window_tokens: int
    reserved_for_output_tokens: int = 0
    reserved_for_system_tokens: int = 0

    def __post_init__(self) -> None:
        if self.model_context_window_tokens < 0:
            raise InvalidBudgetError(
                "model_context_window_tokens must be non-negative",
                details={"model_context_window_tokens": self.model_context_window_tokens},
            )
        for name in (
            "reserved_for_output_tokens",
            "reserved_for_system_tokens",
            "reserved_for_tool_tokens",
        ):
            value = getattr(self, name)
            if value < 0:
                raise InvalidBudgetError(
                    f"{name} must be non-negative",
                    details={name: value},
                )
        if self.reserved_for_output_tokens > self.model_context_window_tokens:
            raise InvalidBudgetError(
                "reserved_for_output_tokens exceeds the model context window",
                details={
                    "reserved_for_output_tokens": self.reserved_for_output_tokens,
                    "model_context_window_tokens": self.model_context_window_tokens,
                },
            )

        self.available_for_context_tokens = (
            self.model_context_window_tokens
            - self.reserved_for_output_tokens
            - self.reserved_for_system_tokens
            - self.reserved_for_tool_tokens
        )
        if self.available_for_context_tokens < 0:
            raise InvalidBudgetError(
                "reservations exceed the model context window; no room for context",
                details={
                    "model_context_window_tokens": self.model_context_window_tokens,
                    "reserved_for_output_tokens": self.reserved_for_output_tokens,
                    "reserved_for_system_tokens": self.reserved_for_system_tokens,
                    "reserved_for_tool_tokens": self.reserved_for_tool_tokens,
                },
            )
        self._remaining = self.available_for_context_tokens

    # -- accounting ---------------------------------------------------------

    @property
    def remaining_tokens(self) -> int:
        return self._remaining

    def try_reserve(self, tokens: int) -> bool:
        """Reserve ``tokens`` if they fit. Returns False without mutating on failure."""
        if tokens < 0:
            raise InvalidBudgetError(
                "cannot reserve a negative token count", details={"tokens": tokens}
            )
        if tokens > self._remaining:
            return False
        self._remaining -= tokens
        self.used_tokens += tokens
        self.peak_used_tokens = max(self.peak_used_tokens, self.used_tokens)
        return True

    def release(self, tokens: int) -> None:
        """Return ``tokens`` to the pool, clamped at the available ceiling."""
        if tokens < 0:
            raise InvalidBudgetError(
                "cannot release a negative token count", details={"tokens": tokens}
            )
        self.used_tokens = max(0, self.used_tokens - tokens)
        self._remaining = min(self.available_for_context_tokens, self._remaining + tokens)

    def is_over_budget(self) -> bool:
        return self.used_tokens > self.available_for_context_tokens

    def shortfall_tokens(self) -> int:
        """Tokens still needed beyond this window (Gate 2 §1.4 two-pass reporting)."""
        if self.declared_required_window_tokens <= self.model_context_window_tokens:
            return 0
        return self.declared_required_window_tokens - self.model_context_window_tokens

    def snapshot(self) -> dict[str, object]:
        """Content-free accounting snapshot for the observability record."""
        return {
            "model_id": self.model_id,
            "model_context_window_tokens": self.model_context_window_tokens,
            "reserved_for_output_tokens": self.reserved_for_output_tokens,
            "reserved_for_system_tokens": self.reserved_for_system_tokens,
            "reserved_for_tool_tokens": self.reserved_for_tool_tokens,
            "available_for_context_tokens": self.available_for_context_tokens,
            "used_tokens": self.used_tokens,
            "remaining_tokens": self._remaining,
            "budget_source": self.budget_source.value,
            "declared_required_window_tokens": self.declared_required_window_tokens,
        }

    reserved_for_tool_tokens: int = 0
    budget_source: BudgetSource = BudgetSource.CONSERVATIVE_DEFAULT
    model_id: str = ""
    #: Pass-1 declaration (Gate 2 §1.4), used to report a window shortfall so the
    #: Router can fail over rather than silently degrade.
    declared_required_window_tokens: int = 0

    used_tokens: int = 0
    peak_used_tokens: int = 0
    available_for_context_tokens: int = field(init=False, default=0)
    _remaining: int = field(init=False, default=0, repr=False)
