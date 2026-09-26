"""
Context Selection — Minimum Sufficient Context (MSC) engine.

Gate 2 §2. Implements the approved deterministic policy:

    task → required context → optional context → dependency expansion
         → ranking → deduplication → budget → final ordered context

Three independent expansion bounds (Gate 2 §2.4) prevent recursive explosion:
``max_dependency_depth``, ``max_expanded_items``, and a visited-set cycle guard.

Determinism guarantee: identical candidate inputs always yield an identical ordered
selection, because identity is content-derived and every tie-break terminates in
``context_id``.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from autoforge_execution.context_budget import ContextWindowBudget
from autoforge_execution.context_items import ContextItem, sort_context_items
from autoforge_execution.errors import (
    MandatoryContextOverflowError,
    UnresolvableDependencyError,
)
from autoforge_execution.token_estimator import TokenEstimator, estimate_tokens

#: Gate 2 §2.4 defaults.
DEFAULT_MAX_DEPENDENCY_DEPTH = 2
DEFAULT_MAX_EXPANDED_ITEMS = 64


@dataclass
class SelectionPolicy:
    """Tunable bounds for one assembly. Defaults match the approved design."""

    max_dependency_depth: int = DEFAULT_MAX_DEPENDENCY_DEPTH
    max_expanded_items: int = DEFAULT_MAX_EXPANDED_ITEMS
    #: Items whose relevance falls below this are never admitted, even if optional
    #: budget remains. Keeps obviously irrelevant material out (MSC, not "as much
    #: as fits").
    min_optional_relevance: float = 0.0


@dataclass
class SelectionResult:
    """Outcome of one selection pass."""

    selected: list[ContextItem] = field(default_factory=list)
    excluded: list[tuple[ContextItem, str]] = field(default_factory=list)
    considered_count: int = 0
    deduplicated_count: int = 0
    expansion_depth_reached: int = 0
    expansion_items_added: int = 0
    expansion_truncated_by_bound: bool = False
    char_fallback_used: bool = False


def assign_token_costs(
    items: list[ContextItem],
    estimator: TokenEstimator | None = None,
) -> None:
    """Fill in ``estimated_tokens`` for items that do not carry a cost yet."""
    for item in items:
        if not item.estimated_tokens:
            item.estimated_tokens = estimate_tokens(item.content, estimator)


def deduplicate(items: list[ContextItem]) -> tuple[list[ContextItem], int]:
    """Exact-match dedup on normalized content (Gate 2 §2.6).

    The first occurrence *in rank order* wins; later duplicates are returned to the
    caller with an auditable ``duplicate_of:<id>`` reason rather than vanishing.
    Only exact duplicates are merged — near-duplicate detection is a documented
    limitation, not a silent gap.
    """
    ordered = sort_context_items(items)
    seen: dict[str, str] = {}
    kept: list[ContextItem] = []
    duplicates: list[ContextItem] = []
    for item in ordered:
        digest = item.content_digest
        if digest in seen:
            duplicates.append(item)
        else:
            seen[digest] = item.context_id
            kept.append(item)
    return kept, len(duplicates)


def expand_dependencies(
    roots: list[ContextItem],
    candidates: list[ContextItem],
    policy: SelectionPolicy,
) -> tuple[list[ContextItem], list[ContextItem], int, int, bool]:
    """Breadth-first, bounded dependency expansion from ``roots``.

    Returns ``(added_items, unresolved, depth_reached, items_added, truncated)``.

    A cycle is a no-op, not an error. A *missing* dependency referenced by a
    mandatory item is an error (:class:`UnresolvableDependencyError`); referenced by
    an optional item it is simply reported.
    """
    by_id = {item.context_id: item for item in candidates}
    available = {item.context_id for item in candidates}
    selected_ids = {item.context_id for item in roots}
    added: list[ContextItem] = []
    unresolved: list[tuple[ContextItem, str]] = []

    frontier: list[ContextItem] = list(roots)
    depth_reached = 0
    truncated = False

    for depth in range(1, policy.max_dependency_depth + 1):
        if not frontier:
            break
        depth_reached = depth
        next_frontier: list[ContextItem] = []

        for parent in sorted(frontier, key=lambda i: i.rank_key()):
            for dep_id in parent.depends_on:
                if dep_id in selected_ids:
                    continue  # already present, or a cycle
                if dep_id not in available:
                    unresolved.append((parent, f"unresolved_dependency:{dep_id}"))
                    continue
                if len(added) >= policy.max_expanded_items:
                    truncated = True
                    continue
                dep = by_id[dep_id]
                dep.dependency_depth = depth
                # A dependency pulled in by expansion is required: it exists because
                # something mandatory needed it (Gate 2 §2.2).
                dep.required = True
                selected_ids.add(dep_id)
                added.append(dep)
                next_frontier.append(dep)

        frontier = next_frontier

    return added, unresolved, depth_reached, len(added), truncated


def select_context(
    candidates: list[ContextItem],
    budget: ContextWindowBudget,
    policy: SelectionPolicy | None = None,
    estimator: TokenEstimator | None = None,
) -> SelectionResult:
    """Run the full MSC policy over ``candidates`` under ``budget``.

    Order of operations (Gate 2 §2.3):

    1. price every candidate;
    2. split mandatory vs optional;
    3. expand dependencies from mandatory roots (bounded);
    4. deduplicate;
    5. admit mandatory in rank order — overflow is a hard failure;
    6. admit optional in rank order while budget remains;
    7. return the final ordered selection plus every exclusion and its reason.

    Mandatory context is never truncated, never partially admitted, and never
    silently dropped (Gate 2 §3.3, §9).
    """
    policy = policy or SelectionPolicy()
    result = SelectionResult(considered_count=len(candidates))

    assign_token_costs(candidates, estimator)

    # Legacy safety backstop (Gate 2 §3.4): even with no budget supplied, a single
    # item can never exceed the historical char ceiling.
    char_ceiling = getattr(policy, "max_item_chars", None)
    if char_ceiling:
        for item in candidates:
            if len(item.content) > char_ceiling:
                result.excluded.append((item, "exceeds_legacy_char_backstop"))
                item.exclusion_reason = "exceeds_legacy_char_backstop"

    pool = [i for i in candidates if i.exclusion_reason is None]

    roots = [i for i in pool if i.required]
    added, unresolved, depth, added_count, truncated = expand_dependencies(
        roots, pool, policy
    )
    result.expansion_depth_reached = depth
    result.expansion_items_added = added_count
    result.expansion_truncated_by_bound = truncated

    for parent, reason in unresolved:
        if parent.required:
            raise UnresolvableDependencyError(
                f"mandatory context item {parent.context_id} has an unresolvable dependency",
                details={
                    "context_id": parent.context_id,
                    "category": parent.category.value,
                    "reason": reason,
                },
            )
        result.excluded.append((parent, reason))
        parent.exclusion_reason = reason

    # De-duplicate by context_id (ContextItem is a mutable dataclass and therefore
    # unhashable, so identity is tracked by its deterministic id).
    #
    # The admission pool is roots + expanded dependencies + all remaining optional
    # candidates. Omitting the optional candidates here would silently drop every
    # non-mandatory item, which would defeat Minimum Sufficient Context entirely.
    all_items: list[ContextItem] = []
    seen_ids: set[str] = set()
    for item in (*roots, *added, *pool):
        if item.context_id not in seen_ids:
            seen_ids.add(item.context_id)
            all_items.append(item)

    pool_ids = {i.context_id for i in pool}
    # Dependencies that a bound deliberately left unexpanded are *not* unresolved:
    # they exist and are reachable, they were simply beyond the configured depth or
    # item cap. Reporting them as unresolvable would be a false correctness failure.
    deferred: set[str] = {
        reason.split(":", 1)[1]
        for _, reason in unresolved
        if reason.startswith("unresolved_dependency:")
    }
    deferred.update(
        dep
        for item in all_items
        for dep in item.depends_on
        if dep in {c.context_id for c in candidates}
    )
    for item in all_items:
        for dep in item.depends_on:
            if dep in pool_ids or dep in deferred:
                continue
            reason = f"unresolved_dependency:{dep}"
            if item.required:
                raise UnresolvableDependencyError(
                    f"mandatory context item {item.context_id} has an unresolvable dependency",
                    details={
                        "context_id": item.context_id,
                        "category": item.category.value,
                        "reason": reason,
                    },
                )
            result.excluded.append((item, reason))
            item.exclusion_reason = reason

    kept, dedup_count = deduplicate(all_items)
    result.deduplicated_count = dedup_count

    kept_ids = {i.context_id for i in kept}
    seen_dup_ids: set[str] = set()
    for original in all_items:
        if original.context_id in kept_ids:
            continue
        if original.context_id in seen_dup_ids:
            continue
        seen_dup_ids.add(original.context_id)
        keeper = next(
            (i.context_id for i in kept if i.content_digest == original.content_digest),
            "",
        )
        reason = f"duplicate_of:{keeper}"
        result.excluded.append((original, reason))
        original.exclusion_reason = reason

    mandatory = [i for i in kept if i.required]
    optional = [i for i in kept if not i.required]

    # 5. Mandatory admission — hard failure on overflow.
    admitted: list[ContextItem] = []
    mandatory_cost = sum(i.estimated_tokens for i in mandatory)
    if mandatory_cost > budget.available_for_context_tokens:
        raise MandatoryContextOverflowError(
            "mandatory context does not fit the available context window",
            details={
                "mandatory_tokens": mandatory_cost,
                "available_for_context_tokens": budget.available_for_context_tokens,
                "overage_tokens": mandatory_cost - budget.available_for_context_tokens,
                "model_context_window_tokens": budget.model_context_window_tokens,
                "budget_source": budget.budget_source.value,
                "shortfall_tokens": budget.shortfall_tokens(),
                "mandatory_context_ids": [i.context_id for i in mandatory],
            },
        )
    for item in mandatory:
        budget.try_reserve(item.estimated_tokens)
        admitted.append(item)

    # 6. Optional admission — trim by rank until budget is exhausted.
    for item in optional:
        if item.relevance < policy.min_optional_relevance:
            result.excluded.append((item, "below_min_optional_relevance"))
            item.exclusion_reason = "below_min_optional_relevance"
            continue
        if not budget.try_reserve(item.estimated_tokens):
            result.excluded.append((item, "budget_exhausted"))
            item.exclusion_reason = "budget_exhausted"
            continue
        admitted.append(item)

    result.selected = sort_context_items(admitted)
    return result
