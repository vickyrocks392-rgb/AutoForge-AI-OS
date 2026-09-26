"""Context budget tests — model-aware, request-scoped budgeting (18-L Gate 3).

Verifies Gate 2 section 3: window derivation, reservation accounting, mandatory
overflow as a hard failure, and model-awareness driven by existing registry
metadata rather than any hardcoded model.
"""

from __future__ import annotations

import pytest

from autoforge_execution.context_budget import (
    CONSERVATIVE_DEFAULT_OUTPUT_RESERVE_TOKENS,
    CONSERVATIVE_DEFAULT_WINDOW_TOKENS,
    BudgetSource,
    ContextWindowBudget,
)
from autoforge_execution.context_items import ContextCategory, ContextItem, ContextSource
from autoforge_execution.context_selection import SelectionPolicy, select_context
from autoforge_execution.errors import InvalidBudgetError, MandatoryContextOverflowError
from autoforge_execution.token_estimator import (
    DEFAULT_TOKEN_ESTIMATOR,
    HeuristicTokenEstimator,
    estimate_tokens,
)


# --- token estimation ------------------------------------------------------


def test_estimate_is_deterministic():
    text = "def foo(a, b):\n    return a + b\n"
    assert estimate_tokens(text) == estimate_tokens(text)


def test_estimate_is_non_negative_and_zero_for_empty():
    assert estimate_tokens("") == 0
    assert estimate_tokens("hello world") > 0


def test_estimate_grows_with_content():
    assert estimate_tokens("a " * 100) > estimate_tokens("a")


def test_estimator_applies_a_conservative_margin():
    plain = HeuristicTokenEstimator(safety_margin=1.0)
    padded = HeuristicTokenEstimator(safety_margin=2.0)
    text = "alpha beta gamma delta"
    assert padded.estimate(text) > plain.estimate(text)


def test_estimator_rejects_under_counting_margin():
    with pytest.raises(ValueError):
        HeuristicTokenEstimator(safety_margin=0.5)


def test_default_estimator_exposes_estimate():
    assert hasattr(DEFAULT_TOKEN_ESTIMATOR, "estimate")


# --- budget construction / model awareness ---------------------------------


def test_available_is_window_minus_reservations():
    budget = ContextWindowBudget(
        model_context_window_tokens=4096,
        reserved_for_output_tokens=1024,
        reserved_for_system_tokens=256,
        reserved_for_tool_tokens=128,
    )
    assert budget.available_for_context_tokens == 4096 - 1024 - 256 - 128


def test_output_reservation_reduces_context_capacity():
    small = ContextWindowBudget(
        model_context_window_tokens=4096, reserved_for_output_tokens=256
    )
    large = ContextWindowBudget(
        model_context_window_tokens=4096, reserved_for_output_tokens=2048
    )
    assert small.available_for_context_tokens > large.available_for_context_tokens


def test_budget_source_is_recorded():
    budget = ContextWindowBudget(
        model_context_window_tokens=2048,
        budget_source=BudgetSource.MODEL_METADATA,
        model_id="registry-model",
    )
    assert budget.snapshot()["budget_source"] == "model_metadata"
    assert budget.snapshot()["model_id"] == "registry-model"


def test_default_window_is_conservative_and_labelled():
    assert CONSERVATIVE_DEFAULT_WINDOW_TOKENS <= 8192
    assert CONSERVATIVE_DEFAULT_OUTPUT_RESERVE_TOKENS > 0


def test_reservations_exceeding_window_raise():
    with pytest.raises(InvalidBudgetError):
        ContextWindowBudget(
            model_context_window_tokens=100, reserved_for_output_tokens=200
        )


def test_negative_window_raises():
    with pytest.raises(InvalidBudgetError):
        ContextWindowBudget(model_context_window_tokens=-1)


# --- accounting ------------------------------------------------------------


def test_try_reserve_respects_remaining():
    budget = ContextWindowBudget(model_context_window_tokens=100, reserved_for_output_tokens=0)
    assert budget.try_reserve(60) is True
    assert budget.remaining_tokens == 40
    assert budget.try_reserve(50) is False
    assert budget.remaining_tokens == 40


def test_release_returns_tokens_to_pool():
    budget = ContextWindowBudget(model_context_window_tokens=100, reserved_for_output_tokens=0)
    budget.try_reserve(70)
    budget.release(70)
    assert budget.remaining_tokens == 100
    assert budget.used_tokens == 0


def test_peak_usage_tracked():
    budget = ContextWindowBudget(model_context_window_tokens=100, reserved_for_output_tokens=0)
    budget.try_reserve(80)
    budget.release(80)
    budget.try_reserve(30)
    assert budget.peak_used_tokens == 80


def test_negative_reserve_raises():
    budget = ContextWindowBudget(model_context_window_tokens=100, reserved_for_output_tokens=0)
    with pytest.raises(InvalidBudgetError):
        budget.try_reserve(-1)


def test_shortfall_reported_when_window_below_declaration():
    budget = ContextWindowBudget(
        model_context_window_tokens=1000, declared_required_window_tokens=4000
    )
    assert budget.shortfall_tokens() == 3000
    ok = ContextWindowBudget(
        model_context_window_tokens=4000, declared_required_window_tokens=1000
    )
    assert ok.shortfall_tokens() == 0


# --- mandatory overflow (Test 7) -------------------------------------------


def test_mandatory_overflow_raises_and_does_not_truncate():
    item = ContextItem(
        content="x " * 3000,
        category=ContextCategory.SYSTEM,
        source=ContextSource("system", "s"),
        required=True,
    )
    budget = ContextWindowBudget(
        model_context_window_tokens=64, reserved_for_output_tokens=8
    )
    with pytest.raises(MandatoryContextOverflowError) as excinfo:
        select_context([item], budget, SelectionPolicy())
    assert excinfo.value.details["mandatory_tokens"] > 0
    # The original content was never rewritten or shortened.
    assert len(item.content) == 6000


def test_smaller_model_window_causes_explicit_failure():
    """A narrower selected model must fail loudly rather than silently degrade."""
    item = ContextItem(
        content="y " * 2000,
        category=ContextCategory.TASK,
        source=ContextSource("task", "t"),
        required=True,
    )
    wide = ContextWindowBudget(
        model_context_window_tokens=8192,
        reserved_for_output_tokens=1024,
        budget_source=BudgetSource.MODEL_METADATA,
        model_id="wide",
    )
    assert select_context([item], wide, SelectionPolicy()).selected

    narrow = ContextWindowBudget(
        model_context_window_tokens=128,
        reserved_for_output_tokens=16,
        budget_source=BudgetSource.MODEL_METADATA,
        model_id="narrow",
    )
    with pytest.raises(MandatoryContextOverflowError):
        select_context([item], narrow, SelectionPolicy())
