"""Context selection tests — Minimum Sufficient Context (18-L Gate 3).

Covers the deterministic selection policy from the Gate 2 design: mandatory vs
optional, ranking, tie-breaking, deduplication, and dependency expansion. All
tests are model-free and deterministic.
"""

from __future__ import annotations

import pytest

from autoforge_execution.context_budget import BudgetSource, ContextWindowBudget
from autoforge_execution.context_items import (
    ContextCategory,
    ContextItem,
    ContextSource,
    normalize_content,
    sort_context_items,
)
from autoforge_execution.context_selection import (
    SelectionPolicy,
    deduplicate,
    select_context,
)
from autoforge_execution.errors import (
    MandatoryContextOverflowError,
    UnresolvableDependencyError,
)


def make_item(
    content: str,
    category: ContextCategory = ContextCategory.EVIDENCE,
    ref: str = "s1",
    *,
    required: bool = False,
    relevance: float = 0.5,
    depends_on: tuple[str, ...] = (),
) -> ContextItem:
    return ContextItem(
        content=content,
        category=category,
        source=ContextSource(category.value, ref),
        required=required,
        relevance=relevance,
        depends_on=depends_on,
    )


def make_budget(window: int = 8192, output_reserve: int = 1024) -> ContextWindowBudget:
    return ContextWindowBudget(
        model_context_window_tokens=window,
        reserved_for_output_tokens=output_reserve,
        budget_source=BudgetSource.MODEL_METADATA,
        model_id="test-model",
    )


# --- identity and determinism ---------------------------------------------


def test_context_id_is_deterministic_and_content_derived():
    a = make_item("same body", ref="r1")
    b = make_item("same body", ref="r1")
    c = make_item("different body", ref="r1")
    assert a.context_id == b.context_id
    assert a.context_id != c.context_id


def test_context_id_prefix_shape():
    assert make_item("body").context_id.startswith("ctx_")


def test_normalize_collapses_blank_lines_and_case():
    # Gate 2 section 2.6 defines normalization as NFKC + trailing-whitespace strip +
    # blank-line collapse + casefold. Internal intra-line spacing is preserved.
    assert normalize_content("Hello World  ") == normalize_content("hello world")
    assert normalize_content("a\n\n\nb") == normalize_content("a\nb")
    assert normalize_content("Keep  inner  spacing") == normalize_content("keep  inner  spacing")


def test_ordering_is_stable_across_input_permutations():
    items = [
        make_item("c", ContextCategory.EVIDENCE, "3", relevance=0.5),
        make_item("a", ContextCategory.TASK, "1", relevance=0.5),
        make_item("b", ContextCategory.SYSTEM, "2", relevance=0.5),
    ]
    first = [i.context_id for i in sort_context_items(items)]
    second = [i.context_id for i in sort_context_items(list(reversed(items)))]
    assert first == second


def test_required_items_sort_before_optional():
    opt = make_item("optional", ContextCategory.SYSTEM, "s")
    req = make_item("required", ContextCategory.TEST_OUTPUT, "t", required=True)
    ordered = sort_context_items([opt, req])
    assert ordered[0].context_id == req.context_id


# --- Test 1: relevant context selected -------------------------------------


def test_relevant_context_is_selected():
    relevant = make_item("auth token validation", relevance=0.9)
    result = select_context([relevant], make_budget(), SelectionPolicy())
    assert [i.context_id for i in result.selected] == [relevant.context_id]


# --- Test 2: irrelevant context excluded -----------------------------------


def test_irrelevant_context_excluded_by_relevance_floor():
    items = [make_item("relevant", relevance=0.9), make_item("noise", relevance=0.0)]
    result = select_context(items, make_budget(), SelectionPolicy(min_optional_relevance=0.5))
    assert [i.content for i in result.selected] == ["relevant"]
    assert any("below_min_optional_relevance" in r for _, r in result.excluded)


# --- Test 3: mandatory context preserved -----------------------------------


def test_mandatory_context_survives_when_optional_is_trimmed():
    mandatory = make_item("mandatory objective", ContextCategory.TASK, required=True)
    optional = [
        make_item("filler " * 200 + str(n), ref=f"e{n}", relevance=0.9) for n in range(8)
    ]
    result = select_context(
        [mandatory, *optional], make_budget(window=300, output_reserve=50), SelectionPolicy()
    )
    assert mandatory.context_id in {i.context_id for i in result.selected}
    assert len(result.selected) < len(optional)


# --- Test 8: deduplication -------------------------------------------------


def test_duplicate_content_is_excluded_with_auditable_reason():
    keeper = make_item("identical body", ref="a")
    dup = make_item("identical body", ref="b")
    result = select_context([keeper, dup], make_budget(), SelectionPolicy())
    assert result.deduplicated_count == 1
    assert len(result.selected) == 1
    assert any(r.startswith("duplicate_of:") for _, r in result.excluded)


def test_deduplicate_keeps_first_in_rank_order():
    a = make_item("same", ContextCategory.TASK, "a")
    b = make_item("same", ContextCategory.EVIDENCE, "b")
    kept, count = deduplicate([b, a])
    assert count == 1
    assert len(kept) == 1
    assert kept[0].category is ContextCategory.TASK


# --- Test 4/5: dependency expansion and bounds -----------------------------


def test_dependency_of_mandatory_item_is_expanded():
    dep = make_item("decision D", ContextCategory.DECISION, "d")
    root = make_item(
        "artifact A", ContextCategory.TASK, "a", required=True, depends_on=(dep.context_id,)
    )
    result = select_context([root, dep], make_budget(), SelectionPolicy())
    assert dep.context_id in {i.context_id for i in result.selected}
    assert result.expansion_items_added == 1


def test_expanded_dependency_is_marked_required():
    dep = make_item("decision D", ContextCategory.DECISION, "d")
    root = make_item(
        "artifact A", ContextCategory.TASK, "a", required=True, depends_on=(dep.context_id,)
    )
    result = select_context([root, dep], make_budget(), SelectionPolicy())
    selected = next(i for i in result.selected if i.context_id == dep.context_id)
    assert selected.required


def test_dependency_depth_is_bounded():
    # The depth bound limits *expansion*: with depth 1, `mid` is pulled in at depth 1
    # but its own dependency `deepest` is never reached, so `deepest` keeps
    # dependency_depth 0. It remains an ordinary optional candidate from the pool.
    deepest = make_item("level 3", ContextCategory.DEPENDENCY, "l3")
    mid = make_item("level 2", ContextCategory.DEPENDENCY, "l2", depends_on=(deepest.context_id,))
    root = make_item(
        "level 1", ContextCategory.TASK, "l1", required=True, depends_on=(mid.context_id,)
    )
    result = select_context(
        [root, mid, deepest], make_budget(), SelectionPolicy(max_dependency_depth=1)
    )
    assert result.expansion_depth_reached == 1
    assert result.expansion_items_added == 1
    reached = {i.context_id: i.dependency_depth for i in result.selected}
    assert reached[mid.context_id] == 1
    # Never expanded, so it was not promoted to mandatory by expansion.
    assert reached.get(deepest.context_id, 0) == 0
    assert not any(i.context_id == deepest.context_id and i.required for i in result.selected)

    # With depth 2 the chain is followed all the way and `deepest` becomes mandatory.
    deepest2 = make_item("level 3b", ContextCategory.DEPENDENCY, "l3b")
    mid2 = make_item(
        "level 2b", ContextCategory.DEPENDENCY, "l2b", depends_on=(deepest2.context_id,)
    )
    root2 = make_item(
        "level 1b", ContextCategory.TASK, "l1b", required=True, depends_on=(mid2.context_id,)
    )
    result2 = select_context(
        [root2, mid2, deepest2], make_budget(), SelectionPolicy(max_dependency_depth=2)
    )
    assert result2.expansion_depth_reached == 2
    promoted = next(i for i in result2.selected if i.context_id == deepest2.context_id)
    assert promoted.required
    assert promoted.dependency_depth == 2


def test_expansion_item_count_is_bounded():
    deps = [make_item(f"dep {n}", ContextCategory.DEPENDENCY, f"d{n}") for n in range(10)]
    root = make_item(
        "root",
        ContextCategory.TASK,
        "r",
        required=True,
        depends_on=tuple(d.context_id for d in deps),
    )
    result = select_context(
        [root, *deps], make_budget(), SelectionPolicy(max_expanded_items=3)
    )
    assert result.expansion_items_added == 3
    assert result.expansion_truncated_by_bound is True


def test_cyclic_dependencies_terminate():
    a = make_item("A body", ContextCategory.TASK, "a")
    b = make_item("B body", ContextCategory.DEPENDENCY, "b")
    a.depends_on = (b.context_id,)
    b.depends_on = (a.context_id,)
    a.required = True
    result = select_context([a, b], make_budget(), SelectionPolicy())
    assert len(result.selected) <= 2


def test_unresolvable_mandatory_dependency_raises():
    orphan = make_item(
        "orphan", ContextCategory.TASK, "o", required=True, depends_on=("ctx_nope",)
    )
    with pytest.raises(UnresolvableDependencyError):
        select_context([orphan], make_budget(), SelectionPolicy())


# --- Test 6: budget enforcement --------------------------------------------


def test_selection_never_exceeds_budget():
    items = [make_item("w " * 100 + str(n), ref=f"e{n}", relevance=0.9) for n in range(12)]
    budget = make_budget(window=400, output_reserve=50)
    result = select_context(items, budget, SelectionPolicy())
    assert budget.used_tokens <= budget.available_for_context_tokens
    assert budget.used_tokens == sum(i.estimated_tokens for i in result.selected)


def test_optional_items_trimmed_by_budget_are_explained():
    items = [make_item("z " * 200 + str(n), ref=f"e{n}", relevance=0.9) for n in range(10)]
    result = select_context(items, make_budget(window=300, output_reserve=50), SelectionPolicy())
    assert any(r == "budget_exhausted" for _, r in result.excluded)



def test_mandatory_never_truncated_raises_instead():
    huge = make_item("x " * 5000, ContextCategory.SYSTEM, required=True)
    with pytest.raises(MandatoryContextOverflowError):
        select_context([huge], make_budget(window=100, output_reserve=10), SelectionPolicy())


def test_mandatory_overflow_reports_deterministic_details():
    huge = make_item("y " * 1000, ContextCategory.SYSTEM, required=True)
    with pytest.raises(MandatoryContextOverflowError) as excinfo:
        select_context([huge], make_budget(window=100, output_reserve=10), SelectionPolicy())
    details = excinfo.value.details
    assert details["overage_tokens"] > 0
    assert details["mandatory_tokens"] > details["available_for_context_tokens"]
    assert details["mandatory_context_ids"] == [huge.context_id]
